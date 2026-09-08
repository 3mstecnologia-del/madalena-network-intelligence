from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def local_day_bounds(target: date, tz_name: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(tz_name)
    start = datetime.combine(target, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    return start, end


def yesterday_bounds(now: datetime | None = None, tz_name: str = "America/Sao_Paulo") -> tuple[datetime, datetime, date]:
    tz = ZoneInfo(tz_name)
    now = now or datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    local = now.astimezone(tz)
    target = (local.date() - timedelta(days=1))
    start, end = local_day_bounds(target, tz_name)
    return start, end, target


def parse_period(value: str) -> tuple[date, date] | None:
    value = (value or "").strip()
    if not value:
        return None
    if ".." in value:
        a, b = value.split("..", 1)
        return date.fromisoformat(a.strip()), date.fromisoformat(b.strip())
    if ":" in value:
        a, b = value.split(":", 1)
        return date.fromisoformat(a.strip()), date.fromisoformat(b.strip())
    d = date.fromisoformat(value)
    return d, d
