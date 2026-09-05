"""Persist normalized collector results with temporal upserts. Tenant-scoped.

History is preserved: upserts update last_seen on the matching observation key
and insert a new row when the key changes (e.g. MAC moves interface or IP).
Absence of a row in a later run is not treated as proof of absence — rows are
never deleted here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    ArpObservation,
    CollectionRun,
    Device,
    DhcpLease,
    Interface,
    InventoryNodeObservation,
    IpAddress,
    MacAddress,
    MacObservation,
    NeighborObservation,
    OltMacObservation,
    OltOnu,
    TopologyObservation,
)
from app.services.policy import apply_policy, load_policy
from collectors.common.transport import sanitize_error
from collectors.common.types import CollectorResult


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    """Normalize DB/SQLite naive datetimes for comparison."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class IngestService:
    def __init__(self, db: Session):
        self.db = db
        self._mac_rows: dict[tuple[UUID, str], MacAddress] = {}
        self._ip_rows: dict[tuple[UUID, str], IpAddress] = {}

    def start_run(
        self,
        *,
        tenant_id: UUID,
        collector_type: str,
        device_id: Optional[UUID] = None,
        site_id: Optional[UUID] = None,
        collector_version: Optional[str] = None,
    ) -> CollectionRun:
        if site_id is None and device_id is not None:
            device = self.db.get(Device, device_id)
            if device is not None and device.tenant_id == tenant_id:
                site_id = device.site_id
        run = CollectionRun(
            tenant_id=tenant_id,
            device_id=device_id,
            site_id=site_id,
            collector_type=collector_type,
            collector_version=collector_version,
            completeness="unknown",
            status="running",
            started_at=utcnow(),
        )
        self.db.add(run)
        self.db.flush()
        return run

    def finish_run(
        self,
        run: CollectionRun,
        *,
        status: str,
        seen: int = 0,
        created: int = 0,
        updated: int = 0,
        excluded: int = 0,
        parse_failures: int = 0,
        error: Optional[str] = None,
        completeness: Optional[str] = None,
        commands_ok: int = 0,
        commands_failed: int = 0,
        collector_version: Optional[str] = None,
    ) -> CollectionRun:
        run.status = status
        run.finished_at = utcnow()
        run.records_seen = seen
        run.records_created = created
        run.records_updated = updated
        run.records_excluded = excluded
        run.parse_failures = parse_failures
        run.error_summary = sanitize_error(error) if error else None
        if completeness is not None:
            run.completeness = completeness
        run.commands_ok = commands_ok
        run.commands_failed = commands_failed
        if collector_version:
            run.collector_version = collector_version
        self.db.add(run)
        return run

    def ingest_result(
        self,
        *,
        tenant_id: UUID,
        device_id: UUID,
        result: CollectorResult,
        run: Optional[CollectionRun] = None,
    ) -> dict[str, int]:
        created = updated = 0
        seen = 0
        run_id = run.id if run else None
        self._mac_rows = {}
        self._ip_rows = {}

        device = self.db.get(Device, device_id)
        if device is not None and device.tenant_id == tenant_id:
            rules = load_policy(self.db, tenant_id, device)
        else:
            rules = load_policy(self.db, tenant_id, None)
        result, excluded = apply_policy(result, rules)

        if result.identity:
            self._apply_identity(tenant_id, device_id, result.identity)

        for node in result.inventory_nodes:
            seen += 1
            if node.mac:
                self._touch_mac(tenant_id, node.mac, node.observed_at)
            if node.ip_address:
                self._touch_ip(tenant_id, node.ip_address, node.observed_at)
            c, u = self._upsert_inventory(tenant_id, device_id, node, run_id)
            created += c
            updated += u
        if result.inventory_nodes:
            self.db.flush()

        for iface in result.interfaces:
            seen += 1
            owner_id = device_id
            owner_ref = getattr(iface, "owner_source_id", None)
            if owner_ref:
                owner = self._device_by_source_ref(tenant_id, owner_ref)
                if owner is not None:
                    owner_id = owner.id
            c, u = self._upsert_interface(tenant_id, owner_id, iface)
            created += c
            updated += u

        for lease in result.dhcp:
            seen += 1
            self._touch_mac(tenant_id, lease.mac, lease.observed_at)
            self._touch_ip(tenant_id, lease.ip_address, lease.observed_at)
            c, u = self._upsert_dhcp(tenant_id, device_id, lease, run_id)
            created += c
            updated += u

        for arp in result.arp:
            seen += 1
            self._touch_mac(tenant_id, arp.mac, arp.observed_at)
            self._touch_ip(tenant_id, arp.ip_address, arp.observed_at)
            c, u = self._upsert_arp(tenant_id, device_id, arp, run_id)
            created += c
            updated += u

        for fdb in result.fdb:
            seen += 1
            self._touch_mac(tenant_id, fdb.mac, fdb.observed_at)
            c, u = self._upsert_fdb(tenant_id, device_id, fdb, run_id)
            created += c
            updated += u

        for neighbor in result.neighbors:
            seen += 1
            if neighbor.mac:
                self._touch_mac(tenant_id, neighbor.mac, neighbor.observed_at)
            if neighbor.ip_address:
                self._touch_ip(tenant_id, neighbor.ip_address, neighbor.observed_at)
            c, u = self._upsert_neighbor(tenant_id, device_id, neighbor, run_id)
            created += c
            updated += u

        for link in result.topology_links:
            seen += 1
            if link.remote_mac:
                self._touch_mac(tenant_id, link.remote_mac, link.observed_at)
            if link.remote_ip:
                self._touch_ip(tenant_id, link.remote_ip, link.observed_at)
            c, u = self._upsert_topology(tenant_id, device_id, link, run_id)
            created += c
            updated += u

        for onu in result.onus:
            seen += 1
            c, u = self._upsert_onu(tenant_id, device_id, onu)
            created += c
            updated += u

        for om in result.olt_macs:
            seen += 1
            self._touch_mac(tenant_id, om.mac, om.observed_at)
            c, u = self._upsert_olt_mac(tenant_id, device_id, om, run_id)
            created += c
            updated += u

        self.db.flush()
        return {"seen": seen, "created": created, "updated": updated, "excluded": excluded}

    def _apply_identity(self, tenant_id: UUID, device_id: UUID, identity) -> None:
        device = self.db.get(Device, device_id)
        if device is None or device.tenant_id != tenant_id:
            return
        if identity.name:
            device.last_identity = identity.name
        if identity.version:
            device.last_version = identity.version
        device.last_observed_at = identity.observed_at
        self.db.add(device)

    def _touch_mac(self, tenant_id: UUID, mac: str, when: datetime) -> None:
        key = (tenant_id, mac)
        row = self._mac_rows.get(key)
        if row is None:
            row = self.db.scalar(
                select(MacAddress).where(MacAddress.tenant_id == tenant_id, MacAddress.mac == mac)
            )
        if row is None:
            row = MacAddress(tenant_id=tenant_id, mac=mac, first_seen=when, last_seen=when)
            self.db.add(row)
        elif _as_utc(when) > _as_utc(row.last_seen):
            row.last_seen = when
            self.db.add(row)
        self._mac_rows[key] = row

    def _touch_ip(self, tenant_id: UUID, address: str, when: datetime) -> None:
        key = (tenant_id, address)
        row = self._ip_rows.get(key)
        if row is None:
            row = self.db.scalar(
                select(IpAddress).where(
                    IpAddress.tenant_id == tenant_id, IpAddress.address == address
                )
            )
        if row is None:
            row = IpAddress(tenant_id=tenant_id, address=address, first_seen=when, last_seen=when)
            self.db.add(row)
        elif _as_utc(when) > _as_utc(row.last_seen):
            row.last_seen = when
            self.db.add(row)
        self._ip_rows[key] = row

    def _upsert_interface(self, tenant_id, device_id, iface) -> tuple[int, int]:
        row = self.db.scalar(
            select(Interface).where(
                Interface.device_id == device_id,
                Interface.name == iface.name,
            )
        )
        if row is None:
            self.db.add(
                Interface(
                    tenant_id=tenant_id,
                    device_id=device_id,
                    name=iface.name,
                    if_type=iface.if_type,
                    admin_status=iface.admin_status,
                    oper_status=iface.oper_status,
                    mac=iface.mac,
                    first_seen=iface.observed_at,
                    last_seen=iface.observed_at,
                    observed_at=iface.observed_at,
                )
            )
            return 1, 0
        row.if_type = iface.if_type or row.if_type
        row.admin_status = iface.admin_status or row.admin_status
        row.oper_status = iface.oper_status or row.oper_status
        row.mac = iface.mac or row.mac
        row.last_seen = iface.observed_at
        row.observed_at = iface.observed_at
        self.db.add(row)
        return 0, 1

    def _upsert_dhcp(self, tenant_id, device_id, lease, run_id) -> tuple[int, int]:
        row = self.db.scalar(
            select(DhcpLease).where(
                DhcpLease.tenant_id == tenant_id,
                DhcpLease.device_id == device_id,
                DhcpLease.mac == lease.mac,
                DhcpLease.ip_address == lease.ip_address,
            )
        )
        if row is None:
            self.db.add(
                DhcpLease(
                    tenant_id=tenant_id,
                    device_id=device_id,
                    mac=lease.mac,
                    ip_address=lease.ip_address,
                    hostname=lease.hostname,
                    server=lease.server,
                    status=lease.status,
                    comment=lease.comment,
                    lease_kind=getattr(lease, "lease_kind", None),
                    client_id=getattr(lease, "client_id", None),
                    reported_last_seen=getattr(lease, "reported_last_seen", None),
                    first_seen=lease.observed_at,
                    last_seen=lease.observed_at,
                    observed_at=lease.observed_at,
                    source=lease.source,
                    collection_run_id=run_id,
                )
            )
            return 1, 0
        row.hostname = lease.hostname or row.hostname
        row.server = lease.server or row.server
        row.status = lease.status or row.status
        row.comment = lease.comment or row.comment
        if getattr(lease, "lease_kind", None):
            row.lease_kind = lease.lease_kind
        if getattr(lease, "client_id", None):
            row.client_id = lease.client_id
        if getattr(lease, "reported_last_seen", None):
            row.reported_last_seen = lease.reported_last_seen
        row.last_seen = lease.observed_at
        row.observed_at = lease.observed_at
        row.collection_run_id = run_id
        self.db.add(row)
        return 0, 1

    def _upsert_arp(self, tenant_id, device_id, arp, run_id) -> tuple[int, int]:
        # Key includes interface so a MAC moving ports keeps the prior ARP row.
        row = self.db.scalar(
            select(ArpObservation).where(
                ArpObservation.tenant_id == tenant_id,
                ArpObservation.device_id == device_id,
                ArpObservation.mac == arp.mac,
                ArpObservation.ip_address == arp.ip_address,
                ArpObservation.interface == arp.interface,
            )
        )
        if row is None:
            self.db.add(
                ArpObservation(
                    tenant_id=tenant_id,
                    device_id=device_id,
                    mac=arp.mac,
                    ip_address=arp.ip_address,
                    interface=arp.interface,
                    first_seen=arp.observed_at,
                    last_seen=arp.observed_at,
                    observed_at=arp.observed_at,
                    source=arp.source,
                    collection_run_id=run_id,
                )
            )
            return 1, 0
        row.last_seen = arp.observed_at
        row.observed_at = arp.observed_at
        row.collection_run_id = run_id
        self.db.add(row)
        return 0, 1

    def _upsert_fdb(self, tenant_id, device_id, fdb, run_id) -> tuple[int, int]:
        row = self.db.scalar(
            select(MacObservation).where(
                MacObservation.tenant_id == tenant_id,
                MacObservation.device_id == device_id,
                MacObservation.mac == fdb.mac,
                MacObservation.interface == fdb.interface,
            )
        )
        if row is None:
            self.db.add(
                MacObservation(
                    tenant_id=tenant_id,
                    device_id=device_id,
                    mac=fdb.mac,
                    interface=fdb.interface,
                    vlan_id=fdb.vlan_id,
                    bridge=fdb.bridge,
                    first_seen=fdb.observed_at,
                    last_seen=fdb.observed_at,
                    observed_at=fdb.observed_at,
                    source=fdb.source,
                    confidence=fdb.confidence,
                    collection_run_id=run_id,
                )
            )
            return 1, 0
        row.vlan_id = fdb.vlan_id if fdb.vlan_id is not None else row.vlan_id
        row.bridge = fdb.bridge or row.bridge
        row.last_seen = fdb.observed_at
        row.observed_at = fdb.observed_at
        row.confidence = fdb.confidence
        row.collection_run_id = run_id
        self.db.add(row)
        return 0, 1

    def _upsert_neighbor(self, tenant_id, device_id, neighbor, run_id) -> tuple[int, int]:
        row = self.db.scalar(
            select(NeighborObservation).where(
                NeighborObservation.tenant_id == tenant_id,
                NeighborObservation.device_id == device_id,
                NeighborObservation.mac == neighbor.mac,
                NeighborObservation.ip_address == neighbor.ip_address,
                NeighborObservation.interface == neighbor.interface,
                NeighborObservation.identity == neighbor.identity,
                NeighborObservation.protocol == getattr(neighbor, "protocol", None),
            )
        )
        if row is None:
            self.db.add(
                NeighborObservation(
                    tenant_id=tenant_id,
                    device_id=device_id,
                    mac=neighbor.mac,
                    ip_address=neighbor.ip_address,
                    interface=neighbor.interface,
                    remote_interface=neighbor.remote_interface,
                    identity=neighbor.identity,
                    platform=neighbor.platform,
                    protocol=getattr(neighbor, "protocol", None),
                    version=getattr(neighbor, "version", None),
                    first_seen=neighbor.observed_at,
                    last_seen=neighbor.observed_at,
                    observed_at=neighbor.observed_at,
                    source=neighbor.source,
                    collection_run_id=run_id,
                )
            )
            return 1, 0
        row.platform = neighbor.platform or row.platform
        row.remote_interface = neighbor.remote_interface or row.remote_interface
        row.protocol = getattr(neighbor, "protocol", None) or row.protocol
        row.version = getattr(neighbor, "version", None) or row.version
        row.last_seen = neighbor.observed_at
        row.observed_at = neighbor.observed_at
        row.collection_run_id = run_id
        self.db.add(row)
        return 0, 1

    def _upsert_onu(self, tenant_id, device_id, onu) -> tuple[int, int]:
        row = self.db.scalar(
            select(OltOnu).where(
                OltOnu.tenant_id == tenant_id,
                OltOnu.device_id == device_id,
                OltOnu.ont_id == onu.ont_id,
            )
        )
        if row is None:
            self.db.add(
                OltOnu(
                    tenant_id=tenant_id,
                    device_id=device_id,
                    ont_id=onu.ont_id,
                    pon=onu.pon,
                    serial=onu.serial,
                    status=onu.status,
                    profile_name=onu.profile_name,
                    first_seen=onu.observed_at,
                    last_seen=onu.observed_at,
                )
            )
            return 1, 0
        row.pon = onu.pon or row.pon
        row.serial = onu.serial or row.serial
        row.status = onu.status or row.status
        row.profile_name = onu.profile_name or row.profile_name
        row.last_seen = onu.observed_at
        self.db.add(row)
        return 0, 1

    def _upsert_olt_mac(self, tenant_id, device_id, om, run_id) -> tuple[int, int]:
        row = self.db.scalar(
            select(OltMacObservation).where(
                OltMacObservation.tenant_id == tenant_id,
                OltMacObservation.device_id == device_id,
                OltMacObservation.mac == om.mac,
                OltMacObservation.ont_id == om.ont_id,
                OltMacObservation.pon == om.pon,
                OltMacObservation.vlan_id == om.vlan_id,
                OltMacObservation.gem == om.gem,
            )
        )
        if row is None:
            self.db.add(
                OltMacObservation(
                    tenant_id=tenant_id,
                    device_id=device_id,
                    mac=om.mac,
                    ont_id=om.ont_id,
                    pon=om.pon,
                    vlan_id=om.vlan_id,
                    gem=om.gem,
                    first_seen=om.observed_at,
                    last_seen=om.observed_at,
                    observed_at=om.observed_at,
                    source=om.source,
                    command=getattr(om, "command", None),
                    collection_run_id=run_id,
                )
            )
            return 1, 0
        row.pon = om.pon or row.pon
        row.vlan_id = om.vlan_id if om.vlan_id is not None else row.vlan_id
        row.gem = om.gem or row.gem
        if getattr(om, "command", None):
            row.command = om.command
        row.source = om.source or row.source
        row.last_seen = om.observed_at
        row.observed_at = om.observed_at
        row.collection_run_id = run_id
        self.db.add(row)
        return 0, 1

    def _device_by_source_ref(self, tenant_id, source_ref: str) -> Optional[Device]:
        return self.db.scalar(
            select(Device).where(Device.tenant_id == tenant_id, Device.source_ref == source_ref)
        )

    def _devices_for_mac(self, tenant_id, mac: str) -> list[Device]:
        ids: set = set()
        for device in self.db.scalars(
            select(Device).where(Device.tenant_id == tenant_id, Device.chassis_mac == mac)
        ):
            ids.add(device.id)
        for iface in self.db.scalars(
            select(Interface).where(Interface.tenant_id == tenant_id, Interface.mac == mac)
        ):
            ids.add(iface.device_id)
        found: list[Device] = []
        for did in ids:
            device = self.db.get(Device, did)
            if device is not None and device.tenant_id == tenant_id:
                found.append(device)
        return found

    def _unique_device_name(self, site_id, preferred: str) -> str:
        name = (preferred or "unifi-node")[:128]
        exists = self.db.scalar(select(Device).where(Device.site_id == site_id, Device.name == name))
        if exists is None:
            return name
        for i in range(2, 50):
            candidate = f"{name[:120]}-{i}"
            exists = self.db.scalar(
                select(Device).where(Device.site_id == site_id, Device.name == candidate)
            )
            if exists is None:
                return candidate
        return f"{name[:100]}-{str(site_id)[:8]}"

    def _match_or_create_inventory_device(self, tenant_id, controller_id, node) -> Optional[Device]:
        controller = self.db.get(Device, controller_id)
        if controller is None or controller.tenant_id != tenant_id:
            return None
        if node.source_id:
            by_ref = self._device_by_source_ref(tenant_id, node.source_id)
            if by_ref is not None:
                self._apply_inventory_identity(by_ref, node)
                return by_ref
        if node.mac:
            matches = self._devices_for_mac(tenant_id, node.mac)
            if len(matches) == 1:
                device = matches[0]
                if node.source_id and not device.source_ref:
                    device.source_ref = node.source_id
                self._apply_inventory_identity(device, node)
                return device
            if len(matches) > 1:
                return None
        preferred = node.name or (f"unifi-{node.mac}" if node.mac else None) or node.source_id or "unifi-node"
        device = Device(
            tenant_id=tenant_id,
            site_id=controller.site_id,
            name=self._unique_device_name(controller.site_id, preferred),
            device_type="unifi",
            vendor="Ubiquiti",
            model=node.model,
            enabled=False,
            chassis_mac=node.mac,
            source_ref=node.source_id,
            last_identity=node.name,
            last_version=node.firmware,
            last_observed_at=node.observed_at,
        )
        self.db.add(device)
        self.db.flush()
        return device

    def _apply_inventory_identity(self, device: Device, node) -> None:
        if node.mac and not device.chassis_mac:
            device.chassis_mac = node.mac
        if node.source_id and not device.source_ref:
            device.source_ref = node.source_id
        if node.model:
            device.model = node.model
        if node.name:
            device.last_identity = node.name
        if node.firmware:
            device.last_version = node.firmware
        device.last_observed_at = node.observed_at
        self.db.add(device)

    def _upsert_inventory(self, tenant_id, controller_id, node, run_id) -> tuple[int, int]:
        observed = self._match_or_create_inventory_device(tenant_id, controller_id, node)
        filters = [
            InventoryNodeObservation.tenant_id == tenant_id,
            InventoryNodeObservation.controller_device_id == controller_id,
        ]
        if node.source_id:
            filters.append(InventoryNodeObservation.source_id == node.source_id)
        elif node.mac:
            filters.append(InventoryNodeObservation.mac == node.mac)
        else:
            filters.append(InventoryNodeObservation.name == node.name)
        row = self.db.scalar(select(InventoryNodeObservation).where(*filters))
        if row is None:
            self.db.add(
                InventoryNodeObservation(
                    tenant_id=tenant_id,
                    controller_device_id=controller_id,
                    observed_device_id=observed.id if observed else None,
                    source_id=node.source_id,
                    name=node.name,
                    mac=node.mac,
                    ip_address=node.ip_address,
                    model=node.model,
                    category=node.category,
                    state=node.state,
                    firmware=node.firmware,
                    uplink_source_id=node.uplink_source_id,
                    first_seen=node.observed_at,
                    last_seen=node.observed_at,
                    observed_at=node.observed_at,
                    source=node.source,
                    collection_run_id=run_id,
                )
            )
            return 1, 0
        row.observed_device_id = observed.id if observed else row.observed_device_id
        row.name = node.name or row.name
        row.mac = node.mac or row.mac
        row.ip_address = node.ip_address or row.ip_address
        row.model = node.model or row.model
        row.category = node.category or row.category
        row.state = node.state or row.state
        row.firmware = node.firmware or row.firmware
        row.uplink_source_id = node.uplink_source_id or row.uplink_source_id
        row.last_seen = node.observed_at
        row.observed_at = node.observed_at
        row.collection_run_id = run_id
        self.db.add(row)
        return 0, 1

    def _resolve_local_device(self, tenant_id, collector_id, link) -> Device:
        if getattr(link, "local_source_id", None):
            found = self._device_by_source_ref(tenant_id, link.local_source_id)
            if found is not None:
                return found
        if getattr(link, "local_mac", None):
            matches = self._devices_for_mac(tenant_id, link.local_mac)
            if len(matches) == 1:
                return matches[0]
        device = self.db.get(Device, collector_id)
        if device is None:
            raise LookupError("collector device missing")
        return device

    def _hint_remote_device_id(self, tenant_id, link):
        if link.remote_mac:
            matches = self._devices_for_mac(tenant_id, link.remote_mac)
            if len(matches) == 1:
                return matches[0].id
            return None
        if link.remote_source_id:
            found = self._device_by_source_ref(tenant_id, link.remote_source_id)
            return found.id if found else None
        return None

    def _upsert_topology(self, tenant_id, collector_id, link, run_id) -> tuple[int, int]:
        local = self._resolve_local_device(tenant_id, collector_id, link)
        filters = [
            TopologyObservation.tenant_id == tenant_id,
            TopologyObservation.local_device_id == local.id,
            TopologyObservation.local_interface == link.local_interface,
            TopologyObservation.source == link.source,
            TopologyObservation.protocol == link.protocol,
        ]
        if link.remote_mac:
            filters.append(TopologyObservation.remote_mac == link.remote_mac)
        elif link.remote_source_id:
            filters.append(TopologyObservation.remote_source_id == link.remote_source_id)
        else:
            filters.append(TopologyObservation.remote_identity == link.remote_identity)
            filters.append(TopologyObservation.remote_mac.is_(None))
        row = self.db.scalar(select(TopologyObservation).where(*filters))
        remote_hint = self._hint_remote_device_id(tenant_id, link)
        if row is None:
            self.db.add(
                TopologyObservation(
                    tenant_id=tenant_id,
                    site_id=local.site_id,
                    local_device_id=local.id,
                    local_interface=link.local_interface,
                    remote_device_id=remote_hint,
                    remote_interface=link.remote_interface,
                    remote_identity=link.remote_identity,
                    remote_mac=link.remote_mac,
                    remote_ip=link.remote_ip,
                    remote_source_id=link.remote_source_id,
                    protocol=link.protocol,
                    source=link.source,
                    first_seen=link.observed_at,
                    last_seen=link.observed_at,
                    observed_at=link.observed_at,
                    collection_run_id=run_id,
                )
            )
            return 1, 0
        if remote_hint:
            row.remote_device_id = remote_hint
        row.remote_interface = link.remote_interface or row.remote_interface
        row.remote_identity = link.remote_identity or row.remote_identity
        row.remote_ip = link.remote_ip or row.remote_ip
        row.remote_source_id = link.remote_source_id or row.remote_source_id
        row.last_seen = link.observed_at
        row.observed_at = link.observed_at
        row.collection_run_id = run_id
        self.db.add(row)
        return 0, 1
