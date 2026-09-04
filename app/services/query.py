"""Tenant-scoped query helpers for API and MCP."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.ip import normalize_ip
from app.core.mac import normalize_mac
from app.correlation.engine import CorrelationEngine, MacCorrelation
from app.models.entities import CollectionRun, Device, IpAddress, MacAddress, Tenant


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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

    def list_devices(
        self, tenant_slug: str, limit: int = 100, offset: int = 0
    ) -> list[Device]:
        tenant = self.require_tenant(tenant_slug)
        return list(
            self.db.scalars(
                select(Device)
                .where(Device.tenant_id == tenant.id)
                .order_by(Device.name)
                .offset(offset)
                .limit(limit)
            )
        )

    def get_device(self, tenant_slug: str, device_id: UUID) -> Device | None:
        tenant = self.require_tenant(tenant_slug)
        device = self.db.get(Device, device_id)
        if device is None or device.tenant_id != tenant.id:
            return None
        return device

    def list_macs(self, tenant_slug: str, limit: int = 100, offset: int = 0) -> list[MacAddress]:
        tenant = self.require_tenant(tenant_slug)
        return list(
            self.db.scalars(
                select(MacAddress)
                .where(MacAddress.tenant_id == tenant.id)
                .order_by(MacAddress.last_seen.desc())
                .offset(offset)
                .limit(limit)
            )
        )

    def find_mac(self, tenant_slug: str, mac: str) -> MacCorrelation | None:
        return self.corr.correlate_mac(tenant_slug, mac)

    def find_ip(self, tenant_slug: str, ip: str) -> dict:
        tenant = self.require_tenant(tenant_slug)
        try:
            ip = normalize_ip(ip)
        except ValueError:
            ip = ip.strip()
        ip_row = self.db.scalar(
            select(IpAddress).where(IpAddress.tenant_id == tenant.id, IpAddress.address == ip)
        )
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
        conflicts: list[dict] = []
        if len(macs) > 1:
            conflicts.append(
                {
                    "kind": "ambiguous_mac",
                    "message": "Multiple MACs observed for this IP; not choosing one.",
                    "values": macs,
                }
            )
        return {
            "ip": ip,
            "tenant": tenant.slug,
            "first_seen": ip_row.first_seen.isoformat() if ip_row else None,
            "last_seen": ip_row.last_seen.isoformat() if ip_row else None,
            "macs": [c.to_dict() for c in correlated if c],
            "conflicts": conflicts,
        }

    def collection_runs(
        self, tenant_slug: str, limit: int = 50, offset: int = 0
    ) -> list[CollectionRun]:
        tenant = self.require_tenant(tenant_slug)
        return list(
            self.db.scalars(
                select(CollectionRun)
                .where(CollectionRun.tenant_id == tenant.id)
                .order_by(CollectionRun.started_at.desc())
                .offset(offset)
                .limit(limit)
            )
        )

    def collection_status(self, tenant_slug: str, limit: int = 50) -> dict:
        tenant = self.require_tenant(tenant_slug)
        runs = self.collection_runs(tenant_slug, limit=limit)
        now = _utcnow()
        items = []
        for r in runs:
            finished = r.finished_at
            freshness = None
            if finished is not None:
                if finished.tzinfo is None:
                    finished = finished.replace(tzinfo=timezone.utc)
                freshness = int((now - finished).total_seconds())
            items.append(
                {
                    "id": str(r.id),
                    "tenant": tenant.slug,
                    "site_id": str(r.site_id) if r.site_id else None,
                    "device_id": str(r.device_id) if r.device_id else None,
                    "collector_type": r.collector_type,
                    "collector_version": r.collector_version,
                    "status": r.status,
                    "completeness": r.completeness,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                    "records_seen": r.records_seen,
                    "records_created": r.records_created,
                    "records_updated": r.records_updated,
                    "records_excluded": r.records_excluded,
                    "parse_failures": r.parse_failures,
                    "commands_ok": r.commands_ok,
                    "commands_failed": r.commands_failed,
                    "error_summary": r.error_summary,
                    "freshness_seconds": freshness,
                }
            )
        last_ok = self.db.scalar(
            select(func.max(CollectionRun.finished_at)).where(
                CollectionRun.tenant_id == tenant.id,
                CollectionRun.status.in_(("success", "ok", "partial")),
            )
        )
        return {
            "tenant": tenant.slug,
            "runs": items,
            "last_successful_at": last_ok.isoformat() if last_ok else None,
        }

    def mac_history(self, tenant_slug: str, mac: str) -> dict:
        corr = self.find_mac(tenant_slug, mac)
        if corr is None:
            return {"mac": normalize_mac(mac), "tenant": tenant_slug, "found": False}
        found = any(
            [corr.dhcp, corr.arp, corr.fdb, corr.olt_macs, corr.neighbors, corr.first_seen]
        )
        return {
            "mac": corr.mac,
            "tenant": corr.tenant,
            "found": found,
            "first_seen": corr.first_seen.isoformat() if corr.first_seen else None,
            "last_seen": corr.last_seen.isoformat() if corr.last_seen else None,
            "ip_changes": corr.historical_ips,
            "current_ips": corr.current_ips,
            "current_locations": corr.current_locations,
            "historical_locations": corr.historical_locations,
            "fdb": corr.fdb,
            "olt": corr.olt_macs,
            "neighbors": corr.neighbors,
            "conflicts": corr.conflicts,
            "timeline": corr.timeline,
            "access_path": corr.access_path.__dict__ if corr.access_path else None,
            "sources": corr.sources,
        }
