"""Correlate topology observations. Observations stay stored; this is query-time.

Identity priority: MAC/chassis, then source-specific id. Hostname/identity alone
is never a deterministic match. Conflicts stay explicit.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Device, Interface, NeighborObservation, Tenant, TopologyObservation

STATUS_CONFIRMED = "confirmed"
STATUS_UNILATERAL = "unilateral"
STATUS_UNRESOLVED = "unresolved"
STATUS_CONFLICTING = "conflicting"


@dataclass
class IdentityIndex:
    tenant_id: UUID
    mac_to_devices: dict[str, set[UUID]]
    source_to_device: dict[str, UUID]
    device_macs: dict[UUID, set[str]]
    names: dict[UUID, str]

    def by_mac(self, mac: Optional[str]) -> tuple[Optional[UUID], str]:
        if not mac:
            return None, "none"
        ids = self.mac_to_devices.get(mac) or set()
        if len(ids) == 1:
            return next(iter(ids)), "mac"
        if len(ids) > 1:
            return None, "ambiguous_mac"
        return None, "unknown"

    def by_source_id(self, source_id: Optional[str]) -> tuple[Optional[UUID], str]:
        if not source_id:
            return None, "none"
        found = self.source_to_device.get(source_id)
        if found:
            return found, "source_id"
        return None, "unknown"


def build_identity_index(db: Session, tenant_id: UUID) -> IdentityIndex:
    mac_to_devices: dict[str, set[UUID]] = defaultdict(set)
    device_macs: dict[UUID, set[str]] = defaultdict(set)
    source_to_device: dict[str, UUID] = {}
    names: dict[UUID, str] = {}
    for device in db.scalars(select(Device).where(Device.tenant_id == tenant_id)):
        names[device.id] = device.name
        if device.chassis_mac:
            mac_to_devices[device.chassis_mac].add(device.id)
            device_macs[device.id].add(device.chassis_mac)
        if device.source_ref:
            source_to_device[device.source_ref] = device.id
    for iface in db.scalars(select(Interface).where(Interface.tenant_id == tenant_id)):
        if iface.mac:
            mac_to_devices[iface.mac].add(iface.device_id)
            device_macs[iface.device_id].add(iface.mac)
    return IdentityIndex(
        tenant_id=tenant_id,
        mac_to_devices=dict(mac_to_devices),
        source_to_device=source_to_device,
        device_macs=dict(device_macs),
        names=names,
    )


def resolve_remote(index: IdentityIndex, obs: TopologyObservation) -> tuple[Optional[UUID], str, list[str]]:
    evidence: list[str] = []
    mac_id, mac_how = index.by_mac(obs.remote_mac)
    if mac_how == "ambiguous_mac":
        return None, STATUS_CONFLICTING, ["ambiguous_mac"]
    if mac_id:
        evidence.append("mac")
        src_id, src_how = index.by_source_id(obs.remote_source_id)
        if src_id and src_id != mac_id:
            return None, STATUS_CONFLICTING, ["mac_source_id_mismatch"]
        if src_how == "source_id":
            evidence.append("source_id")
        return mac_id, "resolved", evidence
    src_id, src_how = index.by_source_id(obs.remote_source_id)
    if src_id:
        evidence.append("source_id")
        return src_id, "resolved", evidence
    if obs.remote_identity:
        evidence.append("identity_name_only")
    return None, STATUS_UNRESOLVED, evidence


@dataclass
class TopologyLinkView:
    local_device_id: UUID
    local_device: str
    local_interface: Optional[str]
    remote_device_id: Optional[UUID]
    remote_device: Optional[str]
    remote_interface: Optional[str]
    remote_identity: Optional[str]
    remote_mac: Optional[str]
    remote_ip: Optional[str]
    protocol: Optional[str]
    source: str
    status: str
    evidence: list[str]
    first_seen: datetime
    last_seen: datetime
    collection_run_id: Optional[UUID]
    current: bool
    conflicts: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "local_device_id": str(self.local_device_id),
            "local_device": self.local_device,
            "local_interface": self.local_interface,
            "remote_device_id": str(self.remote_device_id) if self.remote_device_id else None,
            "remote_device": self.remote_device,
            "remote_interface": self.remote_interface,
            "remote_identity": self.remote_identity,
            "remote_mac": self.remote_mac,
            "remote_ip": self.remote_ip,
            "protocol": self.protocol,
            "source": self.source,
            "status": self.status,
            "evidence": self.evidence,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "collection_run_id": str(self.collection_run_id) if self.collection_run_id else None,
            "current": self.current,
            "conflicts": self.conflicts,
        }


class TopologyCorrelator:
    def __init__(self, db: Session):
        self.db = db

    def require_tenant(self, slug: str) -> Tenant:
        tenant = self.db.scalar(select(Tenant).where(Tenant.slug == slug))
        if tenant is None:
            raise LookupError(f"tenant not found: {slug}")
        return tenant

    def device_neighbors(
        self, tenant_slug: str, device_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> dict:
        tenant = self.require_tenant(tenant_slug)
        device = self.db.get(Device, device_id)
        if device is None or device.tenant_id != tenant.id:
            return {"tenant": tenant_slug, "device_id": str(device_id), "found": False, "neighbors": []}
        index = build_identity_index(self.db, tenant.id)
        rows = list(
            self.db.scalars(
                select(NeighborObservation)
                .where(
                    NeighborObservation.tenant_id == tenant.id,
                    NeighborObservation.device_id == device_id,
                )
                .order_by(NeighborObservation.last_seen.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        items = []
        for row in rows:
            remote_id, how = index.by_mac(row.mac)
            items.append(
                {
                    "local_interface": row.interface,
                    "remote_interface": row.remote_interface,
                    "remote_identity": row.identity,
                    "remote_mac": row.mac,
                    "remote_ip": row.ip_address,
                    "platform": row.platform,
                    "version": row.version,
                    "protocol": row.protocol,
                    "source": row.source,
                    "first_seen": row.first_seen.isoformat() if row.first_seen else None,
                    "last_seen": row.last_seen.isoformat() if row.last_seen else None,
                    "remote_device_id": str(remote_id) if remote_id else None,
                    "remote_device": index.names.get(remote_id) if remote_id else None,
                    "match": how if row.mac else "none",
                    "collection_run_id": str(row.collection_run_id) if row.collection_run_id else None,
                }
            )
        return {
            "tenant": tenant.slug,
            "device_id": str(device.id),
            "device": device.name,
            "found": True,
            "neighbors": items,
            "limit": limit,
            "offset": offset,
        }

    def topology(
        self,
        tenant_slug: str,
        *,
        device_id: Optional[UUID] = None,
        include_history: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        tenant = self.require_tenant(tenant_slug)
        if device_id is not None:
            device = self.db.get(Device, device_id)
            if device is None or device.tenant_id != tenant.id:
                return {
                    "tenant": tenant_slug,
                    "device_id": str(device_id),
                    "found": False,
                    "links": [],
                }
        index = build_identity_index(self.db, tenant.id)
        q = select(TopologyObservation).where(TopologyObservation.tenant_id == tenant.id)
        if device_id is not None:
            q = q.where(TopologyObservation.local_device_id == device_id)
        rows = list(self.db.scalars(q.order_by(TopologyObservation.last_seen.desc())))
        views = self._classify(index, rows)
        if not include_history:
            views = [v for v in views if v.current]
        total = len(views)
        page = views[offset : offset + limit]
        confirmed = sum(1 for v in views if v.status == STATUS_CONFIRMED)
        unilateral = sum(1 for v in views if v.status == STATUS_UNILATERAL)
        conflicting = sum(1 for v in views if v.status == STATUS_CONFLICTING)
        unresolved = sum(1 for v in views if v.status == STATUS_UNRESOLVED)
        return {
            "tenant": tenant.slug,
            "device_id": str(device_id) if device_id else None,
            "found": True,
            "include_history": include_history,
            "counts": {
                "total": total,
                "confirmed": confirmed,
                "unilateral": unilateral,
                "conflicting": conflicting,
                "unresolved": unresolved,
            },
            "links": [v.to_dict() for v in page],
            "limit": limit,
            "offset": offset,
        }

    def _classify(self, index: IdentityIndex, rows: list[TopologyObservation]) -> list[TopologyLinkView]:
        resolved: list[tuple[TopologyObservation, Optional[UUID], list[str], str]] = []
        for row in rows:
            remote_id, kind, evidence = resolve_remote(index, row)
            resolved.append((row, remote_id, evidence, kind))

        reverse: set[tuple[UUID, UUID]] = set()
        for row, remote_id, _, kind in resolved:
            if remote_id and kind == "resolved":
                reverse.add((row.local_device_id, remote_id))

        latest: dict[tuple[UUID, Optional[str]], datetime] = {}
        for row, *_ in resolved:
            key = (row.local_device_id, row.local_interface)
            last = latest.get(key)
            if last is None or _as_utc(row.last_seen) > _as_utc(last):
                latest[key] = row.last_seen

        current_remotes: dict[tuple[UUID, Optional[str]], set[str]] = defaultdict(set)
        for row, remote_id, _, _ in resolved:
            key = (row.local_device_id, row.local_interface)
            if _as_utc(row.last_seen) != _as_utc(latest[key]):
                continue
            token = (
                str(remote_id)
                if remote_id
                else (row.remote_mac or row.remote_source_id or row.remote_identity or "?")
            )
            current_remotes[key].add(token)

        views: list[TopologyLinkView] = []
        for row, remote_id, evidence, kind in resolved:
            key = (row.local_device_id, row.local_interface)
            is_current = _as_utc(row.last_seen) == _as_utc(latest[key])
            conflicts: list[dict] = []
            status = STATUS_UNRESOLVED
            if remote_id == row.local_device_id:
                status = STATUS_CONFLICTING
                conflicts.append({"kind": "self_link"})
            elif kind == STATUS_CONFLICTING:
                status = STATUS_CONFLICTING
                conflicts.append({"kind": evidence[0] if evidence else "conflict"})
            elif is_current and len(current_remotes.get(key, set())) > 1:
                status = STATUS_CONFLICTING
                conflicts.append(
                    {
                        "kind": "interface_conflict",
                        "message": "Same local interface currently observes multiple remotes.",
                        "values": sorted(current_remotes[key]),
                    }
                )
                remote_id = None
            elif remote_id:
                if (remote_id, row.local_device_id) in reverse:
                    status = STATUS_CONFIRMED
                    evidence = list(evidence) + ["bilateral"]
                else:
                    status = STATUS_UNILATERAL
            views.append(
                TopologyLinkView(
                    local_device_id=row.local_device_id,
                    local_device=index.names.get(row.local_device_id, str(row.local_device_id)),
                    local_interface=row.local_interface,
                    remote_device_id=remote_id,
                    remote_device=index.names.get(remote_id) if remote_id else None,
                    remote_interface=row.remote_interface,
                    remote_identity=row.remote_identity,
                    remote_mac=row.remote_mac,
                    remote_ip=row.remote_ip,
                    protocol=row.protocol,
                    source=row.source,
                    status=status,
                    evidence=evidence,
                    first_seen=row.first_seen,
                    last_seen=row.last_seen,
                    collection_run_id=row.collection_run_id,
                    current=is_current,
                    conflicts=conflicts,
                )
            )
        return views


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
