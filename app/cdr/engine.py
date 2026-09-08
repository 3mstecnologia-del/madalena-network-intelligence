from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.cdr.models import CdrCanonicalCall, CdrDashboard, CdrFilters, CdrLeg
from app.cdr.timeutils import parse_period, yesterday_bounds
from app.core.config import get_settings

STATUS_ANSWERED = {"ANSWERED"}
STATUS_MISSED = {"NO ANSWER", "BUSY", "FAILED"}
INBOUND_CONTEXTS = {"entrada_algar"}
OUTBOUND_CONTEXTS = {"ramais"}


def _clean(text_value: str | None) -> str:
    return (text_value or "").strip()


def _digits(value: str | None) -> str:
    if not value:
        return ""
    return "".join(ch for ch in value if ch.isdigit())


def _normal_label(value: str | None) -> str | None:
    value = _clean(value)
    return value or None


def _is_local_channel(value: str | None) -> bool:
    return (_clean(value).lower().startswith("local/"))


def _channel_extension(value: str | None) -> str | None:
    value = _clean(value)
    if not value:
        return None
    if value.lower().startswith("sip/"):
        rest = value.split("/", 1)[1]
        return rest.split("-", 1)[0] or None
    if value.lower().startswith("local/"):
        rest = value.split("/", 1)[1]
        return rest.split("@", 1)[0].split("-", 1)[0] or None
    return None


def _trunk_name(channel: str | None, dstchannel: str | None) -> str | None:
    for value in (_clean(channel), _clean(dstchannel)):
        low = value.lower()
        if "algar" in low:
            return "ALGAR"
        if "mhnet" in low:
            return "MHNET"
        if low.startswith("sip/"):
            return value.split("/", 1)[1].split("-", 1)[0]
    return None


def _direction(dcontext: str | None, channel: str | None, dstchannel: str | None, src: str | None, dst: str | None) -> str:
    ctx = _clean(dcontext).lower()
    if ctx in INBOUND_CONTEXTS:
        return "inbound"
    if ctx in OUTBOUND_CONTEXTS:
        return "outbound"
    if _is_local_channel(channel) and not _is_local_channel(dstchannel):
        return "outbound"
    if _digits(dst).startswith("32") and _digits(src):
        return "inbound"
    return "unknown"


def _status(dispositions: Iterable[str]) -> tuple[str, bool]:
    disp = [d for d in dispositions if d]
    if any(d == "ANSWERED" for d in disp):
        return "answered", True
    if any(d in STATUS_MISSED for d in disp):
        return "missed", False
    return "unknown", False


def _read_legs(db: Session, *, start: datetime, end: datetime) -> list[CdrLeg]:
    rows = db.execute(
        text(
            """
            SELECT calldate, linkedid, uniqueid, src, dst, dcontext, channel, dstchannel,
                   lastapp, lastdata, duration, billsec, disposition, accountcode,
                   userfield, peeraccount, sequence
            FROM (
                SELECT calldate, linkedid, uniqueid, src, dst, dcontext, channel, dstchannel,
                       lastapp, lastdata, duration, billsec, disposition, accountcode,
                       userfield, peeraccount, sequence
                FROM public.cdr
                UNION ALL
                SELECT calldate, uniqueid AS linkedid, uniqueid, src, dst, dcontext, channel, dstchannel,
                       lastapp, lastdata, duration, billsec, disposition, accountcode,
                       userfield, NULL::text AS peeraccount, NULL::integer AS sequence
                FROM public.cdr_antigo
            ) AS cdr_all
            WHERE calldate >= :start AND calldate < :end
            ORDER BY linkedid, calldate, sequence, uniqueid
            """
        ),
        {"start": start.replace(tzinfo=None), "end": end.replace(tzinfo=None)},
    ).mappings().all()
    return [
        CdrLeg(
            calldate=row["calldate"],
            linkedid=str(row["linkedid"] or ""),
            uniqueid=_clean(row["uniqueid"]),
            src=_clean(row["src"]),
            dst=_clean(row["dst"]),
            dcontext=_clean(row["dcontext"]),
            channel=_clean(row["channel"]),
            dstchannel=_clean(row["dstchannel"]),
            lastapp=_clean(row["lastapp"]),
            lastdata=_clean(row["lastdata"]),
            duration=row["duration"] if row["duration"] is not None else 0,
            billsec=row["billsec"] if row["billsec"] is not None else 0,
            disposition=_clean(row["disposition"]),
            accountcode=_clean(row["accountcode"]),
            userfield=_clean(row["userfield"]),
            peeraccount=_clean(row["peeraccount"]),
            sequence=row["sequence"],
        )
        for row in rows
    ]


class CdrEngine:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    def resolve_filters(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        period: str | None = None,
        direction: str | None = None,
        status: str | None = None,
        extension: str | None = None,
        source: str | None = None,
        destination: str | None = None,
        trunk: str | None = None,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        sort: str = "first_seen_desc",
        timezone: str | None = None,
    ) -> CdrFilters:
        tz = timezone or self.settings.cdr_db_timezone
        if period:
            parsed = parse_period(period)
            if parsed is not None:
                start_date, end_date = parsed
                start = start_date
                end = end_date
        if start is None or end is None:
            _, _, yesterday = yesterday_bounds(tz_name=tz)
            start = start or yesterday
            end = end or yesterday
        if isinstance(start, date) and not isinstance(start, datetime):
            start_dt = datetime.combine(start, datetime.min.time())
        else:
            start_dt = start  # type: ignore[assignment]
        if isinstance(end, date) and not isinstance(end, datetime):
            end_dt = datetime.combine(end, datetime.min.time()) + timedelta(days=1)
        else:
            end_dt = end  # type: ignore[assignment]
        assert isinstance(start_dt, datetime)
        assert isinstance(end_dt, datetime)
        limit = min(limit or self.settings.cdr_default_limit, self.settings.cdr_max_limit)
        return CdrFilters(
            start=start_dt,
            end=end_dt,
            direction=(direction or None),
            status=(status or None),
            extension=(extension or None),
            source=(source or None),
            destination=(destination or None),
            trunk=(trunk or None),
            search=(search or None),
            limit=limit,
            offset=offset,
            sort=sort,
        )

    def canonical_calls(self, filters: CdrFilters) -> list[CdrCanonicalCall]:
        legs = _read_legs(self.db, start=filters.start, end=filters.end)
        grouped: dict[str, list[CdrLeg]] = defaultdict(list)
        for leg in legs:
            if not leg.linkedid:
                continue
            grouped[leg.linkedid].append(leg)
        calls: list[CdrCanonicalCall] = []
        for linkedid, items in grouped.items():
            first = min(i.calldate for i in items)
            last = max(i.calldate for i in items)
            dispositions = [i.disposition for i in items if i.disposition]
            status, answered = _status(dispositions)
            direction = _direction(items[0].dcontext, items[0].channel, items[0].dstchannel, items[0].src, items[0].dst)
            src = _normal_label(items[0].src)
            dst = _normal_label(items[0].dst)
            ext = None
            for item in items:
                ext = ext or _channel_extension(item.dstchannel) or _channel_extension(item.channel)
            trunk = _trunk_name(items[0].channel, items[0].dstchannel)
            total_duration = sum(i.duration or 0 for i in items)
            total_billsec = sum(i.billsec or 0 for i in items)
            ring_time = max(total_duration - total_billsec, 0)
            call = CdrCanonicalCall(
                linkedid=linkedid,
                first_seen=first,
                last_seen=last,
                source=src,
                destination=dst,
                direction=direction,
                status=status,
                answered=answered,
                legs=len(items),
                billsec=total_billsec,
                duration=total_duration,
                channel_count=len({i.channel for i in items if i.channel}),
                dcontexts=sorted({i.dcontext for i in items if i.dcontext}),
                channel_labels=sorted({i.channel for i in items if i.channel}),
                dispositions=sorted({i.disposition for i in items if i.disposition}),
                ring_time=ring_time,
                trunk=trunk,
                trunk_channel=items[0].channel,
                extension=ext,
                raw={"legs": [asdict(i) for i in items]},
            )
            calls.append(call)
        calls = self._apply_filters(calls, filters)
        calls = self._sort_and_paginate(calls, filters)
        return calls

    def dashboard(self, filters: CdrFilters) -> CdrDashboard:
        calls = self.canonical_calls(replace(filters, limit=self.settings.cdr_max_limit, offset=0))
        total_calls = len(calls)
        inbound = sum(1 for c in calls if c.direction == "inbound")
        outbound = sum(1 for c in calls if c.direction == "outbound")
        answered = sum(1 for c in calls if c.answered)
        missed = sum(1 for c in calls if c.status == "missed")
        total_duration = sum(c.duration for c in calls)
        total_billsec = sum(c.billsec for c in calls)
        total_legs = sum(c.legs for c in calls)
        answer_rate = round((answered / total_calls) * 100, 1) if total_calls else 0.0
        ext_rank = Counter(c.extension or "Sem ramal" for c in calls)
        src_rank = Counter(c.source or "Sem origem" for c in calls)
        dst_rank = Counter(c.destination or "Sem destino" for c in calls)
        hourly = Counter(c.first_seen.hour for c in calls)
        return CdrDashboard(
            period_start=filters.start,
            period_end=filters.end,
            total_calls=total_calls,
            inbound_calls=inbound,
            outbound_calls=outbound,
            answered_calls=answered,
            missed_calls=missed,
            answer_rate=answer_rate,
            total_duration=total_duration,
            total_billsec=total_billsec,
            total_legs=total_legs,
            extensions=[{"label": k, "count": v} for k, v in ext_rank.most_common(10)],
            sources=[{"label": k, "count": v} for k, v in src_rank.most_common(10)],
            destinations=[{"label": k, "count": v} for k, v in dst_rank.most_common(10)],
            hourly_distribution=[{"hour": h, "count": hourly.get(h, 0)} for h in range(24)],
            canonical_calls=calls,
        )

    def yesterday_dashboard(self) -> CdrDashboard:
        start, end, _ = yesterday_bounds(tz_name=self.settings.cdr_db_timezone)
        return self.dashboard(CdrFilters(start=start, end=end, limit=self.settings.cdr_max_limit))

    def _apply_filters(self, calls: list[CdrCanonicalCall], filters: CdrFilters) -> list[CdrCanonicalCall]:
        result = []
        for call in calls:
            if filters.direction and call.direction != filters.direction:
                continue
            if filters.status and call.status != filters.status:
                continue
            if filters.extension and call.extension != filters.extension:
                continue
            if filters.source and call.source != filters.source:
                continue
            if filters.destination and call.destination != filters.destination:
                continue
            if filters.trunk and (call.trunk or "") != filters.trunk:
                continue
            if filters.search:
                needle = filters.search.lower()
                hay = " ".join(
                    [call.linkedid, call.source or "", call.destination or "", call.extension or "", call.trunk or ""]
                ).lower()
                if needle not in hay:
                    continue
            result.append(call)
        return result

    def _sort_and_paginate(self, calls: list[CdrCanonicalCall], filters: CdrFilters) -> list[CdrCanonicalCall]:
        reverse = True
        key = lambda c: c.first_seen
        if filters.sort == "first_seen_asc":
            reverse = False
        elif filters.sort == "duration_desc":
            key = lambda c: c.duration
        elif filters.sort == "duration_asc":
            key = lambda c: c.duration
            reverse = False
        elif filters.sort == "billsec_desc":
            key = lambda c: c.billsec
        elif filters.sort == "billsec_asc":
            key = lambda c: c.billsec
            reverse = False
        calls = sorted(calls, key=key, reverse=reverse)
        return calls[filters.offset : filters.offset + filters.limit]

    def validate_no_double_count(self, filters: CdrFilters) -> dict[str, int]:
        calls = self.canonical_calls(replace(filters, limit=self.settings.cdr_max_limit, offset=0))
        legs = _read_legs(self.db, start=filters.start, end=filters.end)
        linkedids = {c.linkedid for c in calls}
        return {
            "raw_legs": len(legs),
            "canonical_calls": len(calls),
            "distinct_linkedid": len(linkedids),
            "legs_minus_calls": len(legs) - len(calls),
        }

