from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.cdr.auth import get_basic_identity
from app.cdr.db import get_cdr_db
from app.cdr.schemas import CdrAuthOut, CdrCanonicalCallOut, CdrDashboardOut, CdrReportOut
from app.cdr.service import CdrPortalService

router = APIRouter(tags=["cdr"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "cdr-lesante-portal"}


@router.get("/ready")
def ready(db: Session = Depends(get_cdr_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "service": "cdr-lesante-portal"}


@router.get("/auth/me", response_model=CdrAuthOut)
def auth_me(request: Request) -> CdrAuthOut:
    identity = get_basic_identity(request)
    if not identity.authenticated:
        raise HTTPException(status_code=401, detail="auth required", headers={"WWW-Authenticate": "Basic"})
    return CdrAuthOut(authenticated=True, username=identity.username)


@router.get("/api/dashboard", response_model=CdrDashboardOut)
def dashboard(
    request: Request,
    db: Session = Depends(get_cdr_db),
    start: str | None = Query(None),
    end: str | None = Query(None),
    period: str | None = Query(None),
    direction: str | None = Query(None),
    status: str | None = Query(None),
    extension: str | None = Query(None),
    source: str | None = Query(None),
    destination: str | None = Query(None),
    trunk: str | None = Query(None),
    search: str | None = Query(None),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: str = Query("first_seen_desc"),
) -> CdrDashboardOut:
    identity = get_basic_identity(request)
    if not identity.authenticated:
        raise HTTPException(status_code=401, detail="auth required", headers={"WWW-Authenticate": "Basic"})
    service = CdrPortalService(db)
    dash = service.dashboard(
        start=start,
        end=end,
        period=period,
        direction=direction,
        status=status,
        extension=extension,
        source=source,
        destination=destination,
        trunk=trunk,
        search=search,
        limit=limit,
        offset=offset,
        sort=sort,
    )
    return CdrDashboardOut.model_validate(dash)


@router.get("/api/calls", response_model=list[CdrCanonicalCallOut])
def calls(
    request: Request,
    db: Session = Depends(get_cdr_db),
    start: str | None = Query(None),
    end: str | None = Query(None),
    period: str | None = Query(None),
    direction: str | None = Query(None),
    status: str | None = Query(None),
    extension: str | None = Query(None),
    source: str | None = Query(None),
    destination: str | None = Query(None),
    trunk: str | None = Query(None),
    search: str | None = Query(None),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: str = Query("first_seen_desc"),
) -> list[CdrCanonicalCallOut]:
    identity = get_basic_identity(request)
    if not identity.authenticated:
        raise HTTPException(status_code=401, detail="auth required", headers={"WWW-Authenticate": "Basic"})
    service = CdrPortalService(db)
    dash = service.dashboard(
        start=start,
        end=end,
        period=period,
        direction=direction,
        status=status,
        extension=extension,
        source=source,
        destination=destination,
        trunk=trunk,
        search=search,
        limit=limit,
        offset=offset,
        sort=sort,
    )
    return [CdrCanonicalCallOut(**c.__dict__) for c in dash.canonical_calls]


@router.get("/api/report/yesterday", response_model=CdrReportOut)
def report_yesterday(request: Request, db: Session = Depends(get_cdr_db)) -> CdrReportOut:
    identity = get_basic_identity(request)
    if not identity.authenticated:
        raise HTTPException(status_code=401, detail="auth required", headers={"WWW-Authenticate": "Basic"})
    service = CdrPortalService(db)
    dash, html = service.report(period="yesterday")
    return CdrReportOut(
        title="Relatório CDR de ontem",
        generated_at=datetime.now(timezone.utc),
        period_start=dash.period_start,
        period_end=dash.period_end,
        summary_html=service.dashboard_html(dash),
        html=html,
        dashboard=CdrDashboardOut.model_validate(dash),
    )


@router.get("/api/report", response_model=CdrReportOut)
def report_filtered(
    request: Request,
    db: Session = Depends(get_cdr_db),
    start: str | None = Query(None),
    end: str | None = Query(None),
    period: str | None = Query(None),
    direction: str | None = Query(None),
    status: str | None = Query(None),
    extension: str | None = Query(None),
    source: str | None = Query(None),
    destination: str | None = Query(None),
    trunk: str | None = Query(None),
    search: str | None = Query(None),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: str = Query("first_seen_desc"),
) -> CdrReportOut:
    identity = get_basic_identity(request)
    if not identity.authenticated:
        raise HTTPException(status_code=401, detail="auth required", headers={"WWW-Authenticate": "Basic"})
    service = CdrPortalService(db)
    dash, html = service.report(
        start=start,
        end=end,
        period=period,
        direction=direction,
        status=status,
        extension=extension,
        source=source,
        destination=destination,
        trunk=trunk,
        search=search,
        limit=limit,
        offset=offset,
        sort=sort,
    )
    return CdrReportOut(
        title="Relatório CDR filtrado",
        generated_at=datetime.now(timezone.utc),
        period_start=dash.period_start,
        period_end=dash.period_end,
        summary_html=service.dashboard_html(dash),
        html=html,
        dashboard=CdrDashboardOut.model_validate(dash),
    )


@router.get("/api/validate/no-double-count")
def validate_no_double_count(request: Request, db: Session = Depends(get_cdr_db)) -> dict[str, int]:
    identity = get_basic_identity(request)
    if not identity.authenticated:
        raise HTTPException(status_code=401, detail="auth required", headers={"WWW-Authenticate": "Basic"})
    service = CdrPortalService(db)
    dash = service.dashboard()
    filters = service.engine.resolve_filters(start=dash.period_start.date(), end=dash.period_end.date())
    return service.engine.validate_no_double_count(filters)

