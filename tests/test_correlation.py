"""Correlation + tenant isolation using in-memory SQLite."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base
from app.correlation.engine import CorrelationEngine
from app.models import entities  # noqa: F401
from app.models.entities import Device, Site, Tenant
from app.services.ingest import IngestService
from collectors.intelbras_g08.collector import IntelbrasG08Collector
from collectors.mikrotik.collector import MikroTikCollector
from pathlib import Path

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def _seed_two_tenants(db: Session):
    t1 = Tenant(id=uuid.uuid4(), slug="example-tenant", name="Example")
    t2 = Tenant(id=uuid.uuid4(), slug="other-tenant", name="Other")
    db.add_all([t1, t2])
    s1 = Site(id=uuid.uuid4(), tenant_id=t1.id, slug="site-a", name="Site A")
    s2 = Site(id=uuid.uuid4(), tenant_id=t2.id, slug="site-b", name="Site B")
    db.add_all([s1, s2])
    d1 = Device(
        id=uuid.uuid4(),
        tenant_id=t1.id,
        site_id=s1.id,
        name="LAB-MK",
        device_type="mikrotik",
        vendor="MikroTik",
    )
    d1o = Device(
        id=uuid.uuid4(),
        tenant_id=t1.id,
        site_id=s1.id,
        name="LAB-G08",
        device_type="intelbras_g08",
        vendor="Intelbras",
    )
    d2 = Device(
        id=uuid.uuid4(),
        tenant_id=t2.id,
        site_id=s2.id,
        name="OTHER-MK",
        device_type="mikrotik",
    )
    db.add_all([d1, d1o, d2])
    db.commit()
    return t1, t2, d1, d1o, d2


def test_correlation_mac_ip_onu(db: Session):
    t1, _, d1, d1o, _ = _seed_two_tenants(db)
    mk = MikroTikCollector("infisical", "EXAMPLE")
    result = mk.collect_from_texts(
        dhcp_text=(FIX / "mikrotik_dhcp.txt").read_text(),
        arp_text=(FIX / "mikrotik_arp.txt").read_text(),
        fdb_text=(FIX / "mikrotik_fdb.txt").read_text(),
    )
    ingest = IngestService(db)
    ingest.ingest_result(tenant_id=t1.id, device_id=d1.id, result=result)

    g08 = IntelbrasG08Collector("infisical", "EXAMPLE")
    olt = g08.collect_from_texts(
        ont_brief_text=(FIX / "g08_ont_brief.txt").read_text(),
        mac_table_text=(FIX / "g08_mac_table.txt").read_text(),
    )
    ingest.ingest_result(tenant_id=t1.id, device_id=d1o.id, result=olt)
    db.commit()

    corr = CorrelationEngine(db).correlate_mac("example-tenant", "aa-bb-cc-dd-ee-ff")
    assert corr is not None
    assert corr.mac == "AA:BB:CC:DD:EE:FF"
    assert corr.hostname == "notebook-exemplo"
    assert any(i["ip"] == "10.30.1.50" for i in corr.current_ips)
    assert corr.access_path is not None
    assert corr.access_path.onu == "0/1/14"
    assert corr.access_path.pon == "0/1"
    assert corr.access_path.profile == "CORPORATIVO"
    assert corr.fdb[0]["interface"] == "sfp-sfpplus2"


def test_tenant_isolation(db: Session):
    t1, t2, d1, _, d2 = _seed_two_tenants(db)
    mk = MikroTikCollector("infisical", "EXAMPLE")
    result = mk.collect_from_texts(dhcp_text=(FIX / "mikrotik_dhcp.txt").read_text())
    ingest = IngestService(db)
    ingest.ingest_result(tenant_id=t1.id, device_id=d1.id, result=result)
    db.commit()

    # Same MAC must not appear under other tenant
    corr_other = CorrelationEngine(db).correlate_mac("other-tenant", "AA:BB:CC:DD:EE:FF")
    assert corr_other is not None
    assert corr_other.dhcp == []
    assert corr_other.first_seen is None

    corr_ok = CorrelationEngine(db).correlate_mac("example-tenant", "AA:BB:CC:DD:EE:FF")
    assert corr_ok.dhcp


def test_temporal_ip_history(db: Session):
    from collectors.common.types import NormalizedDhcpLease
    from collectors.common.types import CollectorResult
    from datetime import datetime, timezone, timedelta

    t1, _, d1, _, _ = _seed_two_tenants(db)
    ingest = IngestService(db)
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t1_time = t0 + timedelta(hours=2)
    r1 = CollectorResult(
        dhcp=[
            NormalizedDhcpLease(
                mac="AA:BB:CC:DD:EE:FF",
                ip_address="10.30.1.50",
                hostname="notebook-exemplo",
                observed_at=t0,
            )
        ]
    )
    r2 = CollectorResult(
        dhcp=[
            NormalizedDhcpLease(
                mac="AA:BB:CC:DD:EE:FF",
                ip_address="10.30.1.99",
                hostname="notebook-exemplo",
                observed_at=t1_time,
            )
        ]
    )
    ingest.ingest_result(tenant_id=t1.id, device_id=d1.id, result=r1)
    ingest.ingest_result(tenant_id=t1.id, device_id=d1.id, result=r2)
    db.commit()
    corr = CorrelationEngine(db).correlate_mac("example-tenant", "AA:BB:CC:DD:EE:FF")
    assert corr.current_ips[0]["ip"] == "10.30.1.99"
    assert any(h["ip"] == "10.30.1.50" for h in corr.historical_ips)
