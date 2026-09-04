"""Exclusion policy drops observations before persistence."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import DhcpLease, ExclusionPolicy, MacObservation, OltMacObservation
from app.services.ingest import IngestService
from collectors.common.types import (
    CollectorResult,
    NormalizedArp,
    NormalizedDhcpLease,
    NormalizedMacFdb,
    NormalizedOltMac,
)
from tests.conftest import seed_two_tenants

MAC = "AA:BB:CC:DD:EE:FF"
OTHER = "11:22:33:44:55:66"


def test_vlan_exclusion_not_persisted(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    db.add(ExclusionPolicy(tenant_id=t1.id, rule_type="vlan", rule_value="100", enabled=True))
    db.commit()
    stats = IngestService(db).ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            fdb=[
                NormalizedMacFdb(mac=MAC, interface="ether3", vlan_id=100),
                NormalizedMacFdb(mac=OTHER, interface="ether3", vlan_id=30),
            ]
        ),
    )
    db.commit()
    rows = list(db.scalars(select(MacObservation).where(MacObservation.tenant_id == t1.id)))
    assert stats["excluded"] == 1
    assert len(rows) == 1
    assert rows[0].mac == OTHER
    assert rows[0].vlan_id == 30


def test_cidr_exclusion_not_persisted(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    db.add(ExclusionPolicy(tenant_id=t1.id, rule_type="cidr", rule_value="10.99.0.0/16", enabled=True))
    db.commit()
    IngestService(db).ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            dhcp=[
                NormalizedDhcpLease(mac=MAC, ip_address="10.99.1.10"),
                NormalizedDhcpLease(mac=OTHER, ip_address="10.30.1.50"),
            ]
        ),
    )
    db.commit()
    ips = {r.ip_address for r in db.scalars(select(DhcpLease).where(DhcpLease.tenant_id == t1.id))}
    assert ips == {"10.30.1.50"}


def test_collector_disabled_skips_dhcp(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    d1.collectors_enabled = '["arp","fdb"]'
    db.add(d1)
    db.commit()
    IngestService(db).ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            dhcp=[NormalizedDhcpLease(mac=MAC, ip_address="10.30.1.50")],
            arp=[NormalizedArp(mac=MAC, ip_address="10.30.1.50", interface="bridge")],
        ),
    )
    db.commit()
    assert db.scalar(select(DhcpLease).where(DhcpLease.tenant_id == t1.id)) is None
    from app.models.entities import ArpObservation

    assert db.scalar(select(ArpObservation).where(ArpObservation.tenant_id == t1.id)) is not None


def test_olt_vlan_exclusion(db: Session):
    t1, _, _, _, d_olt, _ = seed_two_tenants(db)
    db.add(ExclusionPolicy(tenant_id=t1.id, rule_type="vlan", rule_value="40", enabled=True))
    db.commit()
    IngestService(db).ingest_result(
        tenant_id=t1.id,
        device_id=d_olt.id,
        result=CollectorResult(
            olt_macs=[
                NormalizedOltMac(mac=MAC, ont_id="0/1/14", pon="0/1", vlan_id=40),
                NormalizedOltMac(mac=OTHER, ont_id="0/1/15", pon="0/1", vlan_id=30),
            ]
        ),
    )
    db.commit()
    macs = {r.mac for r in db.scalars(select(OltMacObservation).where(OltMacObservation.tenant_id == t1.id))}
    assert macs == {OTHER}


def test_exclusion_does_not_cross_tenant(db: Session):
    t1, t2, d1, _, _, d2 = seed_two_tenants(db)
    db.add(ExclusionPolicy(tenant_id=t1.id, rule_type="vlan", rule_value="100", enabled=True))
    db.commit()
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t2.id,
        device_id=d2.id,
        result=CollectorResult(fdb=[NormalizedMacFdb(mac=MAC, interface="ether1", vlan_id=100)]),
    )
    db.commit()
    assert db.scalar(select(MacObservation).where(MacObservation.tenant_id == t2.id)) is not None
