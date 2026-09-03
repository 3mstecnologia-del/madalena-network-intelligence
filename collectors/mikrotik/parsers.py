"""Parsers for MikroTik RouterOS text/CLI outputs. Transport-agnostic."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Optional

from app.core.mac import normalize_mac
from collectors.common.types import NormalizedArp, NormalizedDhcpLease, NormalizedMacFdb

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


def parse_dhcp_leases(text: str) -> list[NormalizedDhcpLease]:
    results: list[NormalizedDhcpLease] = []
    if "mac-address=" in text:
        for stanza in _iter_property_stanzas(text):
            if stanza.get("mac-address") and stanza.get("address"):
                results.append(
                    NormalizedDhcpLease(
                        mac=normalize_mac(stanza["mac-address"]),
                        ip_address=stanza["address"],
                        hostname=_clean_opt(stanza.get("host-name")),
                        server=_clean_opt(stanza.get("server")),
                        status=_clean_opt(stanza.get("status")),
                        comment=_clean_opt(stanza.get("comment")),
                    )
                )
        if results:
            return results

    lease_re = re.compile(
        r"(?P<ip>\d+\.\d+\.\d+\.\d+)\s+"
        r"(?P<mac>[0-9A-Fa-f:\-\.]+)\s+"
        r"(?P<host>\S+)?\s*"
        r"(?P<server>\S+)?\s*"
        r"(?P<status>bound|waiting|busy|auth-failed|offered)?",
        re.IGNORECASE,
    )
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
        try:
            mac = normalize_mac(m.group("mac"))
        except ValueError:
            continue
        results.append(
            NormalizedDhcpLease(
                mac=mac,
                ip_address=m.group("ip"),
                hostname=_clean_opt(m.group("host")),
                server=_clean_opt(m.group("server")),
                status=_clean_opt(m.group("status")),
            )
        )
    return results


def parse_arp(text: str) -> list[NormalizedArp]:
    results: list[NormalizedArp] = []
    if "mac-address=" in text:
        for stanza in _iter_property_stanzas(text):
            if stanza.get("mac-address") and stanza.get("address"):
                results.append(
                    NormalizedArp(
                        mac=normalize_mac(stanza["mac-address"]),
                        ip_address=stanza["address"],
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
            NormalizedArp(mac=mac, ip_address=m.group("ip"), interface=_clean_opt(m.group("iface")))
        )
    return results


def parse_bridge_fdb(text: str) -> list[NormalizedMacFdb]:
    results: list[NormalizedMacFdb] = []
    if "mac-address=" in text:
        for stanza in _iter_property_stanzas(text):
            if not stanza.get("mac-address"):
                continue
            vlan = stanza.get("vid") or stanza.get("vlan-id")
            results.append(
                NormalizedMacFdb(
                    mac=normalize_mac(stanza["mac-address"]),
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
