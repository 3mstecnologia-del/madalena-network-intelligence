from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class NormalizedDhcpLease:
    mac: str
    ip_address: str
    hostname: Optional[str] = None
    server: Optional[str] = None
    status: Optional[str] = None
    comment: Optional[str] = None
    lease_kind: Optional[str] = None
    client_id: Optional[str] = None
    reported_last_seen: Optional[str] = None
    observed_at: datetime = field(default_factory=utcnow)
    source: str = "mikrotik_dhcp"


@dataclass
class NormalizedArp:
    mac: str
    ip_address: str
    interface: Optional[str] = None
    observed_at: datetime = field(default_factory=utcnow)
    source: str = "mikrotik_arp"


@dataclass
class NormalizedMacFdb:
    mac: str
    interface: Optional[str] = None
    vlan_id: Optional[int] = None
    bridge: Optional[str] = None
    observed_at: datetime = field(default_factory=utcnow)
    source: str = "bridge_fdb"
    confidence: Optional[float] = 1.0


@dataclass
class NormalizedOnu:
    ont_id: str
    pon: Optional[str] = None
    serial: Optional[str] = None
    status: Optional[str] = None
    profile_name: Optional[str] = None
    observed_at: datetime = field(default_factory=utcnow)


@dataclass
class NormalizedOltMac:
    mac: str
    ont_id: Optional[str] = None
    pon: Optional[str] = None
    vlan_id: Optional[int] = None
    gem: Optional[str] = None
    serial: Optional[str] = None
    observed_at: datetime = field(default_factory=utcnow)
    source: str = "olt"
    command: Optional[str] = None


@dataclass
class NormalizedIdentity:
    name: Optional[str] = None
    version: Optional[str] = None
    observed_at: datetime = field(default_factory=utcnow)
    source: str = "mikrotik_identity"


@dataclass
class NormalizedInterface:
    name: str
    if_type: Optional[str] = None
    admin_status: Optional[str] = None
    oper_status: Optional[str] = None
    mac: Optional[str] = None
    observed_at: datetime = field(default_factory=utcnow)
    source: str = "mikrotik_interface"


@dataclass
class NormalizedNeighbor:
    mac: Optional[str] = None
    ip_address: Optional[str] = None
    interface: Optional[str] = None
    identity: Optional[str] = None
    platform: Optional[str] = None
    observed_at: datetime = field(default_factory=utcnow)
    source: str = "mikrotik_neighbor"


@dataclass
class CollectorResult:
    dhcp: list[NormalizedDhcpLease] = field(default_factory=list)
    arp: list[NormalizedArp] = field(default_factory=list)
    fdb: list[NormalizedMacFdb] = field(default_factory=list)
    onus: list[NormalizedOnu] = field(default_factory=list)
    olt_macs: list[NormalizedOltMac] = field(default_factory=list)
    identity: Optional[NormalizedIdentity] = None
    interfaces: list[NormalizedInterface] = field(default_factory=list)
    neighbors: list[NormalizedNeighbor] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
