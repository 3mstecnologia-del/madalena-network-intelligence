"""MCP tools: find_mac, get_mac_history, get_collection_status, tenant required."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services.ingest import IngestService
from collectors.common.types import CollectorResult, NormalizedDhcpLease, NormalizedMacFdb
from mcp_server.server import app as mcp_app
from tests.conftest import seed_two_tenants

MAC = "AA:BB:CC:DD:EE:FF"


class _SessionProxy:
    def __init__(self, inner: Session):
        self._inner = inner

    def close(self) -> None:
        return None

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _client(db: Session, monkeypatch) -> TestClient:
    monkeypatch.setattr("mcp_server.server.SessionLocal", lambda: _SessionProxy(db))
    return TestClient(mcp_app)


def test_mcp_find_mac(db: Session, monkeypatch):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    IngestService(db).ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            dhcp=[NormalizedDhcpLease(mac=MAC, ip_address="10.30.1.50", hostname="notebook-exemplo")]
        ),
    )
    db.commit()
    client = _client(db, monkeypatch)
    res = client.post("/tools/find_mac", json={"tenant": "example-tenant", "mac": MAC})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert MAC in body["text"]
    assert body["data"]["mac"] == MAC


def test_mcp_find_mac_requires_tenant(db: Session, monkeypatch):
    client = _client(db, monkeypatch)
    res = client.post("/tools/find_mac", json={"mac": MAC})
    assert res.status_code == 422


def test_mcp_find_ip(db: Session, monkeypatch):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    IngestService(db).ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            dhcp=[NormalizedDhcpLease(mac=MAC, ip_address="10.30.1.50", hostname="notebook-exemplo")]
        ),
    )
    db.commit()
    client = _client(db, monkeypatch)
    res = client.post("/tools/find_ip", json={"tenant": "example-tenant", "ip": "10.30.1.50"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert MAC in (body.get("text") or "")
    macs = [m.get("mac") for m in (body.get("data") or {}).get("macs", [])]
    assert MAC in macs


def test_mcp_get_mac_history(db: Session, monkeypatch):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    from datetime import datetime, timezone

    t0 = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
    t1s = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            dhcp=[NormalizedDhcpLease(mac=MAC, ip_address="10.30.1.50", observed_at=t0)],
            fdb=[NormalizedMacFdb(mac=MAC, interface="ether3", observed_at=t0)],
        ),
    )
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            dhcp=[NormalizedDhcpLease(mac=MAC, ip_address="10.30.1.99", observed_at=t1s)],
            fdb=[NormalizedMacFdb(mac=MAC, interface="ether7", observed_at=t1s)],
        ),
    )
    db.commit()
    client = _client(db, monkeypatch)
    res = client.post("/tools/get_mac_history", json={"tenant": "example-tenant", "mac": MAC})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["found"] is True
    assert data["timeline"]
    assert data["current_ips"][0]["ip"] == "10.30.1.99"
    assert "timeline_events=" in body["text"]
    assert any(e["kind"] == "fdb" for e in data["timeline"])


def test_mcp_get_collection_status(db: Session, monkeypatch):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    ingest = IngestService(db)
    run = ingest.start_run(
        tenant_id=t1.id,
        collector_type="mikrotik_light",
        device_id=d1.id,
        collector_version="0.2.0",
    )
    ingest.finish_run(
        run,
        status="partial",
        completeness="partial",
        seen=3,
        commands_ok=2,
        commands_failed=1,
        error="one command timed out",
        collector_version="0.2.0",
    )
    db.commit()
    client = _client(db, monkeypatch)
    res = client.post("/tools/get_collection_status", json={"tenant": "example-tenant"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    runs = body["data"]["runs"]
    assert runs[0]["status"] == "partial"
    assert runs[0]["completeness"] == "partial"
    assert "freshness_seconds" in runs[0]
    assert "completeness=partial" in body["text"]


def test_mcp_collection_status_isolates_tenant(db: Session, monkeypatch):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    ingest = IngestService(db)
    run = ingest.start_run(tenant_id=t1.id, collector_type="mikrotik_light", device_id=d1.id)
    ingest.finish_run(run, status="success", completeness="complete", seen=1)
    db.commit()
    client = _client(db, monkeypatch)
    res = client.post("/tools/get_collection_status", json={"tenant": "other-tenant"})
    assert res.status_code == 200
    assert res.json()["data"]["runs"] == []
