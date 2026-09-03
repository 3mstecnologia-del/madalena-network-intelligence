"""API find MAC/IP, tenant isolation, pagination, no credential leakage."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.main import app
from app.core.db import get_db
from app.services.ingest import IngestService
from collectors.common.types import CollectorResult, NormalizedDhcpLease
from tests.conftest import seed_two_tenants

MAC = "AA:BB:CC:DD:EE:FF"


def _client(db: Session) -> TestClient:
    def override():
        yield db

    app.dependency_overrides[get_db] = override
    return TestClient(app)


def test_api_find_mac(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    IngestService(db).ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            dhcp=[NormalizedDhcpLease(mac=MAC, ip_address="10.30.1.50", hostname="notebook-exemplo")]
        ),
    )
    db.commit()
    client = _client(db)
    try:
        res = client.get("/macs/aa-bb-cc-dd-ee-ff", params={"tenant": "example-tenant"})
        assert res.status_code == 200
        body = res.json()
        assert body["mac"] == MAC
        assert body["current_ips"][0]["ip"] == "10.30.1.50"
        assert "password" not in res.text.lower()
        assert "secret_prefix" not in res.text
    finally:
        app.dependency_overrides.clear()


def test_api_find_ip(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    IngestService(db).ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(dhcp=[NormalizedDhcpLease(mac=MAC, ip_address="10.30.1.50")]),
    )
    db.commit()
    client = _client(db)
    try:
        res = client.get("/ips/10.30.1.50", params={"tenant": "example-tenant"})
        assert res.status_code == 200
        body = res.json()
        assert body["ip"] == "10.30.1.50"
        assert body["macs"][0]["mac"] == MAC
    finally:
        app.dependency_overrides.clear()


def test_api_tenant_isolation(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    IngestService(db).ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(dhcp=[NormalizedDhcpLease(mac=MAC, ip_address="10.30.1.50")]),
    )
    db.commit()
    client = _client(db)
    try:
        missing = client.get("/macs/" + MAC, params={"tenant": "other-tenant"})
        assert missing.status_code == 404
        devices_b = client.get("/devices", params={"tenant": "other-tenant"})
        assert devices_b.status_code == 200
        names = {d["name"] for d in devices_b.json()}
        assert "LAB-MK" not in names
        assert "OTHER-MK" in names
    finally:
        app.dependency_overrides.clear()


def test_api_health_and_pagination(db: Session):
    seed_two_tenants(db)
    client = _client(db)
    try:
        assert client.get("/health").json()["status"] == "ok"
        page = client.get("/devices", params={"tenant": "example-tenant", "limit": 1, "offset": 0})
        assert page.status_code == 200
        assert len(page.json()) == 1
        page2 = client.get("/devices", params={"tenant": "example-tenant", "limit": 1, "offset": 1})
        assert page2.json()[0]["id"] != page.json()[0]["id"]
    finally:
        app.dependency_overrides.clear()


def test_api_device_omits_secret_refs(db: Session):
    _, _, d1, _, _, _ = seed_two_tenants(db)
    client = _client(db)
    try:
        res = client.get(f"/devices/{d1.id}", params={"tenant": "example-tenant"})
        assert res.status_code == 200
        body = res.json()
        assert "management_host_ref" not in body
        assert "secret_prefix" not in body
        assert "password" not in body
    finally:
        app.dependency_overrides.clear()
