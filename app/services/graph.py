"""Build an evidence-backed infrastructure graph from persisted intelligence.

The graph is derived at query-time from persisted observations — it is never
hardcoded. Nodes represent infrastructure assets (sites, managed devices,
PON groups, ONUs). Edges carry a typed relation with its origin/evidence and
time windows, so newly discovered equipment appears without touching the
client.

Endpoint/client machines (DHCP/ARP/FDB viewers, phones, notebooks) are
deliberately NOT materialized as nodes: they live in the correlation tables for
internal enrichment but must not pollute the infrastructure graph.

Relation vocabulary (each edge carries `kind` + evidence + first/last_seen):
- pertence_a    : device belongs to a site (source: devices.site_id)
- contiene      : OLT -> PON -> ONU (source: olt_onus.pon / olt_onus.ont_id)
- conectado_a   : two devices physically linked (source: correlated topology /
                  neighbor observations; only when the remote resolves)
- uplink_de     : inventory node uplinks to a controller/gateway
- alcanzable_via: routed reachability (reserved; only emitted with evidence)
- anuncia_rede  : device advertises a network (reserved; evidence-gated)
- observado_em  : a node observed at a site (evidence-gated)

Kinds without persisted evidence simply emit no edges; the schema still admits
them so the frontend and future collectors stay decoupled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.correlation.topology import TopologyCorrelator
from app.models.entities import Device, OltOnu, Site, Tenant


def _utc_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


# Map a managed device_type to a stable, generic asset type usable by any
# client without coupling to a specific vendor. Unknown types fall through so
# future collectors (switch/AP/Proxmox) render without code changes.
DEVICE_TYPE_TO_ASSET = {
    "mikrotik": "router",
    "intelbras_g08": "olt",
    "switch": "switch",
    "unifi_network": "controller",
    "proxmox": "server",
    "proxmox_host": "server",
}


def _asset_type(device_type: str) -> str:
    return DEVICE_TYPE_TO_ASSET.get(device_type, device_type or "device")


@dataclass
class _Node:
    id: str
    node_type: str
    label: str
    asset_type: str
    meta: dict = field(default_factory=dict)
    parent_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "node_type": self.node_type,
            "label": self.label,
            "asset_type": self.asset_type,
            "meta": self.meta,
            "parent_id": self.parent_id,
        }


@dataclass
class _Edge:
    kind: str
    source: str
    target: str
    status: str
    evidence: list[str]
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    meta: dict = field(default_factory=dict)
    edge_id: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.edge_id or f"{self.kind}:{self.source}:{self.target}",
            "kind": self.kind,
            "source": self.source,
            "target": self.target,
            "status": self.status,
            "evidence": self.evidence,
            "first_seen": _utc_iso(self.first_seen),
            "last_seen": _utc_iso(self.last_seen),
            "meta": self.meta,
        }


class GraphService:
    """Assemble the infrastructure graph for one tenant."""

    def __init__(self, db: Session):
        self.db = db
        self.topology = TopologyCorrelator(db)

    def require_tenant(self, slug: str) -> Tenant:
        tenant = self.db.scalar(select(Tenant).where(Tenant.slug == slug))
        if tenant is None:
            raise LookupError(f"tenant not found: {slug}")
        return tenant

    def build(self, tenant_slug: str, *, include_connected: bool = True) -> dict:
        tenant = self.require_tenant(tenant_slug)
        nodes: dict[str, _Node] = {}
        edges: list[_Edge] = []

        sites = list(
            self.db.scalars(
                select(Site).where(Site.tenant_id == tenant.id).order_by(Site.name)
            )
        )
        site_by_id = {s.id: s for s in sites}
        for site in sites:
            nodes[str(site.id)] = _Node(
                id=str(site.id),
                node_type="site",
                label=site.name or site.slug,
                asset_type="site",
                meta={"slug": site.slug},
            )

        devices = list(
            self.db.scalars(
                select(Device).where(Device.tenant_id == tenant.id).order_by(Device.name)
            )
        )
        asset_type_by_device: dict[UUID, str] = {}
        for dev in devices:
            at = _asset_type(dev.device_type)
            asset_type_by_device[dev.id] = at
            _add_device_node(nodes, dev, at, site_by_id=site_by_id)
            if dev.site_id and dev.site_id in site_by_id:
                site = site_by_id[dev.site_id]
                edges.append(
                    _Edge(
                        kind="pertence_a",
                        source=str(dev.id),
                        target=str(site.id),
                        status="confirmed",
                        evidence=["devices.site_id"],
                        first_seen=dev.created_at,
                        last_seen=dev.last_observed_at or dev.created_at,
                        meta={"site": site.slug},
                    )
                )

        # OLT -> PON -> ONU hierarchy derived from olt_onus (real evidence).
        self._add_pon_onu_nodes(tenant.id, nodes, edges, asset_type_by_device)

        if include_connected:
            self._add_connected_edges(tenant_slug, nodes, edges)

        return {
            "tenant": tenant.slug,
            "asset_types": sorted({n.asset_type for n in nodes.values()}),
            "relation_kinds": sorted({e.kind for e in edges}),
            "nodes": [n.to_dict() for n in nodes.values()],
            "edges": [e.to_dict() for e in edges],
        }

    def _add_pon_onu_nodes(
        self,
        tenant_id: UUID,
        nodes: dict[str, _Node],
        edges: list[_Edge],
        asset_type_by_device: dict[UUID, str],
    ) -> None:
        onus = list(
            self.db.scalars(
                select(OltOnu)
                .where(OltOnu.tenant_id == tenant_id)
                .order_by(OltOnu.device_id, OltOnu.pon, OltOnu.ont_id)
            )
        )
        pon_node_id: dict[tuple[UUID, Optional[str]], str] = {}
        for onu in onus:
            device_id = onu.device_id
            # A PON group only exists under a device of OLT asset type.
            if asset_type_by_device.get(device_id) != "olt":
                continue
            pon_key = (device_id, onu.pon)
            parent_id = pon_node_id.get(pon_key)
            if parent_id is None:
                parent_id = f"pon:{device_id.hex}:{onu.pon or '_'}"
                pon_label = f"PON {onu.pon}" if onu.pon else "PON ?"
                nodes[parent_id] = _Node(
                    id=parent_id,
                    node_type="pon",
                    label=pon_label,
                    asset_type="pon",
                    meta={"pon": onu.pon, "device_id": str(device_id)},
                    parent_id=str(device_id),
                )
                pon_node_id[pon_key] = parent_id
                edges.append(
                    _Edge(
                        kind="contiene",
                        source=str(device_id),
                        target=parent_id,
                        status="confirmed",
                        evidence=["olt_onus.pon"],
                        first_seen=onu.first_seen,
                        last_seen=onu.last_seen,
                        meta={"pon": onu.pon},
                    )
                )
            onu_id = f"onu:{device_id.hex}:{onu.ont_id}"
            nodes[onu_id] = _Node(
                id=onu_id,
                node_type="onu",
                label=onu.ont_id,
                asset_type="onu",
                meta={
                    "ont_id": onu.ont_id,
                    "pon": onu.pon,
                    "serial": onu.serial,
                    "status": onu.status,
                    "profile_name": onu.profile_name,
                },
                parent_id=parent_id,
            )
            edges.append(
                _Edge(
                    kind="contiene",
                    source=parent_id,
                    target=onu_id,
                    status="confirmed" if onu.status == "online" else "unilateral",
                    evidence=["olt_onus.ont_id"],
                    first_seen=onu.first_seen,
                    last_seen=onu.last_seen,
                    meta={"ont_id": onu.ont_id, "pon": onu.pon},
                )
            )

    def _add_connected_edges(
        self, tenant_slug: str, nodes: dict[str, _Node], edges: list[_Edge]
    ) -> None:
        """Add device<->device relations only when the remote resolves to a node."""
        try:
            data = self.topology.topology(tenant_slug, include_history=False, limit=500)
        except LookupError:
            return
        for link in data.get("links", []):
            remote_id = link.get("remote_device_id")
            if not remote_id:
                continue  # unresolved remote -> no fabricated edge
            source = str(link["local_device_id"])
            target = str(remote_id)
            if source not in nodes or target not in nodes:
                continue
            edges.append(
                _Edge(
                    kind="conectado_a",
                    source=source,
                    target=target,
                    status=link.get("status", "unknown"),
                    evidence=link.get("evidence") or ["topology_observation"],
                    first_seen=_parse_dt(link.get("first_seen")),
                    last_seen=_parse_dt(link.get("last_seen")),
                    meta={
                        "protocol": link.get("protocol"),
                        "local_interface": link.get("local_interface"),
                        "remote_interface": link.get("remote_interface"),
                        "source": link.get("source"),
                    },
                )
            )


def _add_device_node(
    nodes: dict[str, _Node],
    dev: Device,
    asset_type: str,
    *,
    site_by_id: dict[UUID, Site],
) -> None:
    parent_id = str(dev.site_id) if dev.site_id and dev.site_id in site_by_id else None
    nodes[str(dev.id)] = _Node(
        id=str(dev.id),
        node_type="device",
        label=dev.name,
        asset_type=asset_type,
        meta={
            "device_type": dev.device_type,
            "vendor": dev.vendor,
            "model": dev.model,
            "enabled": dev.enabled,
            "last_identity": dev.last_identity,
            "last_version": dev.last_version,
            "site_id": str(dev.site_id) if dev.site_id else None,
        },
        parent_id=parent_id,
    )


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None