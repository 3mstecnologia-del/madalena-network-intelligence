"""Topology observations, multi-source correlation, history, policy, isolation."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.main import app
from app.core.db import get_db
from app.models.entities import (
    Device,
    ExclusionPolicy,
    NeighborObservation,
    TopologyObservation,
)
from app.services.ingest import IngestService
from app.services.query import QueryService
from collectors.common.types import (
    CollectorResult,
    NormalizedDhcpLease,
    NormalizedInterface,
    NormalizedInventoryNode,
    NormalizedNeighbor,
    NormalizedTopologyLink,
)
from collectors.mikrotik.collector import MikroTikCollector
from collectors.unifi.collector import UnifiNetworkCollector
from collectors.unifi.transport_http import MemoryUnifiClient
from mcp_server.server import app as mcp_app
from tests.conftest import FIX, seed_two_tenants

MAC_A = "AA:BB:CC:10:00:01"
MAC_B = "AA:BB:CC:10:00:02"
MAC_SW = "AA:BB:CC:20:00:01"
MAC_AP = "AA:BB:CC:20:00:02"
SITE = "11111111-1111-4111-8111-111111111111"
SW = "22222222-2222-4222-8222-222222222222"
AP = "33333333-3333-4333-8333-333333333333"


def _ts(hour: int) -> datetime:
    return datetime(2026, 9, 3, hour, 0, tzinfo=timezone.utc)


def _ifaces(device_name: str, iface: str, mac: str) -> list[NormalizedInterface]:
    return [NormalizedInterface(name=iface, mac=mac, source="mikrotik_interface")]


class _SessionProxy:
    def __init__(self, inner: Session):
        self._inner = inner

    def close(self) -> None:
        return None

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _api(db: Session) -> TestClient:
    def override():
        yield db

    app.dependency_overrides[get_db] = override
    return TestClient(app)


def _mcp(db: Session, monkeypatch) -> TestClient:
    monkeypatch.setattr("mcp_server.server.SessionLocal", lambda: _SessionProxy(db))
    return TestClient(mcp_app)


def test_neighbor_complete_and_multiple_per_interface(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    result = MikroTikCollector("env", "x").collect_from_texts(
        neighbors_text=(FIX / "mikrotik_neighbors_protocols.txt").read_text()
    )
    IngestService(db).ingest_result(tenant_id=t1.id, device_id=d1.id, result=result)
    db.commit()
    rows = list(
        db.scalars(select(NeighborObservation).where(NeighborObservation.device_id == d1.id))
    )
    assert len(rows) == 3
    ifaces = {r.interface for r in rows}
    assert ifaces == {"ether1", "ether2", "ether3"}
    topo = list(db.scalars(select(TopologyObservation).where(TopologyObservation.local_device_id == d1.id)))
    assert len(topo) == 3


def test_same_neighbor_seen_by_two_devices(db: Session):
    t1, _, d1, d1b, _, _ = seed_two_tenants(db)
    ingest = IngestService(db)
    n = NormalizedNeighbor(
        mac=MAC_SW, interface="ether5", identity="LAB-UNIFI-SW", protocol="lldp", observed_at=_ts(1)
    )
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            neighbors=[n],
            topology_links=[
                NormalizedTopologyLink(
                    local_interface="ether5",
                    remote_mac=MAC_SW,
                    remote_identity="LAB-UNIFI-SW",
                    protocol="lldp",
                    observed_at=_ts(1),
                )
            ],
        ),
    )
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1b.id,
        result=CollectorResult(
            neighbors=[
                NormalizedNeighbor(
                    mac=MAC_SW, interface="sfp1", identity="LAB-UNIFI-SW", protocol="lldp", observed_at=_ts(1)
                )
            ],
            topology_links=[
                NormalizedTopologyLink(
                    local_interface="sfp1",
                    remote_mac=MAC_SW,
                    remote_identity="LAB-UNIFI-SW",
                    protocol="lldp",
                    observed_at=_ts(1),
                )
            ],
        ),
    )
    db.commit()
    rows = list(db.scalars(select(TopologyObservation).where(TopologyObservation.remote_mac == MAC_SW)))
    assert {r.local_device_id for r in rows} == {d1.id, d1b.id}


def test_mac_correlation_and_name_only_is_not_match(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    controller = Device(
        tenant_id=t1.id,
        site_id=d1.site_id,
        name="LAB-UNIFI",
        device_type="unifi_network",
        vendor="Ubiquiti",
        enabled=False,
    )
    db.add(controller)
    db.commit()
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=controller.id,
        result=CollectorResult(
            inventory_nodes=[
                NormalizedInventoryNode(
                    source_id=SW,
                    name="SWITCH-01",
                    mac=MAC_SW,
                    category="usw",
                    observed_at=_ts(1),
                )
            ]
        ),
    )
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            topology_links=[
                NormalizedTopologyLink(
                    local_interface="ether5",
                    remote_mac=MAC_SW,
                    remote_identity="SWITCH-01",
                    protocol="lldp",
                    observed_at=_ts(2),
                ),
                NormalizedTopologyLink(
                    local_interface="ether8",
                    remote_identity="SWITCH-01",
                    protocol="lldp",
                    observed_at=_ts(2),
                ),
            ]
        ),
    )
    db.commit()
    data = QueryService(db).get_topology("example-tenant")
    by_iface = {row["local_interface"]: row for row in data["links"]}
    assert by_iface["ether5"]["remote_device_id"] is not None
    assert by_iface["ether5"]["status"] in {"unilateral", "confirmed"}
    assert "mac" in by_iface["ether5"]["evidence"]
    assert by_iface["ether8"]["remote_device_id"] is None
    assert by_iface["ether8"]["status"] == "unresolved"
    assert "identity_name_only" in by_iface["ether8"]["evidence"]


def test_unilateral_and_bilateral_links(db: Session):
    t1, _, d1, d1b, _, _ = seed_two_tenants(db)
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(interfaces=_ifaces("a", "sfp1", MAC_A)),
    )
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1b.id,
        result=CollectorResult(interfaces=_ifaces("b", "sfp2", MAC_B)),
    )
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            topology_links=[
                NormalizedTopologyLink(
                    local_interface="sfp1",
                    remote_mac=MAC_B,
                    remote_interface="sfp2",
                    protocol="lldp",
                    observed_at=_ts(3),
                )
            ]
        ),
    )
    db.commit()
    uni = QueryService(db).device_links("example-tenant", d1.id)
    assert uni["links"][0]["status"] == "unilateral"
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1b.id,
        result=CollectorResult(
            topology_links=[
                NormalizedTopologyLink(
                    local_interface="sfp2",
                    remote_mac=MAC_A,
                    remote_interface="sfp1",
                    protocol="lldp",
                    observed_at=_ts(3),
                )
            ]
        ),
    )
    db.commit()
    both = QueryService(db).get_topology("example-tenant")
    statuses = {row["status"] for row in both["links"]}
    assert "confirmed" in statuses
    assert both["counts"]["confirmed"] >= 2


def test_self_link_is_conflicting_not_bilateral(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(interfaces=_ifaces("a", "sfp1", MAC_A)),
    )
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            topology_links=[
                NormalizedTopologyLink(
                    local_interface="sfp1",
                    remote_mac=MAC_A,
                    protocol="lldp",
                    observed_at=_ts(3),
                )
            ]
        ),
    )
    db.commit()

    data = QueryService(db).device_links("example-tenant", d1.id)

    assert data["counts"]["confirmed"] == 0
    assert data["counts"]["conflicting"] == 1
    assert data["links"][0]["status"] == "conflicting"
    assert data["links"][0]["conflicts"] == [{"kind": "self_link"}]


def test_interface_conflict_is_explicit(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            topology_links=[
                NormalizedTopologyLink(
                    local_interface="sfp1",
                    remote_mac=MAC_B,
                    remote_interface="sfp2",
                    protocol="lldp",
                    observed_at=_ts(4),
                ),
                NormalizedTopologyLink(
                    local_interface="sfp1",
                    remote_mac=MAC_SW,
                    remote_interface="port-10",
                    protocol="lldp",
                    observed_at=_ts(4),
                ),
            ]
        ),
    )
    db.commit()
    data = QueryService(db).device_links("example-tenant", d1.id)
    assert data["counts"]["conflicting"] >= 1
    assert all(row["status"] == "conflicting" for row in data["links"])
    assert all(row["remote_device_id"] is None for row in data["links"])


def test_uplink_change_preserves_history_and_absence_does_not_delete(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            topology_links=[
                NormalizedTopologyLink(
                    local_interface="sfp1",
                    remote_mac=MAC_B,
                    protocol="lldp",
                    observed_at=_ts(1),
                )
            ]
        ),
    )
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            topology_links=[
                NormalizedTopologyLink(
                    local_interface="sfp1",
                    remote_mac=MAC_SW,
                    protocol="lldp",
                    observed_at=_ts(5),
                )
            ]
        ),
    )
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(dhcp=[NormalizedDhcpLease(mac=MAC_A, ip_address="10.30.2.50", observed_at=_ts(6))]),
    )
    db.commit()
    rows = list(
        db.scalars(
            select(TopologyObservation).where(
                TopologyObservation.local_device_id == d1.id,
                TopologyObservation.local_interface == "sfp1",
            )
        )
    )
    assert len(rows) == 2
    macs = {r.remote_mac for r in rows}
    assert macs == {MAC_B, MAC_SW}
    current = QueryService(db).device_links("example-tenant", d1.id)
    assert len(current["links"]) == 1
    assert current["links"][0]["remote_mac"] == MAC_SW
    hist = QueryService(db).device_links("example-tenant", d1.id, include_history=True)
    assert len(hist["links"]) == 2


def test_unifi_inventory_ingest_and_uplink(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    controller = Device(
        tenant_id=t1.id,
        site_id=d1.site_id,
        name="LAB-UNIFI",
        device_type="unifi_network",
        vendor="Ubiquiti",
    )
    db.add(controller)
    db.commit()
    payloads = {
        "/v1/info": json.loads((FIX / "unifi_info.json").read_text()),
        "/v1/sites": json.loads((FIX / "unifi_sites.json").read_text()),
        f"/v1/sites/{SITE}/devices": json.loads((FIX / "unifi_devices.json").read_text()),
        f"/v1/sites/{SITE}/devices/{SW}": json.loads((FIX / "unifi_device_switch.json").read_text()),
        f"/v1/sites/{SITE}/devices/{AP}": json.loads((FIX / "unifi_device_ap.json").read_text()),
    }
    client = MemoryUnifiClient(payloads)
    result = UnifiNetworkCollector("env", "x", client=client).collect_via_client(client, site_id=SITE)
    isolated = json.loads((FIX / "unifi_device_ap_no_uplink.json").read_text())
    extra = UnifiNetworkCollector("env", "x").collect_from_payloads(devices_payload=[isolated])
    result.inventory_nodes.extend(extra.inventory_nodes)
    result.topology_links.extend(extra.topology_links)
    IngestService(db).ingest_result(tenant_id=t1.id, device_id=controller.id, result=result)
    db.commit()
    names = {d.name for d in db.scalars(select(Device).where(Device.tenant_id == t1.id))}
    assert "LAB-UNIFI-SW" in names
    assert "LAB-UNIFI-AP" in names
    assert "LAB-UNIFI-AP-ISOLATED" in names
    topo = QueryService(db).get_topology("example-tenant")
    uplinks = [row for row in topo["links"] if row["source"] == "unifi_uplink"]
    assert len(uplinks) == 1
    assert uplinks[0]["remote_device"] == "LAB-UNIFI-SW"


def test_policy_excludes_topology_before_persist(db: Session):
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    db.add(ExclusionPolicy(tenant_id=t1.id, rule_type="interface", rule_value="ether9", enabled=True))
    db.commit()
    stats = IngestService(db).ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            neighbors=[
                NormalizedNeighbor(mac=MAC_SW, interface="ether9", identity="SW"),
                NormalizedNeighbor(mac=MAC_AP, interface="ether1", identity="AP"),
            ],
            topology_links=[
                NormalizedTopologyLink(local_interface="ether9", remote_mac=MAC_SW),
                NormalizedTopologyLink(local_interface="ether1", remote_mac=MAC_AP),
            ],
        ),
    )
    db.commit()
    assert stats["excluded"] >= 2
    rows = list(db.scalars(select(TopologyObservation).where(TopologyObservation.local_device_id == d1.id)))
    assert len(rows) == 1
    assert rows[0].local_interface == "ether1"


def test_topology_tenant_isolation(db: Session):
    t1, t2, d1, _, _, d2 = seed_two_tenants(db)
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            topology_links=[NormalizedTopologyLink(local_interface="sfp1", remote_mac=MAC_B)]
        ),
    )
    db.commit()
    other = QueryService(db).get_topology("other-tenant")
    assert other["links"] == []
    assert other["counts"]["total"] == 0
    own = QueryService(db).get_topology("example-tenant")
    assert own["counts"]["total"] == 1


def test_api_and_mcp_topology(db: Session, monkeypatch):
    t1, _, d1, d1b, _, _ = seed_two_tenants(db)
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(interfaces=_ifaces("a", "sfp1", MAC_A)),
    )
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1b.id,
        result=CollectorResult(
            interfaces=_ifaces("b", "sfp2", MAC_B),
            topology_links=[
                NormalizedTopologyLink(
                    local_interface="sfp2", remote_mac=MAC_A, protocol="lldp", observed_at=_ts(1)
                )
            ],
        ),
    )
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            neighbors=[
                NormalizedNeighbor(
                    mac=MAC_B, interface="sfp1", identity="LAB-MK-EDGE", protocol="lldp", observed_at=_ts(1)
                )
            ],
            topology_links=[
                NormalizedTopologyLink(
                    local_interface="sfp1",
                    remote_mac=MAC_B,
                    remote_identity="LAB-MK-EDGE",
                    protocol="lldp",
                    observed_at=_ts(1),
                )
            ],
        ),
    )
    db.commit()
    client = _api(db)
    try:
        neigh = client.get(f"/devices/{d1.id}/neighbors", params={"tenant": "example-tenant"})
        assert neigh.status_code == 200
        assert neigh.json()["neighbors"]
        links = client.get(f"/devices/{d1.id}/links", params={"tenant": "example-tenant"})
        assert links.status_code == 200
        assert "password" not in links.text.lower()
        topo = client.get("/topology", params={"tenant": "example-tenant", "limit": 20})
        assert topo.status_code == 200
        body = topo.json()
        assert body["counts"]["total"] >= 1
        hidden = client.get("/topology", params={"tenant": "other-tenant"})
        assert hidden.json()["links"] == []
    finally:
        app.dependency_overrides.clear()

    mcp = _mcp(db, monkeypatch)
    res = mcp.post(
        "/tools/get_topology",
        json={"tenant": "example-tenant", "limit": 20},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert "confirmed=" in res.json()["text"]
    missing = mcp.post("/tools/get_device_links", json={"tenant": "example-tenant"})
    assert missing.status_code == 400
