"""MCP-facing tool HTTP server.

Phase 1 exposes tools over HTTP JSON for Hermes/lab use.
Full MCP stdio/SSE protocol can wrap these handlers later without changing tool semantics.
Tenant is always required — no implicit cross-tenant access.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.mac import normalize_mac
from app.services.query import QueryService

app = FastAPI(title="Madalena NI MCP Tools", version="0.3.0")


class ToolRequest(BaseModel):
    tenant: str = Field(..., description="Tenant slug — required for isolation")
    mac: Optional[str] = None
    ip: Optional[str] = None
    device_id: Optional[UUID] = None
    limit: int = 50


def _db() -> Session:
    return SessionLocal()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "madalena-ni-mcp"}


@app.get("/ready")
def ready() -> dict[str, str]:
    db = _db()
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "service": "madalena-ni-mcp", "database": "ok"}
    finally:
        db.close()


@app.get("/tools")
def list_tools() -> dict[str, Any]:
    return {
        "tools": [
            {"name": "find_mac", "params": ["tenant", "mac"]},
            {"name": "find_ip", "params": ["tenant", "ip"]},
            {"name": "get_device", "params": ["tenant", "device_id"]},
            {"name": "list_devices", "params": ["tenant"]},
            {"name": "list_tenant_network_assets", "params": ["tenant", "limit?"]},
            {"name": "get_mac_history", "params": ["tenant", "mac"]},
            {"name": "get_collection_status", "params": ["tenant", "limit?"]},
        ]
    }


def _concise_mac(corr) -> str:
    if corr is None:
        return "not found"
    lines = [f"MAC: {corr.mac}", f"tenant: {corr.tenant}"]
    if corr.hostname:
        lines.append(f"hostname: {corr.hostname}")
    if corr.current_ips:
        lines.append("IPs: " + ", ".join(i["ip"] for i in corr.current_ips))
    if corr.current_locations:
        loc = corr.current_locations[0]
        lines.append(
            f"location: {loc.get('device')} iface={loc.get('interface')} source={loc.get('source')}"
        )
    if corr.conflicts:
        lines.append("conflicts: " + ", ".join(c.get("kind", "?") for c in corr.conflicts))
    if corr.dhcp:
        d = corr.dhcp[0]
        lines.append(f"DHCP: {d.get('ip')} via {d.get('device')} server={d.get('server')}")
    if corr.fdb:
        f = corr.fdb[0]
        lines.append(f"FDB: {f.get('device')} port={f.get('interface')} vlan={f.get('vlan_id')}")
    if corr.access_path:
        a = corr.access_path
        lines.append(f"OLT: {a.olt_device} PON={a.pon} ONU={a.onu} profile={a.profile}")
    if corr.first_seen:
        lines.append(f"first_seen: {corr.first_seen.isoformat()}")
    if corr.last_seen:
        lines.append(f"last_seen: {corr.last_seen.isoformat()}")
    lines.append("sources: " + ", ".join(corr.sources))
    return "\n".join(lines)


@app.post("/tools/find_mac")
def find_mac(body: ToolRequest) -> dict[str, Any]:
    if not body.mac:
        raise HTTPException(400, "mac required")
    db = _db()
    try:
        try:
            mac = normalize_mac(body.mac)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        qs = QueryService(db)
        try:
            corr = qs.find_mac(body.tenant, mac)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        if corr is None or not any(
            [corr.dhcp, corr.arp, corr.fdb, corr.olt_macs, corr.neighbors, corr.first_seen]
        ):
            return {"ok": False, "text": f"MAC {mac} not found in tenant {body.tenant}"}
        return {"ok": True, "text": _concise_mac(corr), "data": corr.to_dict()}
    finally:
        db.close()


@app.post("/tools/find_ip")
def find_ip(body: ToolRequest) -> dict[str, Any]:
    if not body.ip:
        raise HTTPException(400, "ip required")
    db = _db()
    try:
        qs = QueryService(db)
        try:
            data = qs.find_ip(body.tenant, body.ip)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        macs = [m.get("mac") for m in data.get("macs", [])]
        text = f"IP {body.ip} tenant={body.tenant} macs={', '.join(macs) or 'none'}"
        return {"ok": True, "text": text, "data": data}
    finally:
        db.close()


@app.post("/tools/get_device")
def get_device(body: ToolRequest) -> dict[str, Any]:
    if not body.device_id:
        raise HTTPException(400, "device_id required")
    db = _db()
    try:
        qs = QueryService(db)
        try:
            device = qs.get_device(body.tenant, body.device_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        if device is None:
            return {"ok": False, "text": "device not found"}
        text = f"{device.name} type={device.device_type} vendor={device.vendor} model={device.model}"
        return {
            "ok": True,
            "text": text,
            "data": {
                "id": str(device.id),
                "name": device.name,
                "device_type": device.device_type,
                "vendor": device.vendor,
                "model": device.model,
                "enabled": device.enabled,
            },
        }
    finally:
        db.close()


@app.post("/tools/list_devices")
def list_devices(body: ToolRequest) -> dict[str, Any]:
    db = _db()
    try:
        qs = QueryService(db)
        try:
            devices = qs.list_devices(body.tenant)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        lines = [f"{d.name} ({d.device_type})" for d in devices]
        return {
            "ok": True,
            "text": f"{len(devices)} devices\n" + "\n".join(lines),
            "data": [{"id": str(d.id), "name": d.name, "device_type": d.device_type} for d in devices],
        }
    finally:
        db.close()


@app.post("/tools/list_tenant_network_assets")
def list_tenant_network_assets(body: ToolRequest) -> dict[str, Any]:
    db = _db()
    try:
        qs = QueryService(db)
        try:
            devices = qs.list_devices(body.tenant)
            macs = qs.list_macs(body.tenant, limit=body.limit)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        text = (
            f"tenant={body.tenant} devices={len(devices)} tracked_macs={len(macs)} "
            f"(showing up to {body.limit})"
        )
        return {
            "ok": True,
            "text": text,
            "data": {
                "devices": len(devices),
                "macs": [m.mac for m in macs],
            },
        }
    finally:
        db.close()


@app.post("/tools/get_mac_history")
def get_mac_history(body: ToolRequest) -> dict[str, Any]:
    if not body.mac:
        raise HTTPException(400, "mac required")
    db = _db()
    try:
        qs = QueryService(db)
        try:
            data = qs.mac_history(body.tenant, body.mac)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        timeline = data.get("timeline") or []
        summary_lines = [
            f"MAC {data.get('mac')} tenant={data.get('tenant')} found={data.get('found')}",
            f"first_seen={data.get('first_seen')} last_seen={data.get('last_seen')}",
            f"current_ips={data.get('current_ips')}",
            f"current_locations={data.get('current_locations')}",
            f"conflicts={data.get('conflicts')}",
            f"timeline_events={len(timeline)}",
        ]
        for event in timeline[:20]:
            summary_lines.append(
                f"{event.get('at')} {event.get('kind')} device={event.get('device')} "
                f"iface={event.get('interface')} ip={event.get('ip')} source={event.get('source')}"
            )
        text = "\n".join(summary_lines)
        return {"ok": bool(data.get("found")), "text": text, "data": data}
    finally:
        db.close()


@app.post("/tools/get_collection_status")
def get_collection_status(body: ToolRequest) -> dict[str, Any]:
    db = _db()
    try:
        qs = QueryService(db)
        try:
            status = qs.collection_status(body.tenant, limit=body.limit)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        lines = [
            f"{r['collector_type']} {r['status']} completeness={r['completeness']} "
            f"seen={r['records_seen']} excluded={r.get('records_excluded', 0)}"
            for r in status.get("runs", [])
        ]
        return {
            "ok": True,
            "text": "\n".join(lines) or "no runs",
            "data": status,
        }
    finally:
        db.close()


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "mcp_server.server:app",
        host=settings.mcp_http_host,
        port=settings.mcp_http_port,
        log_level=settings.api_log_level,
    )


if __name__ == "__main__":
    main()
