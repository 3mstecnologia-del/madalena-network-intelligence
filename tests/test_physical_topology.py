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
from collectors.common.types import CollectorResult, NormalizedInterface, NormalizedTopologyLink
from collectors.mikrotik.collector import MikroTikCollector
from collectors.mikrotik.parsers import parse_interfaces, parse_neighbors
from collectors.unifi.collector import UnifiNetworkCollector
from tests.conftest import seed_two_tenants

MAC_MK = "02:00:5E:10:00:01"
MAC_SW = "02:00:5E:10:00:02"
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
        '0 name=ether1 type=ether comment="TEST-uplink" default-name=ether1 mac-address=02:00:5E:10:00:01\n'
    )
    neighbors = parse_neighbors(
        "0 interface=ether1 interface-name=port-24 identity=TEST-SW "
        "chassis-id=02:00:5E:10:00:02 discoverer=lldp\n"
    )
    assert interfaces[0].description == "TEST-uplink"
    assert interfaces[0].identifiers["default_name"] == "ether1"
    assert neighbors[0].chassis_id == MAC_SW
    assert neighbors[0].protocol == "lldp"
    result = MikroTikCollector("env", "TEST").collect_from_texts(
        identity_text="name: TEST-MK",
        interfaces_text='0 name=ether1 type=ether comment="TEST-uplink" mac-address=02:00:5E:10:00:01',
        neighbors_text=(
            "0 interface=ether1 interface-name=port-24 identity=TEST-SW "
            "chassis-id=02:00:5E:10:00:02 discoverer=lldp"
        ),
    )
    assert result.identity is not None
    assert result.interfaces and result.neighbors and result.topology_links
    assert result.topology_links[0].remote_chassis_id == MAC_SW


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
