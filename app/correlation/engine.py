"""Correlate observations for a MAC without destroying raw rows."""

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
    OltMacObservation,
    OltOnu,
    Tenant,
)


@dataclass
class AccessPath:
    olt_device: Optional[str] = None
    olt_device_id: Optional[str] = None
    pon: Optional[str] = None
    onu: Optional[str] = None
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
    hostname: Optional[str] = None
    dhcp: list[dict[str, Any]] = field(default_factory=list)
    arp: list[dict[str, Any]] = field(default_factory=list)
    fdb: list[dict[str, Any]] = field(default_factory=list)
    access_path: Optional[AccessPath] = None
    olt_macs: list[dict[str, Any]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

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

        sources: set[str] = set()
        hostname = None
        current_ips: list[dict[str, Any]] = []
        historical_ips: list[dict[str, Any]] = []
        seen_ip: set[str] = set()

        dhcp_out = []
        for i, row in enumerate(dhcp_rows):
            sources.add(row.source)
            device = self.db.get(Device, row.device_id)
            item = {
                "ip": row.ip_address,
                "hostname": row.hostname,
                "server": row.server,
                "status": row.status,
                "device": device.name if device else None,
                "first_seen": row.first_seen.isoformat() if row.first_seen else None,
                "last_seen": row.last_seen.isoformat() if row.last_seen else None,
            }
            dhcp_out.append(item)
            if i == 0:
                hostname = row.hostname
                current_ips.append({"ip": row.ip_address, "via": "dhcp", "device": item["device"]})
                seen_ip.add(row.ip_address)
            elif row.ip_address not in seen_ip:
                historical_ips.append({"ip": row.ip_address, "via": "dhcp", "last_seen": item["last_seen"]})
                seen_ip.add(row.ip_address)

        arp_out = []
        for i, row in enumerate(arp_rows):
            sources.add(row.source)
            device = self.db.get(Device, row.device_id)
            item = {
                "ip": row.ip_address,
                "interface": row.interface,
                "device": device.name if device else None,
                "last_seen": row.last_seen.isoformat() if row.last_seen else None,
            }
            arp_out.append(item)
            if row.ip_address not in seen_ip:
                if not current_ips:
                    current_ips.append({"ip": row.ip_address, "via": "arp", "device": item["device"]})
                else:
                    historical_ips.append({"ip": row.ip_address, "via": "arp", "last_seen": item["last_seen"]})
                seen_ip.add(row.ip_address)

        fdb_out = []
        for row in fdb_rows:
            sources.add(row.source)
            device = self.db.get(Device, row.device_id)
            fdb_out.append(
                {
                    "interface": row.interface,
                    "vlan_id": row.vlan_id,
                    "bridge": row.bridge,
                    "device": device.name if device else None,
                    "last_seen": row.last_seen.isoformat() if row.last_seen else None,
                }
            )

        access: Optional[AccessPath] = None
        olt_out = []
        for i, row in enumerate(olt_rows):
            sources.add(row.source)
            device = self.db.get(Device, row.device_id)
            olt_out.append(
                {
                    "ont_id": row.ont_id,
                    "pon": row.pon,
                    "vlan_id": row.vlan_id,
                    "device": device.name if device else None,
                    "last_seen": row.last_seen.isoformat() if row.last_seen else None,
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
                access = AccessPath(
                    olt_device=device.name if device else None,
                    olt_device_id=str(device.id) if device else None,
                    pon=row.pon,
                    onu=row.ont_id,
                    profile=profile,
                    serial=serial,
                )

        return MacCorrelation(
            mac=mac,
            tenant=tenant.slug,
            first_seen=mac_row.first_seen if mac_row else None,
            last_seen=mac_row.last_seen if mac_row else None,
            current_ips=current_ips,
            historical_ips=historical_ips,
            hostname=hostname,
            dhcp=dhcp_out,
            arp=arp_out,
            fdb=fdb_out,
            access_path=access,
            olt_macs=olt_out,
            sources=sorted(sources),
        )
