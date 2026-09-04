from __future__ import annotations

from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.schemas import (
    CollectionRunOut,
    DeviceOut,
    HealthOut,
    MacDetailOut,
    MacListItem,
    TenantOut,
)
from app.core.db import get_db
from app.core.ip import normalize_ip
from app.core.mac import normalize_mac
from app.services.query import QueryService

app = FastAPI(
    title="Madalena Network Intelligence",
    version="0.4.0",
    description="Multi-tenant network inventory, topology, and MAC/IP/ONU correlation API",
)


@app.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(status="ok")


@app.get("/ready", response_model=HealthOut)
def ready(db: Session = Depends(get_db)) -> HealthOut:
    db.execute(text("SELECT 1"))
    return HealthOut(status="ok")


@app.get("/tenants", response_model=list[TenantOut])
def list_tenants(db: Session = Depends(get_db)) -> list[TenantOut]:
    return QueryService(db).list_tenants()


@app.get("/devices", response_model=list[DeviceOut])
def list_devices(
    tenant: str = Query(..., description="Tenant slug (required for isolation)"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[DeviceOut]:
    try:
        return QueryService(db).list_devices(tenant, limit=limit, offset=offset)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/devices/{device_id}", response_model=DeviceOut)
def get_device(
    device_id: UUID,
    tenant: str = Query(...),
    db: Session = Depends(get_db),
) -> DeviceOut:
    try:
        device = QueryService(db).get_device(tenant, device_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")
    return device


@app.get("/devices/{device_id}/neighbors")
def get_device_neighbors(
    device_id: UUID,
    tenant: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        data = QueryService(db).device_neighbors(tenant, device_id, limit=limit, offset=offset)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not data.get("found"):
        raise HTTPException(status_code=404, detail="device not found")
    return data


@app.get("/devices/{device_id}/links")
def get_device_links(
    device_id: UUID,
    tenant: str = Query(...),
    include_history: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        data = QueryService(db).device_links(
            tenant,
            device_id,
            include_history=include_history,
            limit=limit,
            offset=offset,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not data.get("found"):
        raise HTTPException(status_code=404, detail="device not found")
    return data


@app.get("/topology")
def get_topology(
    tenant: str = Query(...),
    include_history: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        return QueryService(db).get_topology(
            tenant, include_history=include_history, limit=limit, offset=offset
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/macs", response_model=list[MacListItem])
def list_macs(
    tenant: str = Query(...),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[MacListItem]:
    try:
        rows = QueryService(db).list_macs(tenant, limit=limit, offset=offset)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [MacListItem(mac=r.mac, first_seen=r.first_seen, last_seen=r.last_seen) for r in rows]


@app.get("/macs/{mac}", response_model=MacDetailOut)
def get_mac(
    mac: str,
    tenant: str = Query(...),
    db: Session = Depends(get_db),
) -> MacDetailOut:
    try:
        mac_n = normalize_mac(mac)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        corr = QueryService(db).find_mac(tenant, mac_n)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if corr is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    data = corr.to_dict()
    if not any(
        [
            data["dhcp"],
            data["arp"],
            data["fdb"],
            data["olt_macs"],
            data.get("neighbors"),
            data["first_seen"],
        ]
    ):
        raise HTTPException(status_code=404, detail="mac not found in tenant")
    return MacDetailOut(**data)


@app.get("/macs/{mac}/history")
def get_mac_history(mac: str, tenant: str = Query(...), db: Session = Depends(get_db)):
    try:
        normalize_mac(mac)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        data = QueryService(db).mac_history(tenant, mac)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not data.get("found"):
        raise HTTPException(status_code=404, detail="mac not found in tenant")
    return data


@app.get("/ips/{ip}")
def get_ip(ip: str, tenant: str = Query(...), db: Session = Depends(get_db)):
    try:
        normalize_ip(ip)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return QueryService(db).find_ip(tenant, ip)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/collection-runs", response_model=list[CollectionRunOut])
def collection_runs(
    tenant: str = Query(...),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[CollectionRunOut]:
    try:
        return QueryService(db).collection_runs(tenant, limit=limit, offset=offset)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
