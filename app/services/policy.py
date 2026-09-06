"""Drop out-of-scope observations after parse, before persist.

Rules are tenant/site/device scoped and stored in the database (runtime),
never hardcoded as customer VLANs or networks.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, replace
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.collectors_config import parse_collectors_enabled
from app.models.entities import Device, ExclusionPolicy
from collectors.common.types import CollectorResult

RULE_VLAN = "vlan"
RULE_CIDR = "cidr"
RULE_SOURCE = "source"
RULE_COLLECTOR = "collector"
RULE_INTERFACE = "interface"

_SOURCE_COLLECTOR = {
    "mikrotik_dhcp": "dhcp",
    "mikrotik_arp": "arp",
    "bridge_fdb": "fdb",
    "mikrotik_identity": "identity",
    "mikrotik_interface": "interfaces",
    "mikrotik_neighbor": "neighbors",
    "olt": "ont_mac_table",
    "unifi_inventory": "inventory",
    "unifi_interface": "inventory",
    "unifi_uplink": "inventory",
}


@dataclass(frozen=True)
class PolicyRules:
    vlans: frozenset[int]
    networks: tuple[ipaddress._BaseNetwork, ...]
    sources: frozenset[str]
    collectors: frozenset[str]
    interfaces: frozenset[str]

    def collector_blocked(self, name: str) -> bool:
        return name in self.collectors

    def source_blocked(self, source: Optional[str]) -> bool:
        if not source:
            return False
        return source in self.sources or _SOURCE_COLLECTOR.get(source, "") in self.collectors

    def vlan_blocked(self, vlan_id: Optional[int]) -> bool:
        return vlan_id is not None and vlan_id in self.vlans

    def interface_blocked(self, name: Optional[str]) -> bool:
        if not name:
            return False
        return name in self.interfaces or name.lower() in {i.lower() for i in self.interfaces}

    def ip_blocked(self, ip_text: Optional[str]) -> bool:
        if not ip_text or not self.networks:
            return False
        try:
            addr = ipaddress.ip_address(ip_text)
        except ValueError:
            return False
        return any(addr in net for net in self.networks)


def load_policy(db: Session, tenant_id: UUID, device: Optional[Device] = None) -> PolicyRules:
    rows = list(
        db.scalars(
            select(ExclusionPolicy).where(
                ExclusionPolicy.tenant_id == tenant_id,
                ExclusionPolicy.enabled.is_(True),
            )
        )
    )
    vlans: set[int] = set()
    networks: list[ipaddress._BaseNetwork] = []
    sources: set[str] = set()
    collectors: set[str] = set()
    interfaces: set[str] = set()
    for row in rows:
        if row.device_id is not None and (device is None or row.device_id != device.id):
            continue
        if row.site_id is not None and (device is None or row.site_id != device.site_id):
            continue
        kind = (row.rule_type or "").strip().lower()
        value = (row.rule_value or "").strip()
        if not value:
            continue
        if kind == RULE_VLAN:
            try:
                vlans.add(int(value))
            except ValueError:
                continue
        elif kind == RULE_CIDR:
            try:
                networks.append(ipaddress.ip_network(value, strict=False))
            except ValueError:
                continue
        elif kind == RULE_SOURCE:
            sources.add(value)
        elif kind == RULE_COLLECTOR:
            collectors.add(value)
        elif kind == RULE_INTERFACE:
            interfaces.add(value)
    if device is not None:
        enabled = parse_collectors_enabled(device.collectors_enabled, device.device_type)
        defaults = parse_collectors_enabled(None, device.device_type)
        collectors |= set(defaults - enabled)
    return PolicyRules(
        vlans=frozenset(vlans),
        networks=tuple(networks),
        sources=frozenset(sources),
        collectors=frozenset(collectors),
        interfaces=frozenset(interfaces),
    )


def apply_policy(result: CollectorResult, rules: PolicyRules) -> tuple[CollectorResult, int]:
    """Return a copy of result with excluded observations removed. Count dropped items."""
    excluded = 0

    def keep_ip_iface_vlan(*, ip=None, iface=None, vlan=None, source=None, collector=None) -> bool:
        nonlocal excluded
        if collector and rules.collector_blocked(collector):
            excluded += 1
            return False
        if rules.source_blocked(source):
            excluded += 1
            return False
        if rules.vlan_blocked(vlan):
            excluded += 1
            return False
        if rules.interface_blocked(iface):
            excluded += 1
            return False
        if rules.ip_blocked(ip):
            excluded += 1
            return False
        return True

    dhcp = [
        x
        for x in result.dhcp
        if keep_ip_iface_vlan(ip=x.ip_address, source=x.source, collector="dhcp")
    ]
    arp = [
        x
        for x in result.arp
        if keep_ip_iface_vlan(
            ip=x.ip_address, iface=x.interface, source=x.source, collector="arp"
        )
    ]
    fdb = [
        x
        for x in result.fdb
        if keep_ip_iface_vlan(
            iface=x.interface, vlan=x.vlan_id, source=x.source, collector="fdb"
        )
    ]
    neighbors = [
        x
        for x in result.neighbors
        if keep_ip_iface_vlan(
            ip=x.ip_address,
            iface=x.interface,
            source=x.source,
            collector="neighbors",
        )
    ]
    interfaces = [
        x
        for x in result.interfaces
        if keep_ip_iface_vlan(iface=x.name, source=x.source, collector="interfaces")
    ]
    olt_macs = [
        x
        for x in result.olt_macs
        if keep_ip_iface_vlan(
            vlan=x.vlan_id, source=x.source, collector="ont_mac_table"
        )
    ]
    onus = list(result.onus)
    if rules.collector_blocked("ont_mac_table") and rules.collector_blocked("ont_brief"):
        excluded += len(onus)
        onus = []
    identity = result.identity
    if identity is not None and (
        rules.collector_blocked("identity") or rules.source_blocked(identity.source)
    ):
        excluded += 1
        identity = None
    inventory_nodes = [
        x
        for x in result.inventory_nodes
        if keep_ip_iface_vlan(
            ip=x.ip_address, source=x.source, collector="inventory"
        )
    ]
    topology_links = [
        x
        for x in result.topology_links
        if keep_ip_iface_vlan(
            ip=x.remote_ip,
            iface=x.local_interface,
            source=x.source,
            collector=_SOURCE_COLLECTOR.get(x.source, "neighbors"),
        )
    ]

    filtered = replace(
        result,
        dhcp=dhcp,
        arp=arp,
        fdb=fdb,
        neighbors=neighbors,
        interfaces=interfaces,
        olt_macs=olt_macs,
        onus=onus,
        identity=identity,
        inventory_nodes=inventory_nodes,
        topology_links=topology_links,
        meta=dict(result.meta),
    )
    filtered.meta["records_excluded"] = excluded
    return filtered, excluded
