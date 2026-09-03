"""Tenant-scoped query helpers for API and MCP."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.correlation.engine import CorrelationEngine, MacCorrelation
from app.core.mac import normalize_mac
from app.models.entities import CollectionRun, Device, IpAddress, MacAddress, Tenant


class QueryService:
    def __init__(self, db: Session):
        self.db = db
        self.corr = CorrelationEngine(db)

    def require_tenant(self, slug: str) -> Tenant:
        tenant = self.db.scalar(select(Tenant).where(Tenant.slug == slug))
        if tenant is None:
            raise LookupError(f"tenant not found: {slug}")
        return tenant

    def list_tenants(self) -> list[Tenant]:
        return list(self.db.scalars(select(Tenant).order_by(Tenant.slug)))

    def list_devices(self, tenant_slug: str) -> list[Device]:
        tenant = self.require_tenant(tenant_slug)
        return list(
            self.db.scalars(
                select(Device).where(Device.tenant_id == tenant.id).order_by(Device.name)
            )
        )

    def get_device(self, tenant_slug: str, device_id: UUID) -> Optional[Device]:
        tenant = self.require_tenant(tenant_slug)
        device = self.db.get(Device, device_id)
        if device is None or device.tenant_id != tenant.id:
            return None
        return device

    def list_macs(self, tenant_slug: str, limit: int = 100) -> list[MacAddress]:
        tenant = self.require_tenant(tenant_slug)
        return list(
            self.db.scalars(
                select(MacAddress)
                .where(MacAddress.tenant_id == tenant.id)
                .order_by(MacAddress.last_seen.desc())
                .limit(limit)
            )
        )

    def find_mac(self, tenant_slug: str, mac: str) -> Optional[MacCorrelation]:
        return self.corr.correlate_mac(tenant_slug, mac)

    def find_ip(self, tenant_slug: str, ip: str) -> dict:
        tenant = self.require_tenant(tenant_slug)
        ip_row = self.db.scalar(
            select(IpAddress).where(IpAddress.tenant_id == tenant.id, IpAddress.address == ip)
        )
        # Find latest DHCP/ARP by IP within tenant only
        from app.models.entities import ArpObservation, DhcpLease

        leases = list(
            self.db.scalars(
                select(DhcpLease)
                .where(DhcpLease.tenant_id == tenant.id, DhcpLease.ip_address == ip)
                .order_by(DhcpLease.last_seen.desc())
            )
        )
        arps = list(
            self.db.scalars(
                select(ArpObservation)
                .where(ArpObservation.tenant_id == tenant.id, ArpObservation.ip_address == ip)
                .order_by(ArpObservation.last_seen.desc())
            )
        )
        macs = sorted({normalize_mac(r.mac) for r in leases + arps})
        correlated = [self.corr.correlate_mac(tenant_slug, m) for m in macs]
        return {
            "ip": ip,
            "tenant": tenant.slug,
            "first_seen": ip_row.first_seen.isoformat() if ip_row else None,
            "last_seen": ip_row.last_seen.isoformat() if ip_row else None,
            "macs": [c.to_dict() for c in correlated if c],
        }

    def collection_runs(self, tenant_slug: str, limit: int = 50) -> list[CollectionRun]:
        tenant = self.require_tenant(tenant_slug)
        return list(
            self.db.scalars(
                select(CollectionRun)
                .where(CollectionRun.tenant_id == tenant.id)
                .order_by(CollectionRun.started_at.desc())
                .limit(limit)
            )
        )

    def mac_history(self, tenant_slug: str, mac: str) -> dict:
        corr = self.find_mac(tenant_slug, mac)
        if corr is None:
            return {"mac": normalize_mac(mac), "tenant": tenant_slug, "found": False}
        return {
            "mac": corr.mac,
            "tenant": corr.tenant,
            "found": True,
            "first_seen": corr.first_seen.isoformat() if corr.first_seen else None,
            "last_seen": corr.last_seen.isoformat() if corr.last_seen else None,
            "ip_changes": corr.historical_ips,
            "current_ips": corr.current_ips,
            "fdb": corr.fdb,
            "olt": corr.olt_macs,
            "access_path": corr.access_path.__dict__ if corr.access_path else None,
        }
