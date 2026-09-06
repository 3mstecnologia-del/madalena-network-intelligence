"""Evidence-backed infrastructure graph endpoint and service."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Device
from app.services.graph import GraphService
from app.services.ingest import IngestService
from collectors.common.types import (
    CollectorResult,
    NormalizedDhcpLease,
    NormalizedNeighbor,
    NormalizedOnu,
    NormalizedTopologyLink,
)
from tests.conftest import FIX, seed_two_tenants


def _onu(ont_id: str, pon: str, serial: str, status: str = "online") -> NormalizedOnu:
    return NormalizedOnu(ont_id=ont_id, pon=pon, serial=serial, status=status)


def _device(db: Session, *, tenant_id, site_id, name, device_type):
    dev = Device(
        tenant_id=tenant_id, site_id=site_id, name=name, device_type=device_type
    )
    db.add(dev)
    db.flush()
    return dev


def test_graph_site_device_pon_onu_hierarchy(db: Session):
    t1, _, d1, _, d1o, _ = seed_two_tenants(db)
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1o.id,
        result=CollectorResult(
            onus=[
                _onu("0/1/1", "0/1", "TEST-00000001"),
                _onu("0/1/2", "0/1", "TEST-00000002"),
                _onu("0/2/3", "0/2", "TEST-00000003"),
            ]
        ),
    )
    db.commit()

    g = GraphService(db).build("example-tenant")

    assert g["tenant"] == "example-tenant"
    types = {n["node_type"] for n in g["nodes"]}
    assert "site" in types and "device" in types and "pon" in types and "onu" in types

    # The OLT device must resolve to asset_type "olt".
    dev = {n["label"]: n for n in g["nodes"] if n["node_type"] == "device"}
    assert dev["LAB-G08"]["asset_type"] == "olt"
    assert dev["LAB-MK"]["asset_type"] == "router"

    # OLT -> PON -> ONU containment edges exist:
    #   2x OLT->PON (0/1, 0/2) + 3x PON->ONU (0/1/1, 0/1/2, 0/2/3) = 5
    contains = [e for e in g["edges"] if e["kind"] == "contiene"]
    assert len(contains) == 5

    # A non-OLT device must NOT gain PON/ONU child nodes: the OLT->PON edges
    # originate from exactly one top-level device (the G08 OLT).
    olt_pon = [e for e in contains if e["target"].startswith("pon:")]
    assert len(olt_pon) == 2
    olt_srcs = {e["source"] for e in olt_pon}
    assert len(olt_srcs) == 1  # only the OLT device contains at the top level


def test_graph_excludes_endpoint_collections(db: Session):
    """DHCP/ARP/FDB must not be materialized as graph nodes or edges."""
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            dhcp=[
                NormalizedDhcpLease(
                    mac="AA:BB:CC:DD:EE:FF", ip_address="10.30.1.50", hostname="notebook-exemplo"
                )
            ]
        ),
    )
    db.commit()

    g = GraphService(db).build("example-tenant")

    node_types = {n["node_type"] for n in g["nodes"]}
    assert "endpoint" not in node_types
    assert all(n["node_type"] != "onu" for n in g["nodes"])  # no ONUs seeded here


def test_graph_connected_edges_only_when_remote_resolves(db: Session):
    t1, _, d1, d1b, _, _ = seed_two_tenants(db)
    ingest = IngestService(db)
    # Remote MAC matches another managed device in the SAME tenant via d1b? No:
    # MAC_A and MAC_B both belong to interfaces. Register interface MACs for both
    # devices so the correlator can resolve the remote to a node.
    from collectors.common.types import NormalizedInterface

    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            interfaces=[NormalizedInterface(name="sfp1", mac="AA:BB:CC:10:00:01")]
        ),
    )
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1b.id,
        result=CollectorResult(
            interfaces=[NormalizedInterface(name="sfp2", mac="AA:BB:CC:10:00:02")]
        ),
    )
    db.flush()
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            topology_links=[
                NormalizedTopologyLink(
                    local_interface="sfp1",
                    remote_mac="AA:BB:CC:10:00:02",
                    remote_identity="LAB-MK-EDGE",
                    protocol="lldp",
                )
            ]
        ),
    )
    db.commit()

    g = GraphService(db).build("example-tenant")
    connected = [e for e in g["edges"] if e["kind"] == "conectado_a"]
    assert len(connected) >= 1
    assert connected[0]["status"] in {"unilateral", "confirmed"}
    assert connected[0]["evidence"]


def test_graph_unresolved_neighbor_no_fabricated_edge(db: Session):
    """A neighbor MAC that resolves to no managed device must not create an edge."""
    t1, _, d1, _, _, _ = seed_two_tenants(db)
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            topology_links=[
                NormalizedTopologyLink(
                    local_interface="ether1",
                    remote_mac="AA:BB:CC:00:00:01",  # unknown, unresolved
                    protocol="lldp",
                )
            ]
        ),
    )
    db.commit()

    g = GraphService(db).build("example-tenant")
    connected = [e for e in g["edges"] if e["kind"] == "conectado_a"]
    assert connected == []


def test_graph_tenant_isolation(db: Session):
    t1, t2, d1, _, d1o, d2 = seed_two_tenants(db)
    # Give example-tenant some ONUs under its G08 OLT (d1o) only.
    ingest = IngestService(db)
    ingest.ingest_result(
        tenant_id=t1.id,
        device_id=d1o.id,
        result=CollectorResult(onus=[_onu("0/1/9", "0/1", "TEST-00000099")]),
    )
    db.commit()

    other = GraphService(db).build("other-tenant")
    assert all(n["node_type"] != "onu" for n in other["nodes"])
    own = GraphService(db).build("example-tenant")
    assert any(n["node_type"] == "onu" for n in own["nodes"])


def test_graph_endpoint_and_ui_mount(db: Session):
    """HTTP endpoint returns the graph; the Graph UI is served under /ui/."""
    from fastapi.testclient import TestClient

    from app.api.main import app
    from app.core.db import get_db

    def override():
        yield db

    app.dependency_overrides[get_db] = override
    try:
        client = TestClient(app)
        t1, _, d1, _, d1o, _ = seed_two_tenants(db)
        ingest = IngestService(db)
        ingest.ingest_result(
            tenant_id=t1.id,
            device_id=d1o.id,
            result=CollectorResult(onus=[_onu("0/1/5", "0/1", "TEST-55555555")]),
        )
        db.commit()

        # Unknown tenant -> 404.
        r404 = client.get("/topology/graph", params={"tenant": "nope"})
        assert r404.status_code == 404

        g = client.get("/topology/graph", params={"tenant": "example-tenant"})
        assert g.status_code == 200
        body = g.json()
        assert body["tenant"] == "example-tenant"
        assert any(n["node_type"] == "onu" for n in body["nodes"])
        assert any(n["node_type"] == "pon" for n in body["nodes"])
        assert any(e["kind"] == "contiene" for e in body["edges"])

        # UI is mounted and serves the Obsidian-like view.
        ui = client.get("/ui/")
        assert ui.status_code == 200
        assert "cy" in ui.text  # the graph container present in the page
        vendor = client.get("/ui/vendor/cytoscape.min.js")
        assert vendor.status_code == 200
    finally:
        app.dependency_overrides.clear()