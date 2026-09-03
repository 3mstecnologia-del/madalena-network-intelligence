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
    IpAddress,
    MacAddress,
    MacObservation,
    NeighborObservation,
    OltMacObservation,
    OltOnu,
)
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

        if result.identity:
            self._apply_identity(tenant_id, device_id, result.identity)

        for iface in result.interfaces:
            seen += 1
            c, u = self._upsert_interface(tenant_id, device_id, iface)
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
        return {"seen": seen, "created": created, "updated": updated}

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
                    identity=neighbor.identity,
                    platform=neighbor.platform,
                    first_seen=neighbor.observed_at,
                    last_seen=neighbor.observed_at,
                    observed_at=neighbor.observed_at,
                    source=neighbor.source,
                    collection_run_id=run_id,
                )
            )
            return 1, 0
        row.platform = neighbor.platform or row.platform
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
