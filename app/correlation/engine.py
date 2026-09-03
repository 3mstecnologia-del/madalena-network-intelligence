"""Correlate observations for a MAC without destroying raw rows.

Current state is derived from latest timestamps. Conflicting evidence is
exposed as `conflicts` — never collapsed into a single invented truth.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.mac import normalize_mac
from app.models.entities import (
    ArpObservation,
    Device,
    DhcpLease,
    MacAddress,
    MacObservation,
    NeighborObservation,
    OltMacObservation,
    OltOnu,
    Tenant,
)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


@dataclass
class AccessPath:
    olt_device: Optional[str] = None
    olt_device_id: Optional[str] = None
    pon: Optional[str] = None
    onu: Optional[str] = None
    vlan_id: Optional[int] = None
    profile: Optional[str] = None
    serial: Optional[str] = None


@dataclass
class MacCorrelation:
    mac: str
    tenant: str
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    current_ips: list[dict[str, Any]] = field(default_factory=list)
    historical_ips: list[dict[str, Any]] = field(default_factory=list)
    current_locations: list[dict[str, Any]] = field(default_factory=list)
    historical_locations: list[dict[str, Any]] = field(default_factory=list)
    hostname: Optional[str] = None
    dhcp: list[dict[str, Any]] = field(default_factory=list)
    arp: list[dict[str, Any]] = field(default_factory=list)
    fdb: list[dict[str, Any]] = field(default_factory=list)
    neighbors: list[dict[str, Any]] = field(default_factory=list)
    access_path: Optional[AccessPath] = None
    olt_macs: list[dict[str, Any]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for key in ("first_seen", "last_seen"):
            if d.get(key) is not None:
                d[key] = d[key].isoformat()
        return d


class CorrelationEngine:
    def __init__(self, db: Session):
        self.db = db

    def correlate_mac(self, tenant_slug: str, mac_raw: str) -> Optional[MacCorrelation]:
        mac = normalize_mac(mac_raw)
        tenant = self.db.scalar(select(Tenant).where(Tenant.slug == tenant_slug))
        if tenant is None:
            return None
        return self._correlate(tenant, mac)

    def correlate_mac_by_tenant_id(self, tenant_id: UUID, mac_raw: str) -> Optional[MacCorrelation]:
        mac = normalize_mac(mac_raw)
        tenant = self.db.get(Tenant, tenant_id)
        if tenant is None:
            return None
        return self._correlate(tenant, mac)

    def _device_name(self, device_id: UUID) -> Optional[str]:
        device = self.db.get(Device, device_id)
        return device.name if device else None

    def _correlate(self, tenant: Tenant, mac: str) -> MacCorrelation:
        mac_row = self.db.scalar(
            select(MacAddress).where(MacAddress.tenant_id == tenant.id, MacAddress.mac == mac)
        )
        dhcp_rows = list(
            self.db.scalars(
                select(DhcpLease)
                .where(DhcpLease.tenant_id == tenant.id, DhcpLease.mac == mac)
                .order_by(DhcpLease.last_seen.desc())
            )
        )
        arp_rows = list(
            self.db.scalars(
                select(ArpObservation)
                .where(ArpObservation.tenant_id == tenant.id, ArpObservation.mac == mac)
                .order_by(ArpObservation.last_seen.desc())
            )
        )
        fdb_rows = list(
            self.db.scalars(
                select(MacObservation)
                .where(MacObservation.tenant_id == tenant.id, MacObservation.mac == mac)
                .order_by(MacObservation.last_seen.desc())
            )
        )
        olt_rows = list(
            self.db.scalars(
                select(OltMacObservation)
                .where(OltMacObservation.tenant_id == tenant.id, OltMacObservation.mac == mac)
                .order_by(OltMacObservation.last_seen.desc())
            )
        )
        neighbor_rows = list(
            self.db.scalars(
                select(NeighborObservation)
                .where(NeighborObservation.tenant_id == tenant.id, NeighborObservation.mac == mac)
                .order_by(NeighborObservation.last_seen.desc())
            )
        )

        sources: set[str] = set()
        hostname = None
        timeline: list[dict[str, Any]] = []

        dhcp_out = []
        ip_events: list[tuple[datetime, dict[str, Any]]] = []
        for row in dhcp_rows:
            sources.add(row.source)
            device_name = self._device_name(row.device_id)
            item = {
                "ip": row.ip_address,
                "hostname": row.hostname,
                "server": row.server,
                "status": row.status,
                "device": device_name,
                "device_id": str(row.device_id),
                "first_seen": _iso(row.first_seen),
                "last_seen": _iso(row.last_seen),
                "source": row.source,
                "collection_run_id": str(row.collection_run_id) if row.collection_run_id else None,
            }
            dhcp_out.append(item)
            if hostname is None:
                hostname = row.hostname
            ip_events.append((row.last_seen, {"ip": row.ip_address, "via": "dhcp", "device": device_name}))
            timeline.append(
                {
                    "at": _iso(row.last_seen),
                    "kind": "dhcp_lease",
                    "device": device_name,
                    "device_id": str(row.device_id),
                    "interface": None,
                    "ip": row.ip_address,
                    "source": row.source,
                    "first_seen": _iso(row.first_seen),
                    "last_seen": _iso(row.last_seen),
                    "collection_run_id": str(row.collection_run_id) if row.collection_run_id else None,
                }
            )

        arp_out = []
        for row in arp_rows:
            sources.add(row.source)
            device_name = self._device_name(row.device_id)
            item = {
                "ip": row.ip_address,
                "interface": row.interface,
                "device": device_name,
                "device_id": str(row.device_id),
                "first_seen": _iso(row.first_seen),
                "last_seen": _iso(row.last_seen),
                "source": row.source,
                "collection_run_id": str(row.collection_run_id) if row.collection_run_id else None,
            }
            arp_out.append(item)
            ip_events.append(
                (row.last_seen, {"ip": row.ip_address, "via": "arp", "device": device_name})
            )
            timeline.append(
                {
                    "at": _iso(row.last_seen),
                    "kind": "arp",
                    "device": device_name,
                    "device_id": str(row.device_id),
                    "interface": row.interface,
                    "ip": row.ip_address,
                    "source": row.source,
                    "first_seen": _iso(row.first_seen),
                    "last_seen": _iso(row.last_seen),
                    "collection_run_id": str(row.collection_run_id) if row.collection_run_id else None,
                }
            )

        fdb_out = []
        location_events: list[tuple[datetime, dict[str, Any]]] = []
        for row in fdb_rows:
            sources.add(row.source)
            device_name = self._device_name(row.device_id)
            loc = {
                "interface": row.interface,
                "vlan_id": row.vlan_id,
                "bridge": row.bridge,
                "device": device_name,
                "device_id": str(row.device_id),
                "source": row.source,
                "first_seen": _iso(row.first_seen),
                "last_seen": _iso(row.last_seen),
            }
            fdb_out.append(loc)
            location_events.append((row.last_seen, loc))
            timeline.append(
                {
                    "at": _iso(row.last_seen),
                    "kind": "fdb",
                    "device": device_name,
                    "device_id": str(row.device_id),
                    "interface": row.interface,
                    "ip": None,
                    "vlan_id": row.vlan_id,
                    "source": row.source,
                    "first_seen": _iso(row.first_seen),
                    "last_seen": _iso(row.last_seen),
                    "collection_run_id": str(row.collection_run_id) if row.collection_run_id else None,
                }
            )

        if not location_events:
            for row in arp_rows:
                device_name = self._device_name(row.device_id)
                loc = {
                    "interface": row.interface,
                    "vlan_id": None,
                    "bridge": None,
                    "device": device_name,
                    "device_id": str(row.device_id),
                    "source": row.source,
                    "first_seen": _iso(row.first_seen),
                    "last_seen": _iso(row.last_seen),
                }
                location_events.append((row.last_seen, loc))

        access: Optional[AccessPath] = None
        olt_out = []
        for i, row in enumerate(olt_rows):
            sources.add(row.source)
            device_name = self._device_name(row.device_id)
            olt_out.append(
                {
                    "ont_id": row.ont_id,
                    "pon": row.pon,
                    "vlan_id": row.vlan_id,
                    "device": device_name,
                    "device_id": str(row.device_id),
                    "first_seen": _iso(row.first_seen),
                    "last_seen": _iso(row.last_seen),
                    "source": row.source,
                    "command": getattr(row, "command", None),
                }
            )
            timeline.append(
                {
                    "at": _iso(row.last_seen),
                    "kind": "olt_mac",
                    "device": device_name,
                    "device_id": str(row.device_id),
                    "interface": row.pon,
                    "ip": None,
                    "ont_id": row.ont_id,
                    "source": row.source,
                    "command": getattr(row, "command", None),
                    "first_seen": _iso(row.first_seen),
                    "last_seen": _iso(row.last_seen),
                    "collection_run_id": str(row.collection_run_id) if row.collection_run_id else None,
                }
            )
            if i == 0 and row.ont_id:
                profile = None
                serial = None
                onu = self.db.scalar(
                    select(OltOnu).where(
                        OltOnu.tenant_id == tenant.id,
                        OltOnu.device_id == row.device_id,
                        OltOnu.ont_id == row.ont_id,
                    )
                )
                if onu:
                    profile = onu.profile_name
                    serial = onu.serial
                device = self.db.get(Device, row.device_id)
                access = AccessPath(
                    olt_device=device_name,
                    olt_device_id=str(device.id) if device else None,
                    pon=row.pon,
                    onu=row.ont_id,
                    vlan_id=row.vlan_id,
                    profile=profile,
                    serial=serial,
                )

        neighbor_out = []
        for row in neighbor_rows:
            sources.add(row.source)
            device_name = self._device_name(row.device_id)
            neighbor_out.append(
                {
                    "mac": row.mac,
                    "ip": row.ip_address,
                    "interface": row.interface,
                    "identity": row.identity,
                    "platform": row.platform,
                    "device": device_name,
                    "last_seen": _iso(row.last_seen),
                    "source": row.source,
                }
            )
            timeline.append(
                {
                    "at": _iso(row.last_seen),
                    "kind": "neighbor",
                    "device": device_name,
                    "device_id": str(row.device_id),
                    "interface": row.interface,
                    "ip": row.ip_address,
                    "identity": row.identity,
                    "source": row.source,
                    "first_seen": _iso(row.first_seen),
                    "last_seen": _iso(row.last_seen),
                    "collection_run_id": str(row.collection_run_id) if row.collection_run_id else None,
                }
            )

        current_ips, historical_ips = _split_latest(ip_events, key="ip")
        current_locations, historical_locations = _split_latest(
            location_events, key=lambda loc: (loc.get("device"), loc.get("interface"))
        )
        conflicts = _detect_conflicts(current_ips, current_locations)
        if olt_rows:
            max_olt = max(row.last_seen for row in olt_rows)
            current_onts = sorted(
                {row.ont_id for row in olt_rows if row.last_seen == max_olt and row.ont_id}
            )
            if len(current_onts) > 1:
                conflicts.append(
                    {
                        "kind": "ambiguous_onu",
                        "message": (
                            "Multiple ONUs observed this MAC at the latest timestamp; "
                            "not choosing one."
                        ),
                        "values": current_onts,
                    }
                )

        timeline.sort(key=lambda e: e.get("at") or "", reverse=True)

        return MacCorrelation(
            mac=mac,
            tenant=tenant.slug,
            first_seen=mac_row.first_seen if mac_row else None,
            last_seen=mac_row.last_seen if mac_row else None,
            current_ips=current_ips,
            historical_ips=historical_ips,
            current_locations=current_locations,
            historical_locations=historical_locations,
            hostname=hostname,
            dhcp=dhcp_out,
            arp=arp_out,
            fdb=fdb_out,
            neighbors=neighbor_out,
            access_path=access,
            olt_macs=olt_out,
            sources=sorted(sources),
            conflicts=conflicts,
            timeline=timeline,
        )


def _split_latest(
    events: list[tuple[datetime, dict[str, Any]]],
    key,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Items sharing the latest timestamp are current; older distinct keys are history."""
    if not events:
        return [], []
    max_ts = max(ts for ts, _ in events)
    current: list[dict[str, Any]] = []
    historical: list[dict[str, Any]] = []
    seen_current: set[Any] = set()
    seen_hist: set[Any] = set()

    def ident(item: dict[str, Any]) -> Any:
        if callable(key):
            return key(item)
        return item.get(key)

    for ts, item in sorted(events, key=lambda pair: pair[0], reverse=True):
        ident_key = ident(item)
        if ts == max_ts:
            if ident_key not in seen_current:
                current.append(item)
                seen_current.add(ident_key)
        else:
            if ident_key not in seen_current and ident_key not in seen_hist:
                historical.append(item)
                seen_hist.add(ident_key)
    return current, historical


def _detect_conflicts(
    current_ips: list[dict[str, Any]],
    current_locations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    ips = sorted({i["ip"] for i in current_ips if i.get("ip")})
    if len(ips) > 1:
        conflicts.append(
            {
                "kind": "ambiguous_ip",
                "message": "Multiple IPs observed at the latest timestamp; not choosing one.",
                "values": ips,
            }
        )
    devices = sorted({loc.get("device") for loc in current_locations if loc.get("device")})
    if len(devices) > 1:
        conflicts.append(
            {
                "kind": "ambiguous_device",
                "message": "Multiple devices observed this MAC at the latest timestamp.",
                "values": devices,
            }
        )
    ifaces = sorted(
        {
            f"{loc.get('device')}:{loc.get('interface')}"
            for loc in current_locations
            if loc.get("interface")
        }
    )
    if len(ifaces) > 1:
        conflicts.append(
            {
                "kind": "ambiguous_location",
                "message": "Multiple device/interface pairs observed at the latest timestamp.",
                "values": ifaces,
            }
        )
    return conflicts
