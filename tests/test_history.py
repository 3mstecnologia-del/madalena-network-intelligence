"""History, location moves, conflicts, partial runs, offline device, tenant isolation."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.correlation.engine import CorrelationEngine
from app.models.entities import ArpObservation, CollectionRun, DhcpLease, MacObservation, OltMacObservation
from app.services.ingest import IngestService
from collectors.common.types import (
    CollectorResult,
    NormalizedArp,
    NormalizedDhcpLease,
    NormalizedMacFdb,
    NormalizedOltMac,
)
from collectors.mikrotik.collector import MikroTikCollector
from tests.conftest import FIX, seed_two_tenants

MAC = "AA:BB:CC:DD:EE:FF"


def _ts(hour: int) -> datetime:
    return datetime(2026, 3, 1, hour, 0, 0, tzinfo=timezone.utc)


def test_mac_history_timeline(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            dhcp=[
                NormalizedDhcpLease(mac=MAC, ip_address="10.30.1.50", observed_at=_ts(1)),
            ],
            arp=[
                NormalizedArp(
                    mac=MAC, ip_address="10.30.1.50", interface="bridge-lan", observed_at=_ts(1)
                )
            ],
            fdb=[
                NormalizedMacFdb(mac=MAC, interface="ether3", observed_at=_ts(2)),
            ],
        ),
    )
    db.commit()
    corr = CorrelationEngine(db).correlate_mac("example-tenant", MAC)
    assert corr.first_seen is not None
    assert corr.last_seen is not None
    kinds = {e["kind"] for e in corr.timeline}
    assert {"dhcp_lease", "arp", "fdb"} <= kinds
    assert corr.timeline[0]["kind"] == "fdb"


def test_mac_moves_interface(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            fdb=[NormalizedMacFdb(mac=MAC, interface="ether3", observed_at=_ts(1))]
        ),
    )
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            fdb=[NormalizedMacFdb(mac=MAC, interface="ether7", observed_at=_ts(3))]
        ),
    )
    db.commit()
    rows = list(
        db.scalars(select(MacObservation).where(MacObservation.mac == MAC, MacObservation.tenant_id == t1.id))
    )
    assert len(rows) == 2
    corr = CorrelationEngine(db).correlate_mac("example-tenant", MAC)
    assert corr.current_locations[0]["interface"] == "ether7"
    assert any(loc["interface"] == "ether3" for loc in corr.historical_locations)


def test_mac_moves_device(db: Session):
    t1, _, d1, d1b, _, _ = seed_two_tenants(db)
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            fdb=[NormalizedMacFdb(mac=MAC, interface="ether1", observed_at=_ts(1))]
        ),
    )
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1b.id,
        result=CollectorResult(
            fdb=[NormalizedMacFdb(mac=MAC, interface="ether8", observed_at=_ts(4))]
        ),
    )
    db.commit()
    corr = CorrelationEngine(db).correlate_mac("example-tenant", MAC)
    assert corr.current_locations[0]["device"] == "LAB-MK-EDGE"
    assert any(loc["device"] == "LAB-MK" for loc in corr.historical_locations)


def test_mac_uses_different_ip(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            dhcp=[NormalizedDhcpLease(mac=MAC, ip_address="10.30.1.50", observed_at=_ts(1))]
        ),
    )
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            dhcp=[NormalizedDhcpLease(mac=MAC, ip_address="10.30.1.99", observed_at=_ts(5))]
        ),
    )
    db.commit()
    assert (
        len(list(db.scalars(select(DhcpLease).where(DhcpLease.mac == MAC, DhcpLease.tenant_id == t1.id))))
        == 2
    )
    corr = CorrelationEngine(db).correlate_mac("example-tenant", MAC)
    assert corr.current_ips[0]["ip"] == "10.30.1.99"
    assert any(h["ip"] == "10.30.1.50" for h in corr.historical_ips)


def test_multiple_sources_same_mac(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    mk = MikroTikCollector("infisical", "EXAMPLE")
    result = mk.collect_from_texts(
        dhcp_text=(FIX / "mikrotik_dhcp.txt").read_text(),
        arp_text=(FIX / "mikrotik_arp.txt").read_text(),
        fdb_text=(FIX / "mikrotik_fdb.txt").read_text(),
        neighbors_text=(FIX / "mikrotik_neighbors.txt").read_text(),
    )
    IngestService(db).ingest_result(tenant_id=t1.id, device_id=d1.id, result=result)
    db.commit()
    corr = CorrelationEngine(db).correlate_mac("example-tenant", MAC)
    assert "mikrotik_dhcp" in corr.sources
    assert "mikrotik_arp" in corr.sources
    assert "bridge_fdb" in corr.sources
    assert corr.dhcp and corr.arp and corr.fdb


def test_conflicting_evidence(db: Session):
    t1, _, d1, d1b, _, _ = seed_two_tenants(db)
    same = _ts(8)
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            dhcp=[NormalizedDhcpLease(mac=MAC, ip_address="10.30.1.50", observed_at=same)],
            fdb=[NormalizedMacFdb(mac=MAC, interface="ether1", observed_at=same)],
        ),
    )
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1b.id,
        result=CollectorResult(
            dhcp=[NormalizedDhcpLease(mac=MAC, ip_address="10.30.1.77", observed_at=same)],
            fdb=[NormalizedMacFdb(mac=MAC, interface="ether9", observed_at=same)],
        ),
    )
    db.commit()
    corr = CorrelationEngine(db).correlate_mac("example-tenant", MAC)
    kinds = {c["kind"] for c in corr.conflicts}
    assert "ambiguous_ip" in kinds
    assert "ambiguous_device" in kinds
    assert "ambiguous_location" in kinds
    assert len(corr.current_ips) == 2


def test_partial_collection_run(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    ingest = IngestService(db)
    run = ingest.start_run(
        tenant_id=t1.id,
        collector_type="mikrotik_light",
        device_id=d1.id,
        collector_version="0.2.0",
    )
    result = CollectorResult(
        arp=[NormalizedArp(mac=MAC, ip_address="10.30.1.50", interface="bridge-lan")],
        meta={"completeness": "partial", "commands_ok": 1, "commands_failed": 2},
    )
    stats = ingest.ingest_result(tenant_id=t1.id, device_id=d1.id, result=result, run=run)
    ingest.finish_run(
        run,
        status="partial",
        completeness="partial",
        seen=stats["seen"],
        created=stats["created"],
        commands_ok=1,
        commands_failed=2,
        error="bridge host print timeout",
        collector_version="0.2.0",
    )
    db.commit()
    stored = db.get(CollectionRun, run.id)
    assert stored.status == "partial"
    assert stored.completeness == "partial"
    assert stored.commands_ok == 1
    assert stored.commands_failed == 2
    assert stored.records_seen == 1
    assert len(list(db.scalars(select(ArpObservation).where(ArpObservation.tenant_id == t1.id)))) == 1


def test_device_offline_keeps_history(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            dhcp=[
                NormalizedDhcpLease(
                    mac=MAC, ip_address="10.30.1.50", observed_at=_ts(1), hostname="notebook-exemplo"
                )
            ]
        ),
    )
    db.commit()
    before = len(list(db.scalars(select(DhcpLease).where(DhcpLease.tenant_id == t1.id))))
    run = ingest.start_run(tenant_id=t1.id, collector_type="mikrotik_light", device_id=d1.id)
    ingest.finish_run(
        run,
        status="error",
        completeness="none",
        error="ssh transport failed",
    )
    db.commit()
    assert len(list(db.scalars(select(DhcpLease).where(DhcpLease.tenant_id == t1.id)))) == before
    corr = CorrelationEngine(db).correlate_mac("example-tenant", MAC)
    assert corr.dhcp
    assert corr.hostname == "notebook-exemplo"


def test_tenant_a_cannot_see_tenant_b(db: Session):
    t1, t2, d1, _, _, d2 = seed_two_tenants(db)
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            dhcp=[NormalizedDhcpLease(mac=MAC, ip_address="10.30.1.50", observed_at=_ts(1))]
        ),
    )
    ingest.ingest_result(
        tenant_id=t2.id,
        device_id=d2.id,
        result=CollectorResult(
            dhcp=[
                NormalizedDhcpLease(
                    mac="11:22:33:44:55:66", ip_address="10.40.1.8", observed_at=_ts(1)
                )
            ]
        ),
    )
    db.commit()
    corr_b = CorrelationEngine(db).correlate_mac("other-tenant", MAC)
    assert corr_b.dhcp == []
    assert corr_b.first_seen is None
    corr_a = CorrelationEngine(db).correlate_mac("example-tenant", "11:22:33:44:55:66")
    assert corr_a.dhcp == []


def test_arp_interface_change_keeps_prior_row(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            arp=[
                NormalizedArp(
                    mac=MAC, ip_address="10.30.1.50", interface="vlan30", observed_at=_ts(1)
                )
            ]
        ),
    )
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            arp=[
                NormalizedArp(
                    mac=MAC, ip_address="10.30.1.50", interface="vlan40", observed_at=_ts(2)
                )
            ]
        ),
    )
    db.commit()
    rows = list(
        db.scalars(select(ArpObservation).where(ArpObservation.mac == MAC, ArpObservation.tenant_id == t1.id))
    )
    assert {r.interface for r in rows} == {"vlan30", "vlan40"}


def test_olt_mac_move_keeps_prior_onu(db: Session):
    t1, _, _, _, d1o, _ = seed_two_tenants(db)
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1o.id,
        result=CollectorResult(
            olt_macs=[
                NormalizedOltMac(
                    mac=MAC, ont_id="0/1/14", pon="0/1", source="olt", observed_at=_ts(1)
                )
            ]
        ),
    )
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1o.id,
        result=CollectorResult(
            olt_macs=[
                NormalizedOltMac(
                    mac=MAC, ont_id="0/1/15", pon="0/1", source="olt", observed_at=_ts(3)
                )
            ]
        ),
    )
    db.commit()
    rows = list(
        db.scalars(
            select(OltMacObservation).where(
                OltMacObservation.mac == MAC, OltMacObservation.tenant_id == t1.id
            )
        )
    )
    assert {r.ont_id for r in rows} == {"0/1/14", "0/1/15"}
    corr = CorrelationEngine(db).correlate_mac("example-tenant", MAC)
    assert corr.access_path is not None
    assert corr.access_path.onu == "0/1/15"
    assert {row["ont_id"] for row in corr.olt_macs} == {"0/1/14", "0/1/15"}


def test_olt_mac_same_timestamp_two_onus_is_conflict(db: Session):
    t1, _, _, _, d1o, _ = seed_two_tenants(db)
    same = _ts(4)
    IngestService(db).ingest_result(
        tenant_id=t1.id,
        device_id=d1o.id,
        result=CollectorResult(
            olt_macs=[
                NormalizedOltMac(mac=MAC, ont_id="0/1/14", pon="0/1", source="olt", observed_at=same),
                NormalizedOltMac(mac=MAC, ont_id="0/1/15", pon="0/1", source="olt", observed_at=same),
            ]
        ),
    )
    db.commit()
    corr = CorrelationEngine(db).correlate_mac("example-tenant", MAC)
    kinds = {c["kind"] for c in corr.conflicts}
    assert "ambiguous_onu" in kinds


def test_ingest_same_mac_two_onus_one_run(db: Session):
    t1, _, _, _, d1o, _ = seed_two_tenants(db)
    IngestService(db).ingest_result(
        tenant_id=t1.id,
        device_id=d1o.id,
        result=CollectorResult(
            olt_macs=[
                NormalizedOltMac(mac=MAC, ont_id="0/1/14", pon="0/1", source="olt", observed_at=_ts(1)),
                NormalizedOltMac(mac=MAC, ont_id="0/1/15", pon="0/1", source="olt", observed_at=_ts(1)),
            ]
        ),
    )
    db.commit()
    rows = list(
        db.scalars(
            select(OltMacObservation).where(
                OltMacObservation.mac == MAC, OltMacObservation.tenant_id == t1.id
            )
        )
    )
    assert {r.ont_id for r in rows} == {"0/1/14", "0/1/15"}


def test_multiple_macs_behind_same_onu(db: Session):
    t1, _, _, _, d1o, _ = seed_two_tenants(db)
    mac_b = "11:22:33:44:55:66"
    IngestService(db).ingest_result(
        tenant_id=t1.id,
        device_id=d1o.id,
        result=CollectorResult(
            olt_macs=[
                NormalizedOltMac(mac=MAC, ont_id="0/1/14", pon="0/1", vlan_id=30, source="olt"),
                NormalizedOltMac(mac=mac_b, ont_id="0/1/14", pon="0/1", vlan_id=30, source="olt"),
            ]
        ),
    )
    db.commit()
    rows = list(
        db.scalars(
            select(OltMacObservation).where(
                OltMacObservation.ont_id == "0/1/14", OltMacObservation.tenant_id == t1.id
            )
        )
    )
    assert {r.mac for r in rows} == {MAC, mac_b}


def test_repeated_dhcp_collection_updates_last_seen(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            dhcp=[NormalizedDhcpLease(mac=MAC, ip_address="10.30.1.50", observed_at=_ts(1))]
        ),
    )
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            dhcp=[NormalizedDhcpLease(mac=MAC, ip_address="10.30.1.50", observed_at=_ts(2))]
        ),
    )
    db.commit()
    rows = list(db.scalars(select(DhcpLease).where(DhcpLease.mac == MAC, DhcpLease.tenant_id == t1.id)))
    assert len(rows) == 1
    assert rows[0].last_seen.replace(tzinfo=None) == _ts(2).replace(tzinfo=None)
    assert rows[0].first_seen.replace(tzinfo=None) == _ts(1).replace(tzinfo=None)


def test_finish_run_sanitizes_error_before_persist(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    ingest = IngestService(db)
    run = ingest.start_run(tenant_id=t1.id, collector_type="mikrotik_dhcp", device_id=d1.id)
    ingest.finish_run(
        run,
        status="error",
        error="password=super-secret host=192.0.2.8 user='labuser'",
        completeness="none",
    )
    db.commit()
    stored = db.get(type(run), run.id)
    assert stored.error_summary is not None
    assert "super-secret" not in stored.error_summary
    assert "192.0.2.8" not in stored.error_summary
    assert "labuser" not in stored.error_summary
