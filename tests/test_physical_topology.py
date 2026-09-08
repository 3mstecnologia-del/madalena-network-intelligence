"""Topologia física canônica com evidência sintética e isolamento por tenant."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.main import app
from app.core.db import get_db
from app.models.entities import (
    Device,
    DeviceIdentifier,
    Interface,
    InterfaceObservation,
    LinkEvidence,
    PhysicalLink,
)
from app.services.ingest import IngestService
from collectors.common.types import (
    CollectorResult,
    NormalizedInterface,
    NormalizedInventoryNode,
    NormalizedTopologyLink,
)
from collectors.mikrotik.collector import MikroTikCollector
from collectors.mikrotik.parsers import parse_interfaces, parse_neighbors
from collectors.unifi.collector import UnifiNetworkCollector
from tests.conftest import seed_two_tenants

MAC_MK = "AA:BB:CC:10:00:01"
MAC_SW = "AA:BB:CC:10:00:02"
SW_ID = "TEST-SW-001"


def _ts(hour: int) -> datetime:
    return datetime(2026, 9, 6, hour, tzinfo=timezone.utc)


def _client(db: Session) -> TestClient:
    def override():
        yield db

    app.dependency_overrides[get_db] = override
    return TestClient(app)


def test_interface_observation_preserves_temporal_evidence(db: Session):
    tenant, _, device, *_ = seed_two_tenants(db)
    ingest = IngestService(db)
    first = NormalizedInterface(
        name="ether1",
        description="TEST uplink",
        mac=MAC_MK,
        identifiers={"ifindex": "1"},
        source="mikrotik_interface",
        observed_at=_ts(1),
        evidence={"comment": "TEST uplink"},
    )
    second = NormalizedInterface(
        name="ether1",
        description="TEST uplink novo",
        mac=MAC_MK,
        identifiers={"ifindex": "1"},
        source="mikrotik_interface",
        observed_at=_ts(2),
        evidence={"comment": "TEST uplink novo"},
    )
    ingest.ingest_result(tenant_id=tenant.id, device_id=device.id, result=CollectorResult(interfaces=[first]))
    ingest.ingest_result(tenant_id=tenant.id, device_id=device.id, result=CollectorResult(interfaces=[second]))
    db.commit()

    interface = db.scalar(select(Interface).where(Interface.device_id == device.id, Interface.name == "ether1"))
    assert interface is not None
    assert interface.description == "TEST uplink novo"
    assert interface.source == "mikrotik_interface"
    assert interface.source_identifiers == {"ifindex": "1"}
    history = list(db.scalars(select(InterfaceObservation).where(InterfaceObservation.interface_id == interface.id)))
    assert len(history) == 2
    assert {row.evidence["comment"] for row in history} == {"TEST uplink", "TEST uplink novo"}


def test_mikrotik_description_chassis_protocol_and_topology_collection():
    interfaces = parse_interfaces(
        '0 name=ether1 type=ether comment="TEST-uplink" default-name=ether1 mac-address=AA:BB:CC:10:00:01\n'
    )
    neighbors = parse_neighbors(
        "0 interface=ether1 interface-name=port-24 identity=TEST-SW "
        "chassis-id=AA:BB:CC:10:00:02 discoverer=lldp\n"
    )
    assert interfaces[0].description == "TEST-uplink"
    assert interfaces[0].identifiers["default_name"] == "ether1"
    assert neighbors[0].chassis_id == MAC_SW
    assert neighbors[0].protocol == "lldp"
    result = MikroTikCollector("env", "TEST").collect_from_texts(
        identity_text="name: TEST-MK",
        interfaces_text='0 name=ether1 type=ether comment="TEST-uplink" mac-address=AA:BB:CC:10:00:01',
        neighbors_text=(
            "0 interface=ether1 interface-name=port-24 identity=TEST-SW "
            "chassis-id=AA:BB:CC:10:00:02 discoverer=lldp"
        ),
    )
    assert result.identity is not None
    assert result.interfaces and result.neighbors and result.topology_links
    assert result.topology_links[0].remote_chassis_id == MAC_SW


def test_mikrotik_neighbor_detail_multi_protocol_and_no_chassis():
    """Reproduce the real `RouterOS 7 /ip neighbor print detail` layout: fields
    span multiple lines, no discovery at all is rare, and the realistic
    MikroTik↔MikroTik discovery is `discovered-by=cdp,mndp` (no LLDP, hence no
    `chassis-id`). The protocol must normalize to cdp and a missing chassis-id
    must not fail the parse."""
    text = (
        " 0 interface=SFP2_REDE_200 mac-address=AA:BB:CC:10:00:02 "
        'identity="TEST-ROUTER" platform="MikroTik" version="7.16.1 '
        '(stable) 2024-10-10 14:03:32" unpack=none age=23s uptime=21w '
        'software-id="Q1TB-SEYJ" board="CCR1016-12G" ipv6=yes '
        'interface-name="ether2" discovered-by=cdp,mndp\n'
        " 1 interface=ether1 mac-address=AA:BB:CC:10:00:03 "
        'identity="TEST-SW" board="CRS328-24P-4S+" discovered-by=mndp\n'
    )
    neighbors = parse_neighbors(text)
    assert len(neighbors) == 2
    assert neighbors[0].protocol == "cdp"
    assert neighbors[0].identity == "TEST-ROUTER"
    assert neighbors[0].platform == "MikroTik"
    assert neighbors[0].version.startswith("7.16.1")
    assert neighbors[0].remote_interface == "ether2"
    assert neighbors[0].chassis_id is None
    assert neighbors[1].protocol == "mndp"
    assert neighbors[1].chassis_id is None


def test_unifi_serial_ports_uplink_variants_and_categories():
    switch = {
        "id": SW_ID,
        "name": "TEST-SW",
        "type": "switch",
        "serialNumber": "TEST-SERIAL-001",
        "macAddress": MAC_SW,
        "interfaces": {
            "ports": [
                {
                    "idx": 24,
                    "name": "TEST-Port-24",
                    "connector": "rj45",
                    "state": "up",
                    "macAddress": MAC_SW,
                    "description": "TEST uplink",
                }
            ]
        },
    }
    ap = {
        "id": "TEST-AP-001",
        "name": "TEST-AP",
        "type": "ap",
        "serial": "TEST-SERIAL-002",
        "uplinkDeviceId": SW_ID,
        "uplinkPortIdx": 24,
    }
    result = UnifiNetworkCollector("env", "TEST").collect_from_payloads(
        devices_payload=[switch, ap], detail_payloads=[switch, ap]
    )
    by_id = {node.source_id: node for node in result.inventory_nodes}
    assert by_id[SW_ID].serial == "TEST-SERIAL-001"
    assert by_id[SW_ID].category == "unifi_switch"
    assert by_id["TEST-AP-001"].category == "unifi_ap"
    port = next(row for row in result.interfaces if row.owner_source_id == SW_ID)
    assert port.name == "TEST-Port-24"
    assert port.description == "TEST uplink"
    assert port.identifiers["port_idx"] == "24"
    uplink = next(link for link in result.topology_links if link.local_source_id == "TEST-AP-001")
    assert uplink.remote_source_id == SW_ID
    assert uplink.remote_interface == "port-24"


def test_unifi_live_payload_feature_list_and_empty_dict_categories():
    """Reproduce the real Integration v1 payloads: the list endpoint returns
    `features` as a string list and the detail endpoint as a dict whose flag keys
    may hold an empty dict (e.g. {"accessPoint": {}}). Categories and uplinks
    must still resolve even when `type` and `serialNumber` are absent (newer
    controller builds stop exposing them in the list payload)."""
    # List payload: features is a list, no type/serialNumber.
    switch_list = {
        "id": SW_ID,
        "name": "TEST-SW",
        "macAddress": MAC_SW,
        "model": "US 8 PoE 150W",
        "features": ["switching"],
    }
    ap_list = {
        "id": "TEST-AP-001",
        "name": "TEST-AP",
        "macAddress": "AA:BB:CC:10:00:03",
        "model": "U6-LR",
        "features": ["accessPoint"],
    }
    # Detail payload: features is a dict with empty flag dicts; uplink present.
    switch_detail = {
        **switch_list,
        "type": "switch",
        "features": {"switching": {}},
        "uplink": {"deviceId": "TEST-AP-001"},
        "interfaces": {
            "ports": [
                {
                    "idx": 24,
                    "name": "TEST-Port-24",
                    "connector": "rj45",
                    "state": "up",
                    "macAddress": MAC_SW,
                }
            ]
        },
    }
    ap_detail = {
        **ap_list,
        "type": "ap",
        "features": {"accessPoint": {}},
        "uplink": {"deviceId": SW_ID},
    }
    result = UnifiNetworkCollector("env", "TEST").collect_from_payloads(
        devices_payload=[switch_list, ap_list],
        detail_payloads=[switch_detail, ap_detail],
    )
    by_id = {node.source_id: node for node in result.inventory_nodes}
    assert by_id[SW_ID].category == "unifi_switch"
    assert by_id["TEST-AP-001"].category == "unifi_ap"
    # serial absent from list payload is preserved as None (Integration v1).
    assert by_id[SW_ID].serial is None
    assert by_id["TEST-AP-001"].serial is None
    assert {node.source_id for node in result.inventory_nodes} == {SW_ID, "TEST-AP-001"}
    links_by_local = {link.local_source_id: link for link in result.topology_links}
    assert links_by_local[SW_ID].remote_source_id == "TEST-AP-001"
    assert links_by_local["TEST-AP-001"].remote_source_id == SW_ID


def test_multisource_and_reverse_observations_create_one_physical_link(db: Session):
    tenant, _, mk, *_ = seed_two_tenants(db)
    mk.chassis_mac = MAC_MK
    switch = Device(
        tenant_id=tenant.id,
        site_id=mk.site_id,
        name="TEST-SW",
        device_type="unifi_switch",
        chassis_mac=MAC_SW,
        source_ref=SW_ID,
    )
    db.add(switch)
    db.commit()
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=tenant.id,
        device_id=mk.id,
        result=CollectorResult(
            interfaces=[NormalizedInterface(name="ether1", mac=MAC_MK)],
            topology_links=[
                NormalizedTopologyLink(
                    local_interface="ether1",
                    remote_mac=MAC_SW,
                    remote_chassis_id=MAC_SW,
                    remote_interface="port-24",
                    protocol="lldp",
                    source="mikrotik_neighbor",
                    observed_at=_ts(1),
                    evidence={"protocol": "lldp"},
                )
            ],
        ),
    )
    ingest.ingest_result(
        tenant_id=tenant.id,
        device_id=switch.id,
        result=CollectorResult(
            interfaces=[NormalizedInterface(name="port-24", mac=MAC_SW, source="unifi_interface")],
            topology_links=[
                NormalizedTopologyLink(
                    local_source_id=SW_ID,
                    local_interface="port-24",
                    remote_mac=MAC_MK,
                    remote_interface="ether1",
                    source="unifi_uplink",
                    protocol="unifi_uplink",
                    observed_at=_ts(2),
                    evidence={"uplink": True},
                )
            ],
        ),
    )
    db.commit()
    links = list(db.scalars(select(PhysicalLink).where(PhysicalLink.tenant_id == tenant.id)))
    assert len(links) == 1
    evidence = list(db.scalars(select(LinkEvidence).where(LinkEvidence.physical_link_id == links[0].id)))
    assert {row.source for row in evidence} == {"mikrotik_neighbor", "unifi_uplink"}
    assert links[0].directly_observed is True
    assert links[0].confidence == 1.0


def test_name_only_and_ambiguous_identifiers_do_not_materialize_link(db: Session):
    tenant, _, local, other, *_ = seed_two_tenants(db)
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=tenant.id,
        device_id=local.id,
        result=CollectorResult(
            topology_links=[NormalizedTopologyLink(local_interface="ether8", remote_identity=other.name)]
        ),
    )
    shared = "TEST-SERIAL-DUP"
    db.add_all(
        [
            DeviceIdentifier(tenant_id=tenant.id, device_id=local.id, kind="serial", value=shared, source="test"),
            DeviceIdentifier(tenant_id=tenant.id, device_id=other.id, kind="serial", value=shared, source="test"),
        ]
    )
    db.flush()
    ingest.ingest_result(
        tenant_id=tenant.id,
        device_id=local.id,
        result=CollectorResult(
            topology_links=[NormalizedTopologyLink(local_interface="ether9", remote_identifiers={"serial": shared})]
        ),
    )
    db.commit()
    assert list(db.scalars(select(PhysicalLink).where(PhysicalLink.tenant_id == tenant.id))) == []


def test_interfaces_and_physical_links_api_isolated_paginated_and_historical(db: Session):
    tenant, _, local, remote, *_ = seed_two_tenants(db)
    local.chassis_mac = MAC_MK
    remote.chassis_mac = MAC_SW
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=tenant.id,
        device_id=local.id,
        result=CollectorResult(
            interfaces=[NormalizedInterface(name="ether1", mac=MAC_MK, description="TEST")],
            topology_links=[
                NormalizedTopologyLink(
                    local_interface="ether1", remote_mac=MAC_SW, remote_interface="ether2", observed_at=_ts(1)
                )
            ],
        ),
    )
    db.commit()
    client = _client(db)
    try:
        interfaces = client.get(
            "/interfaces", params={"tenant": "example-tenant", "device_id": str(local.id), "include_history": True}
        )
        assert interfaces.status_code == 200
        assert interfaces.json()["items"][0]["history"]
        assert client.get("/interfaces", params={"tenant": "other-tenant"}).json()["items"] == []
        links = client.get("/physical-links", params={"tenant": "example-tenant", "limit": 1, "offset": 0})
        assert links.status_code == 200
        body = links.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1
        link = body["items"][0]
        assert {link["device_a"]["id"], link["device_b"]["id"]} == {str(local.id), str(remote.id)}
        assert link["sources"]
        assert link["evidence"]
        assert client.get("/physical-links", params={"tenant": "other-tenant"}).json()["items"] == []
    finally:
        app.dependency_overrides.clear()


def test_unilateral_link_is_inferred_until_reverse_confirms(db: Session):
    """A lone unilateral observation materializes as inferred/lower-confidence;
    the reverse observation promotes the consolidated link to directly_observed
    with full confidence (one PhysicalLink, two LinkEvidence rows)."""
    tenant, _, mk, sw, *_ = seed_two_tenants(db)
    mk.chassis_mac = MAC_MK
    sw.chassis_mac = MAC_SW
    ingest = IngestService(db)
    # Only MK observes SW -> unilateral.
    ingest.ingest_result(
        tenant_id=tenant.id,
        device_id=mk.id,
        result=CollectorResult(
            topology_links=[
                NormalizedTopologyLink(
                    local_interface="ether1", remote_mac=MAC_SW,
                    remote_interface="ether2", source="mikrotik_neighbor",
                    observed_at=_ts(1), directly_observed=True,
                )
            ],
        ),
    )
    db.commit()
    links = list(db.scalars(select(PhysicalLink).where(PhysicalLink.tenant_id == tenant.id)))
    assert len(links) == 1
    assert links[0].directly_observed is False
    assert links[0].inferred is True
    assert links[0].confidence < 1.0

    # SW now observes MK -> reverse arrives -> promote.
    ingest.ingest_result(
        tenant_id=tenant.id,
        device_id=sw.id,
        result=CollectorResult(
            topology_links=[
                NormalizedTopologyLink(
                    local_interface="ether2", remote_mac=MAC_MK,
                    remote_interface="ether1", source="mikrotik_neighbor",
                    observed_at=_ts(2), directly_observed=True,
                )
            ],
        ),
    )
    db.commit()
    links = list(db.scalars(select(PhysicalLink).where(PhysicalLink.tenant_id == tenant.id)))
    assert len(links) == 1  # still one consolidated link
    assert links[0].directly_observed is True
    assert links[0].inferred is False
    assert links[0].confidence == 1.0
    evidence = list(db.scalars(select(LinkEvidence).where(LinkEvidence.physical_link_id == links[0].id)))
    assert len(evidence) == 2  # both directions preserved


def test_new_inventory_device_records_identifiers_at_first_ingest(db: Session):
    """A UniFi node materializing a brand-new Device must write a
    device_identifiers row (source_id/serial) immediately — not only on a later
    run when the device already resolves by source_ref/MAC. Regression for the
    live UNIPLAC ingest where every device was new and device_identifiers stayed
    empty."""
    tenant, _, controller, *_ = seed_two_tenants(db)
    controller.source_ref = "TEST-UNIFI-CONTROLLER"
    ingest = IngestService(db)
    result = CollectorResult(
        inventory_nodes=[
            NormalizedInventoryNode(
                source_id=SW_ID,
                name="TEST-SW",
                mac=MAC_SW,
                category="unifi_switch",
                source="unifi_inventory",
                identifiers={"source_id": SW_ID},
                observed_at=_ts(3),
            )
        ]
    )
    ingest.ingest_result(tenant_id=tenant.id, device_id=controller.id, result=result)
    db.commit()
    device = db.scalar(select(Device).where(Device.source_ref == SW_ID))
    assert device is not None
    identifiers = list(db.scalars(select(DeviceIdentifier).where(DeviceIdentifier.device_id == device.id)))
    assert any(i.kind == "source_id" and i.value == SW_ID for i in identifiers)
