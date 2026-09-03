"""Persist normalized collector results with temporal upserts. Tenant-scoped."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    ArpObservation,
    CollectionRun,
    DhcpLease,
    IpAddress,
    MacAddress,
    MacObservation,
    OltMacObservation,
    OltOnu,
)
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

    def start_run(
        self,
        *,
        tenant_id: UUID,
        collector_type: str,
        device_id: Optional[UUID] = None,
    ) -> CollectionRun:
        run = CollectionRun(
            tenant_id=tenant_id,
            device_id=device_id,
            collector_type=collector_type,
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
    ) -> CollectionRun:
        run.status = status
        run.finished_at = utcnow()
        run.records_seen = seen
        run.records_created = created
        run.records_updated = updated
        run.error_summary = error
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

    def _touch_mac(self, tenant_id: UUID, mac: str, when: datetime) -> None:
        row = self.db.scalar(
            select(MacAddress).where(MacAddress.tenant_id == tenant_id, MacAddress.mac == mac)
        )
        if row is None:
            self.db.add(
                MacAddress(tenant_id=tenant_id, mac=mac, first_seen=when, last_seen=when)
            )
        else:
            if _as_utc(when) > _as_utc(row.last_seen):
                row.last_seen = when
            self.db.add(row)

    def _touch_ip(self, tenant_id: UUID, address: str, when: datetime) -> None:
        row = self.db.scalar(
            select(IpAddress).where(IpAddress.tenant_id == tenant_id, IpAddress.address == address)
        )
        if row is None:
            self.db.add(
                IpAddress(tenant_id=tenant_id, address=address, first_seen=when, last_seen=when)
            )
        else:
            if _as_utc(when) > _as_utc(row.last_seen):
                row.last_seen = when
            self.db.add(row)

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
        row.last_seen = lease.observed_at
        row.observed_at = lease.observed_at
        row.collection_run_id = run_id
        self.db.add(row)
        return 0, 1

    def _upsert_arp(self, tenant_id, device_id, arp, run_id) -> tuple[int, int]:
        row = self.db.scalar(
            select(ArpObservation).where(
                ArpObservation.tenant_id == tenant_id,
                ArpObservation.device_id == device_id,
                ArpObservation.mac == arp.mac,
                ArpObservation.ip_address == arp.ip_address,
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
        row.interface = arp.interface or row.interface
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
                    collection_run_id=run_id,
                )
            )
            return 1, 0
        row.pon = om.pon or row.pon
        row.vlan_id = om.vlan_id if om.vlan_id is not None else row.vlan_id
        row.gem = om.gem or row.gem
        row.last_seen = om.observed_at
        row.observed_at = om.observed_at
        row.collection_run_id = run_id
        self.db.add(row)
        return 0, 1
