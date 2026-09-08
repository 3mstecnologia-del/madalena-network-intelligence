"""Tenant-scoped query helpers for API and MCP."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.ip import normalize_ip
from app.core.mac import normalize_mac
from app.correlation.engine import CorrelationEngine, MacCorrelation
from app.correlation.topology import TopologyCorrelator
from app.models.entities import (
    CollectionRun,
    Device,
    DeviceIdentifier,
    Interface,
    InterfaceObservation,
    OltMacObservation,
    PhysicalLink,
    LinkEvidence,
    IpAddress,
    MacAddress,
    Tenant,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class QueryService:
    def __init__(self, db: Session):
        self.db = db
        self.corr = CorrelationEngine(db)
        self.topology = TopologyCorrelator(db)

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

    def list_interfaces(
        self,
        tenant_slug: str,
        *,
        device_id: UUID | None = None,
        include_history: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        tenant = self.require_tenant(tenant_slug)
        q = select(Interface).where(Interface.tenant_id == tenant.id)
        if device_id is not None:
            q = q.where(Interface.device_id == device_id)
        rows = list(self.db.scalars(q.order_by(Interface.device_id, Interface.name).offset(offset).limit(limit)))
        total = self.db.scalar(
            select(func.count()).select_from(Interface).where(
                Interface.tenant_id == tenant.id,
                *( [Interface.device_id == device_id] if device_id is not None else [] ),
            )
        ) or 0
        items = []
        for iface in rows:
            history_rows = list(
                self.db.scalars(
                    select(InterfaceObservation).where(
                        InterfaceObservation.tenant_id == tenant.id,
                        InterfaceObservation.interface_id == iface.id,
                    ).order_by(InterfaceObservation.observed_at.desc())
                )
            )
            items.append(
                {
                    "id": str(iface.id),
                    "tenant_id": str(iface.tenant_id),
                    "device_id": str(iface.device_id),
                    "name": iface.name,
                    "if_type": iface.if_type,
                    "admin_status": iface.admin_status,
                    "oper_status": iface.oper_status,
                    "mac": iface.mac,
                    "description": iface.description,
                    "source": iface.source,
                    "source_identifiers": iface.source_identifiers or {},
                    "first_seen": iface.first_seen.isoformat() if iface.first_seen else None,
                    "last_seen": iface.last_seen.isoformat() if iface.last_seen else None,
                    "observed_at": iface.observed_at.isoformat() if iface.observed_at else None,
                    "device": {
                        "id": str(iface.device.id) if iface.device else None,
                        "name": iface.device.name if iface.device else None,
                        "device_type": iface.device.device_type if iface.device else None,
                    },
                    "history": [
                        {
                            "id": str(h.id),
                            "observed_at": h.observed_at.isoformat() if h.observed_at else None,
                            "source": h.source,
                            "name": h.name,
                            "description": h.description,
                            "if_type": h.if_type,
                            "admin_status": h.admin_status,
                            "oper_status": h.oper_status,
                            "mac": h.mac,
                            "source_identifiers": h.source_identifiers or {},
                            "evidence": h.evidence or {},
                            "collection_run_id": str(h.collection_run_id) if h.collection_run_id else None,
                        }
                        for h in history_rows
                    ] if include_history else [],
                }
            )
        return {"tenant": tenant.slug, "total": int(total), "items": items, "limit": limit, "offset": offset}

    def list_physical_links(
        self,
        tenant_slug: str,
        *,
        device_id: UUID | None = None,
        include_history: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        tenant = self.require_tenant(tenant_slug)
        q = select(PhysicalLink).where(PhysicalLink.tenant_id == tenant.id)
        if device_id is not None:
            q = q.where((PhysicalLink.device_a_id == device_id) | (PhysicalLink.device_b_id == device_id))
        rows = list(self.db.scalars(q.order_by(PhysicalLink.last_seen.desc()).offset(offset).limit(limit)))
        total = self.db.scalar(
            select(func.count()).select_from(PhysicalLink).where(
                PhysicalLink.tenant_id == tenant.id,
                *([
                    (PhysicalLink.device_a_id == device_id) | (PhysicalLink.device_b_id == device_id)
                ] if device_id is not None else []),
            )
        ) or 0
        items = []
        for link in rows:
            evidences = list(
                self.db.scalars(
                    select(LinkEvidence).where(LinkEvidence.physical_link_id == link.id).order_by(LinkEvidence.observed_at.desc())
                )
            )
            da = self.db.get(Device, link.device_a_id)
            db = self.db.get(Device, link.device_b_id)
            ia = self.db.get(Interface, link.interface_a_id) if link.interface_a_id else None
            ib = self.db.get(Interface, link.interface_b_id) if link.interface_b_id else None
            items.append(
                {
                    "id": str(link.id),
                    "device_a": {"id": str(da.id) if da else None, "name": da.name if da else None, "device_type": da.device_type if da else None},
                    "device_b": {"id": str(db.id) if db else None, "name": db.name if db else None, "device_type": db.device_type if db else None},
                    "interface_a": {"id": str(ia.id) if ia else None, "name": ia.name if ia else None, "description": ia.description if ia else None},
                    "interface_b": {"id": str(ib.id) if ib else None, "name": ib.name if ib else None, "description": ib.description if ib else None},
                    "directly_observed": link.directly_observed,
                    "inferred": link.inferred,
                    "confidence": link.confidence,
                    "first_seen": link.first_seen.isoformat() if link.first_seen else None,
                    "last_seen": link.last_seen.isoformat() if link.last_seen else None,
                    "sources": sorted({e.source for e in evidences}),
                    "evidence": [
                        {
                            "source": e.source,
                            "protocol": e.protocol,
                            "observed_at": e.observed_at.isoformat() if e.observed_at else None,
                            "directly_observed": e.directly_observed,
                            "inferred": e.inferred,
                            "confidence": e.confidence,
                            "collection_run_id": str(e.collection_run_id) if e.collection_run_id else None,
                            "evidence": e.evidence or {},
                        }
                        for e in evidences
                    ] if include_history or True else [],
                }
            )
        return {"tenant": tenant.slug, "total": int(total), "items": items, "limit": limit, "offset": offset}

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

    def device_neighbors(
        self, tenant_slug: str, device_id: UUID, limit: int = 50, offset: int = 0
    ) -> dict:
        return self.topology.device_neighbors(
            tenant_slug, device_id, limit=limit, offset=offset
        )

    def device_links(
        self,
        tenant_slug: str,
        device_id: UUID,
        *,
        include_history: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        return self.topology.topology(
            tenant_slug,
            device_id=device_id,
            include_history=include_history,
            limit=limit,
            offset=offset,
        )

    def get_topology(
        self,
        tenant_slug: str,
        *,
        include_history: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        return self.topology.topology(
            tenant_slug,
            include_history=include_history,
            limit=limit,
            offset=offset,
        )

    # ---- OLT MAC -> device location correlation -----------------------------

    def _device_ids_for_mac(self, tenant_id, mac: str) -> set:
        """Devices whose trustworthy identity includes this MAC.

        Resolution order mirrors the correlation engine: chassis_mac, interface
        MAC, then device_identifiers(kind='mac'|'serial' value). A MAC mapping to
        several devices is reported as ambiguous (never guessed).
        """
        ids: set = set()
        for dev in self.db.scalars(
            select(Device).where(Device.tenant_id == tenant_id, Device.chassis_mac == mac)
        ):
            ids.add(dev.id)
        for iface in self.db.scalars(
            select(Interface).where(Interface.tenant_id == tenant_id, Interface.mac == mac)
        ):
            ids.add(iface.device_id)
        for row in self.db.scalars(
            select(DeviceIdentifier).where(
                DeviceIdentifier.tenant_id == tenant_id,
                DeviceIdentifier.kind == "mac",
                DeviceIdentifier.value == mac,
            )
        ):
            ids.add(row.device_id)
        return ids

    def olt_locations(
        self,
        tenant_slug: str,
        *,
        mac: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict:
        """Correlate OLT-learned MACs (behind ONUs) with known devices.

        A MAC learned on the OLT proves the equipment was observed BEHIND that
        ONU/PON/OLT — a location/path evidence. It does not by itself prove a
        direct ONU<->device cable, because a switch/bridge may sit in between.
        No PhysicalLink is inferred here; raw OltMacObservation rows are always
        preserved and returned.
        """
        tenant = self.require_tenant(tenant_slug)
        q = select(OltMacObservation).where(OltMacObservation.tenant_id == tenant.id)
        if mac:
            try:
                mac_n = normalize_mac(mac)
            except ValueError:
                mac_n = mac
            q = q.where(OltMacObservation.mac == mac_n)

        rows = list(
            self.db.scalars(
                q.order_by(OltMacObservation.last_seen.desc()).offset(offset).limit(limit)
            )
        )
        total_all = self.db.scalar(
            select(func.count()).select_from(OltMacObservation).where(
                OltMacObservation.tenant_id == tenant.id
            )
        ) or 0

        resolve_cache: dict[str, tuple[Optional[UUID], bool]] = {}
        mac_to_devices: dict[str, dict] = {}
        per_device: dict[UUID, dict] = {}

        for row in rows:
            if row.mac not in resolve_cache:
                ids = self._device_ids_for_mac(tenant.id, row.mac)
                if len(ids) == 1:
                    resolve_cache[row.mac] = (next(iter(ids)), False)
                elif len(ids) > 1:
                    resolve_cache[row.mac] = (None, True)
                else:
                    resolve_cache[row.mac] = (None, False)
            dev_id, ambiguous = resolve_cache[row.mac]
            entry = mac_to_devices.setdefault(
                row.mac,
                {"mac": row.mac, "resolved_device_id": None, "resolved_device": None,
                 "resolved": False, "ambiguous": ambiguous, "locations": []},
            )
            if dev_id is not None and entry["resolved_device_id"] is None:
                entry["resolved_device_id"] = str(dev_id)
                entry["resolved"] = True
                device = self.db.get(Device, dev_id)
                entry["resolved_device"] = device.name if device else None
                entry["device_type"] = device.device_type if device else None
                per_device.setdefault(
                    dev_id,
                    {"device_id": str(dev_id), "name": device.name if device else None,
                     "device_type": device.device_type if device else None,
                     "locations": {}, "macs": {}},
                )["macs"][row.mac] = True
            loc = {"ont_id": row.ont_id, "pon": row.pon, "serial": row.serial,
                   "vlan_id": row.vlan_id, "first_seen": row.first_seen.isoformat() if row.first_seen else None,
                   "last_seen": row.last_seen.isoformat() if row.last_seen else None}
            entry["locations"].append(loc)
            if dev_id is not None:
                dloc = per_device[dev_id]["locations"]
                key = (row.ont_id, row.pon, row.serial)
                d = dloc.setdefault(key, {"ont_id": row.ont_id, "pon": row.pon,
                                          "serial": row.serial, "macs": [], "first_seen": loc["first_seen"],
                                          "last_seen": row.last_seen.isoformat() if row.last_seen else None})
                if row.mac not in d["macs"]:
                    d["macs"].append(row.mac)
                if loc["first_seen"] and (not d["first_seen"] or loc["first_seen"] < d["first_seen"]):
                    d["first_seen"] = loc["first_seen"]

        mac_items = list(mac_to_devices.values())
        resolved_count = sum(1 for v in mac_items if v["resolved"])
        ambiguous_count = sum(1 for v in mac_items if v["ambiguous"])
        device_items = []
        for dev in per_device.values():
            dev["locations"] = list(dev["locations"].values())
            device_items.append(dev)

        return {
            "tenant": tenant.slug,
            "total_olt_mac_rows": int(total_all),
            "queried_rows": len(rows),
            "distinct_macs": len(mac_items),
            "resolved_macs": resolved_count,
            "ambiguous_macs": ambiguous_count,
            "unresolved_macs": len(mac_items) - resolved_count - ambiguous_count,
            "devices_localized": len(device_items),
            "devices": device_items,
            "macs": mac_items,
            "limit": limit,
            "offset": offset,
        }
