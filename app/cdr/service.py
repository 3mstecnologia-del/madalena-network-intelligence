from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.cdr.engine import CdrEngine
from app.cdr.models import CdrDashboard, CdrFilters
from app.cdr.reporting import dashboard_html, report_html
from app.cdr.timeutils import yesterday_bounds
from app.core.config import get_settings


class CdrPortalService:
    def __init__(self, db: Session):
        self.db = db
        self.engine = CdrEngine(db)
        self.settings = get_settings()

    def resolve_period(self, *, start: str | None = None, end: str | None = None, period: str | None = None) -> tuple[datetime, datetime]:
        tz = ZoneInfo(self.settings.cdr_db_timezone)
        if period:
            normalized = period.strip().lower()
            if normalized == "yesterday":
                return yesterday_bounds(tz_name=self.settings.cdr_db_timezone)[:2]
            start_date, end_date = self._parse_period(period)
            return self._date_bounds(start_date, tz), self._date_bounds(end_date, tz, plus_one=True)
        if start and end:
            return self._date_bounds(date.fromisoformat(start), tz), self._date_bounds(date.fromisoformat(end), tz, plus_one=True)
        start_dt, end_dt, _ = yesterday_bounds(tz_name=self.settings.cdr_db_timezone)
        return start_dt, end_dt

    def dashboard(self, *, start: str | None = None, end: str | None = None, period: str | None = None, direction: str | None = None, status: str | None = None, extension: str | None = None, source: str | None = None, destination: str | None = None, trunk: str | None = None, search: str | None = None, limit: int | None = None, offset: int = 0, sort: str = "first_seen_desc") -> CdrDashboard:
        s, e = self.resolve_period(start=start, end=end, period=period)
        filters = CdrFilters(start=s, end=e, direction=direction, status=status, extension=extension, source=source, destination=destination, trunk=trunk, search=search, limit=limit or self.settings.cdr_default_limit, offset=offset, sort=sort)
        return self.engine.dashboard(filters)

    def yesterday(self) -> CdrDashboard:
        return self.engine.yesterday_dashboard()

    def report(self, *, start: str | None = None, end: str | None = None, period: str | None = None, direction: str | None = None, status: str | None = None, extension: str | None = None, source: str | None = None, destination: str | None = None, trunk: str | None = None, search: str | None = None, limit: int | None = None, offset: int = 0, sort: str = "first_seen_desc") -> tuple[CdrDashboard, str]:
        dash = self.dashboard(start=start, end=end, period=period, direction=direction, status=status, extension=extension, source=source, destination=destination, trunk=trunk, search=search, limit=limit, offset=offset, sort=sort)
        filters = {
            "Período": period or (f"{start}..{end}" if start and end else "Ontem"),
            "Direção": direction or "",
            "Status": status or "",
            "Ramal": extension or "",
            "Origem": source or "",
            "Destino": destination or "",
            "Tronco": trunk or "",
            "Busca": search or "",
        }
        html = report_html(dash, "Relatório CDR LeSante", filters)
        return dash, html

    def dashboard_html(self, dash: CdrDashboard) -> str:
        return dashboard_html(dash)

    def _parse_period(self, value: str) -> tuple[date, date]:
        if ".." in value:
            a, b = value.split("..", 1)
            return date.fromisoformat(a.strip()), date.fromisoformat(b.strip())
        if ":" in value:
            a, b = value.split(":", 1)
            return date.fromisoformat(a.strip()), date.fromisoformat(b.strip())
        d = date.fromisoformat(value)
        return d, d

    def _date_bounds(self, value: date, tz: ZoneInfo, plus_one: bool = False) -> datetime:
        dt = datetime.combine(value, datetime.min.time(), tzinfo=tz)
        if plus_one:
            dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            dt = dt + timedelta(days=1)
        return dt
