"""OLT: ONU serial persistida + correlação de localização (MAC atrás de ONU)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Device, OltMacObservation
from app.services.ingest import IngestService
from app.services.query import QueryService
from collectors.common.types import CollectorResult, NormalizedOltMac
from tests.conftest import seed_two_tenants

MAC_ONU = "AA:BB:CC:20:00:01"
MAC_AP = "AA:BB:CC:20:00:02"
SERIAL = "TEST-ONU-SN-001"


def _ingest_olt_mac(db, tenant_id, device_id, mac, ont_id, serial, pon="0/1", vlan=100):
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=tenant_id,
        device_id=device_id,
        result=CollectorResult(
            olt_macs=[
                NormalizedOltMac(
                    mac=mac, ont_id=ont_id, pon=pon, vlan_id=vlan,
                    serial=serial, source="olt",
                )
            ]
        ),
    )
    db.commit()


def test_olt_mac_persists_onu_serial(db: Session):
    tenant, _, device, *_ = seed_two_tenants(db)
    _ingest_olt_mac(db, tenant.id, device.id, MAC_ONU, "0/1/3", SERIAL)
    row = db.scalar(
        select(OltMacObservation).where(
            OltMacObservation.tenant_id == tenant.id, OltMacObservation.mac == MAC_ONU
        )
    )
    assert row is not None
    assert row.serial == SERIAL
    assert row.ont_id == "0/1/3"
    assert row.pon == "0/1"
    assert row.vlan_id == 100


def test_olt_serial_preserved_on_update(db: Session):
    tenant, _, device, *_ = seed_two_tenants(db)
    _ingest_olt_mac(db, tenant.id, device.id, MAC_ONU, "0/1/3", SERIAL)
    # Re-observe the same MAC with serial missing -> serial must not be lost.
    _ingest_olt_mac(db, tenant.id, device.id, MAC_ONU, "0/1/3", None)
    row = db.scalar(
        select(OltMacObservation).where(OltMacObservation.mac == MAC_ONU)
    )
    assert row.serial == SERIAL


def test_olt_locations_resolve_known_mac_to_device_and_ont(db: Session):
    tenant, _, olt, *_ = seed_two_tenants(db)
    ap = Device(
        tenant_id=tenant.id, site_id=olt.site_id, name="AP-TEST-01",
        device_type="unifi_ap", chassis_mac=MAC_AP,
    )
    db.add(ap)
    db.commit()
    _ingest_olt_mac(db, tenant.id, olt.id, MAC_AP, "0/1/7", SERIAL, pon="0/1", vlan=200)
    _ingest_olt_mac(db, tenant.id, olt.id, "AA:BB:CC:20:00:99", "0/2/1", None, pon="0/2")

    out = QueryService(db).olt_locations("example-tenant")
    assert out["distinct_macs"] == 2
    assert out["resolved_macs"] == 1
    assert out["unresolved_macs"] == 1
    assert out["devices_localized"] == 1
    dev = out["devices"][0]
    assert dev["name"] == "AP-TEST-01"
    assert dev["device_type"] == "unifi_ap"
    assert dev["locations"][0]["ont_id"] == "0/1/7"
    assert dev["locations"][0]["pon"] == "0/1"
    assert dev["locations"][0]["serial"] == SERIAL
    assert "AA:BB:CC:20:00:02" in dev["locations"][0]["macs"]


def test_olt_locations_ambiguous_and_per_tenant_isolated(db: Session):
    tenant, other_tenant, olt, other, *_ = seed_two_tenants(db)
    shared = "AA:BB:CC:20:00:0A"
    db.add_all([
        Device(tenant_id=tenant.id, site_id=olt.site_id, name="AP-A", device_type="unifi_ap", chassis_mac=shared),
        Device(tenant_id=tenant.id, site_id=olt.site_id, name="AP-B", device_type="unifi_ap", chassis_mac=shared),
    ])
    db.commit()
    _ingest_olt_mac(db, tenant.id, olt.id, shared, "0/1/1", None)
    _ingest_olt_mac(db, other_tenant.id, other.id, shared, "0/9/9", None)

    out = QueryService(db).olt_locations("example-tenant")
    assert out["distinct_macs"] == 1
    assert out["resolved_macs"] == 0
    assert out["ambiguous_macs"] == 1
    # Per-tenant isolation: the other tenant's identical MAC does not appear.
    other_out = QueryService(db).olt_locations("other-tenant")
    assert other_out["macs"][0]["locations"][0]["ont_id"] == "0/9/9"
    assert out["macs"][0]["locations"][0]["ont_id"] == "0/1/1"


def test_olt_locations_mac_filter(db: Session):
    tenant, _, olt, *_ = seed_two_tenants(db)
    _ingest_olt_mac(db, tenant.id, olt.id, MAC_AP, "0/1/2", SERIAL)
    _ingest_olt_mac(db, tenant.id, olt.id, MAC_ONU, "0/1/3", None)
    out = QueryService(db).olt_locations("example-tenant", mac=MAC_AP)
    assert out["distinct_macs"] == 1
    assert out["macs"][0]["mac"] == MAC_AP