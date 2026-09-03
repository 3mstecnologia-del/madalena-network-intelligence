"""Correlation + tenant isolation using in-memory SQLite."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.correlation.engine import CorrelationEngine
from app.services.ingest import IngestService
from collectors.common.types import CollectorResult, NormalizedDhcpLease
from collectors.intelbras_g08.collector import IntelbrasG08Collector
from collectors.mikrotik.collector import MikroTikCollector
from tests.conftest import FIX, seed_two_tenants


def test_correlation_mac_ip_onu(db: Session):
    t1, _, d1, _, d1o, _ = seed_two_tenants(db)
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
    assert corr.access_path.vlan_id == 30
    assert corr.access_path.profile == "CORPORATIVO"
    assert corr.fdb[0]["interface"] == "sfp-sfpplus2"


def test_tenant_isolation(db: Session):
    t1, t2, d1, _, _, d2 = seed_two_tenants(db)
    mk = MikroTikCollector("infisical", "EXAMPLE")
    result = mk.collect_from_texts(dhcp_text=(FIX / "mikrotik_dhcp.txt").read_text())
    ingest = IngestService(db)
    ingest.ingest_result(tenant_id=t1.id, device_id=d1.id, result=result)
    db.commit()

    corr_other = CorrelationEngine(db).correlate_mac("other-tenant", "AA:BB:CC:DD:EE:FF")
    assert corr_other is not None
    assert corr_other.dhcp == []
    assert corr_other.first_seen is None

    corr_ok = CorrelationEngine(db).correlate_mac("example-tenant", "AA:BB:CC:DD:EE:FF")
    assert corr_ok.dhcp


def test_temporal_ip_history(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
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
