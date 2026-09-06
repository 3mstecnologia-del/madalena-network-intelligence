"""Parsers for MikroTik RouterOS text/CLI outputs. Transport-agnostic."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Optional

from app.core.ip import normalize_ip
from app.core.mac import normalize_mac
from collectors.common.types import (
    NormalizedArp,
    NormalizedDhcpLease,
    NormalizedIdentity,
    NormalizedInterface,
    NormalizedMacFdb,
    NormalizedNeighbor,
)

_ENTRY_START = re.compile(r"^(\d+)\s+")


def _iter_property_stanzas(text: str) -> Iterator[dict[str, str]]:
    """Yield key=value stanzas from RouterOS print-style output."""
    stanza: dict[str, str] = {}

    def flush() -> Optional[dict[str, str]]:
        nonlocal stanza
        if not stanza:
            return None
        out = stanza
        stanza = {}
        return out

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("Flags"):
            done = flush()
            if done:
                yield done
            continue
        if _ENTRY_START.match(line) and stanza:
            done = flush()
            if done:
                yield done
        if re.match(r"^\d+\s+D\b", line):
            stanza["dynamic"] = "yes"
        for part in line.split():
            if "=" in part:
                k, _, v = part.partition("=")
                stanza[k.lower()] = v
    done = flush()
    if done:
        yield done


def _clean_opt(v: Optional[str]) -> Optional[str]:
    if v is None or v == "" or v == '""':
        return None
    return v.strip('"')


def _safe_ip(value: str) -> Optional[str]:
    try:
        return normalize_ip(value)
    except ValueError:
        return None


@dataclass
class DhcpParseReport:
    leases: list[NormalizedDhcpLease]
    entries_seen: int
    parse_failures: int


def parse_dhcp_leases(text: str) -> list[NormalizedDhcpLease]:
    return parse_dhcp_report(text).leases


def parse_dhcp_report(text: str) -> DhcpParseReport:
    """Parse RouterOS DHCP lease print. entries_seen counts lease-like records."""
    if "mac-address=" in text or "address=" in text:
        leases: list[NormalizedDhcpLease] = []
        seen = 0
        failed = 0
        for stanza in _iter_property_stanzas(text):
            if not stanza.get("mac-address") and not stanza.get("address"):
                continue
            seen += 1
            ip = _safe_ip(stanza["address"]) if stanza.get("address") else None
            try:
                mac = normalize_mac(stanza["mac-address"]) if stanza.get("mac-address") else None
            except ValueError:
                mac = None
            if ip is None or mac is None:
                failed += 1
                continue
            kind = None
            if stanza.get("dynamic") in {"yes", "true", "1"}:
                kind = "dynamic"
            elif stanza.get("dynamic") in {"no", "false", "0"}:
                kind = "static"
            leases.append(
                NormalizedDhcpLease(
                    mac=mac,
                    ip_address=ip,
                    hostname=_clean_opt(stanza.get("host-name")),
                    server=_clean_opt(stanza.get("server")),
                    status=_clean_opt(stanza.get("status")),
                    comment=_clean_opt(stanza.get("comment")),
                    lease_kind=kind,
                    client_id=_clean_opt(stanza.get("client-id")),
                    reported_last_seen=_clean_opt(stanza.get("last-seen")),
                )
            )
        if seen:
            return DhcpParseReport(leases=leases, entries_seen=seen, parse_failures=failed)

    results: list[NormalizedDhcpLease] = []
    lease_re = re.compile(
        r"(?P<ip>\d+\.\d+\.\d+\.\d+)\s+"
        r"(?P<mac>[0-9A-Fa-f:\-\.]+)\s+"
        r"(?P<host>\S+)?\s*"
        r"(?P<server>\S+)?\s*"
        r"(?P<status>bound|waiting|busy|auth-failed|offered)?",
        re.IGNORECASE,
    )
    seen = failed = 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "ADDRESS" in line.upper() and "MAC" in line.upper():
            continue
        cleaned = re.sub(r"^[\d\sXDBR]+", "", line).strip()
        m = lease_re.search(cleaned) or lease_re.search(line)
        if not m:
            continue
        seen += 1
        try:
            mac = normalize_mac(m.group("mac"))
            ip = normalize_ip(m.group("ip"))
        except ValueError:
            failed += 1
            continue
        results.append(
            NormalizedDhcpLease(
                mac=mac,
                ip_address=ip,
                hostname=_clean_opt(m.group("host")),
                server=_clean_opt(m.group("server")),
                status=_clean_opt(m.group("status")),
            )
        )
    return DhcpParseReport(leases=results, entries_seen=seen, parse_failures=failed)


def parse_arp(text: str) -> list[NormalizedArp]:
    results: list[NormalizedArp] = []
    if "mac-address=" in text:
        for stanza in _iter_property_stanzas(text):
            if stanza.get("mac-address") and stanza.get("address"):
                ip = _safe_ip(stanza["address"])
                try:
                    mac = normalize_mac(stanza["mac-address"])
                except ValueError:
                    continue
                if ip is None:
                    continue
                results.append(
                    NormalizedArp(
                        mac=mac,
                        ip_address=ip,
                        interface=_clean_opt(stanza.get("interface")),
                    )
                )
        if results:
            return results

    arp_re = re.compile(
        r"(?P<ip>\d+\.\d+\.\d+\.\d+)\s+"
        r"(?P<mac>[0-9A-Fa-f:\-\.]+)\s+"
        r"(?P<iface>\S+)?",
        re.IGNORECASE,
    )
    for line in text.splitlines():
        if not line.strip() or ("ADDRESS" in line.upper() and "MAC" in line.upper()):
            continue
        m = arp_re.search(line)
        if not m:
            continue
        try:
            mac = normalize_mac(m.group("mac"))
        except ValueError:
            continue
        results.append(
            NormalizedArp(mac=mac, ip_address=normalize_ip(m.group("ip")), interface=_clean_opt(m.group("iface")))
        )
    return results


def parse_bridge_fdb(text: str) -> list[NormalizedMacFdb]:
    results: list[NormalizedMacFdb] = []
    if "mac-address=" in text:
        for stanza in _iter_property_stanzas(text):
            if not stanza.get("mac-address"):
                continue
            vlan = stanza.get("vid") or stanza.get("vlan-id")
            try:
                mac = normalize_mac(stanza["mac-address"])
            except ValueError:
                continue
            results.append(
                NormalizedMacFdb(
                    mac=mac,
                    interface=_clean_opt(stanza.get("on-interface") or stanza.get("interface")),
                    vlan_id=int(vlan) if vlan and vlan.isdigit() else None,
                    bridge=_clean_opt(stanza.get("bridge")),
                )
            )
        if results:
            return results

    fdb_re = re.compile(
        r"(?P<mac>[0-9A-Fa-f:\-\.]+)\s+"
        r"(?:on\s+)?(?P<iface>\S+)"
        r"(?:\s+vlan\s*(?P<vlan>\d+))?",
        re.IGNORECASE,
    )
    for line in text.splitlines():
        if not line.strip() or line.lower().startswith("flags"):
            continue
        m = fdb_re.search(line)
        if not m:
            continue
        try:
            mac = normalize_mac(m.group("mac"))
        except ValueError:
            continue
        vlan = m.groupdict().get("vlan")
        results.append(
            NormalizedMacFdb(
                mac=mac,
                interface=_clean_opt(m.group("iface")),
                vlan_id=int(vlan) if vlan else None,
            )
        )
    return results


def parse_identity(text: str) -> Optional[NormalizedIdentity]:
    """Parse `/system identity print` and optional `/system resource print`."""
    name = None
    version = None
    for stanza in _iter_property_stanzas(text) if "=" in text else []:
        name = name or _clean_opt(stanza.get("name"))
        version = version or _clean_opt(stanza.get("version"))
    if name is None:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("name:"):
                name = stripped.split(":", 1)[1].strip() or None
            if stripped.lower().startswith("version:"):
                version = stripped.split(":", 1)[1].strip() or None
    if not name and not version:
        return None
    return NormalizedIdentity(name=name, version=version)


def parse_interfaces(text: str) -> list[NormalizedInterface]:
    results: list[NormalizedInterface] = []
    if "name=" in text:
        for stanza in _iter_property_stanzas(text):
            name = _clean_opt(stanza.get("name"))
            if not name:
                continue
            results.append(
                NormalizedInterface(
                    name=name,
                    if_type=_clean_opt(stanza.get("type")),
                    admin_status=_clean_opt(stanza.get("disabled")),
                    oper_status=_clean_opt(stanza.get("running")),
                    mac=_safe_mac(stanza.get("mac-address")),
                    description=_clean_opt(stanza.get("comment") or stanza.get("description")),
                    identifiers={
                        key: value
                        for key, value in {
                            "default_name": _clean_opt(stanza.get("default-name")),
                            "ifindex": _clean_opt(stanza.get("ifindex") or stanza.get("id")),
                        }.items()
                        if value
                    },
                    evidence={
                        key: value
                        for key, value in {
                            "comment": _clean_opt(stanza.get("comment")),
                            "description": _clean_opt(stanza.get("description")),
                        }.items()
                        if value
                    },
                )
            )
        if results:
            return results
    return results


def parse_neighbors(text: str) -> list[NormalizedNeighbor]:
    results: list[NormalizedNeighbor] = []
    if "mac-address=" in text or "identity=" in text:
        for stanza in _iter_property_stanzas(text):
            mac_raw = stanza.get("mac-address")
            mac = _safe_mac(mac_raw) if mac_raw else None
            addr = stanza.get("address")
            ip = _safe_ip(addr) if addr else None
            ident = _clean_opt(stanza.get("identity"))
            if not mac and not ident and not ip:
                continue
            results.append(
                NormalizedNeighbor(
                    mac=mac,
                    ip_address=ip,
                    interface=_clean_opt(stanza.get("interface")),
                    remote_interface=_clean_opt(stanza.get("interface-name")),
                    identity=ident,
                    platform=_clean_opt(stanza.get("platform") or stanza.get("board")),
                    version=_clean_opt(stanza.get("version")),
                    protocol=_normalize_protocol(stanza.get("discoverer") or stanza.get("protocol")),
                    chassis_id=_safe_mac(stanza.get("chassis-id"))
                    or _clean_opt(stanza.get("chassis-id")),
                )
            )
    return results


def _normalize_protocol(value: Optional[str]) -> Optional[str]:
    raw = (value or "").strip().lower()
    if not raw:
        return None
    if "lldp" in raw:
        return "lldp"
    if "cdp" in raw:
        return "cdp"
    if "mndp" in raw:
        return "mndp"
    return raw.split()[0]


def _safe_mac(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return normalize_mac(value)
    except ValueError:
        return None
