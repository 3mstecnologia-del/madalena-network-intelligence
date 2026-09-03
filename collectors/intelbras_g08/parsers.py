"""Parsers for Intelbras G08 CLI outputs.

Commands referenced from hermes skill olt-intelbras-g08-ops (operational knowledge).
This collector does NOT invent CLI — only parse fixtures / validated formats.
"""

from __future__ import annotations

import re
from typing import Optional

from app.core.mac import normalize_mac
from collectors.common.types import NormalizedOltMac, NormalizedOnu

# Fixture-oriented table: ONT_ID  PON  MAC  VLAN  GEM
# Example validated skill command: show ont mac-address-table interface gpon all
_MAC_ROW = re.compile(
    r"(?P<ont>\d+/\d+/\d+)\s+"
    r"(?:gpon\s*)?(?P<pon>\d+/\d+)?\s*"
    r"(?P<mac>[0-9A-Fa-f:\-\.]+)\s*"
    r"(?:vlan\s*)?(?P<vlan>\d+)?\s*"
    r"(?:gem\s*)?(?P<gem>\d+)?",
    re.IGNORECASE,
)

_MAC_SIMPLE = re.compile(
    r"(?P<mac>[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}|[0-9A-Fa-f]{12})"
    r".*?(?:ont[-\s]?(?:id)?[=:\s]+)(?P<ont>\d+/\d+/\d+)",
    re.IGNORECASE,
)

# Brief ONT line: 0/1/14  SERIAL  online  PROFILE
_ONT_BRIEF = re.compile(
    r"(?P<ont>\d+/\d+/\d+)\s+"
    r"(?P<serial>[A-Za-z0-9]+)\s+"
    r"(?P<status>online|offline|los|dying-gasp|\S+)\s*"
    r"(?P<profile>\S+)?",
    re.IGNORECASE,
)


def parse_ont_mac_address_table(text: str) -> list[NormalizedOltMac]:
    """Parse output of: show ont mac-address-table interface gpon all

    TODO: validate exact column layout against live G08 once lab access is authorized.
    Current parser accepts a documented fixture format for CI.
    """
    results: list[NormalizedOltMac] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "MAC" in line.upper() and "ONT" in line.upper():
            continue
        m = _MAC_ROW.search(line)
        if m:
            try:
                mac = normalize_mac(m.group("mac"))
            except ValueError:
                continue
            pon = m.group("pon")
            ont = m.group("ont")
            if not pon and ont:
                parts = ont.split("/")
                if len(parts) >= 2:
                    pon = f"{parts[0]}/{parts[1]}"
            vlan = m.group("vlan")
            results.append(
                NormalizedOltMac(
                    mac=mac,
                    ont_id=ont,
                    pon=pon,
                    vlan_id=int(vlan) if vlan else None,
                    gem=m.group("gem"),
                )
            )
            continue
        m2 = _MAC_SIMPLE.search(line)
        if m2:
            try:
                mac = normalize_mac(m2.group("mac"))
            except ValueError:
                continue
            ont = m2.group("ont")
            parts = ont.split("/")
            pon = f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else None
            results.append(NormalizedOltMac(mac=mac, ont_id=ont, pon=pon))
    return results


def parse_ont_brief(text: str) -> list[NormalizedOnu]:
    """Parse output of: show ont brief interface gpon all

    TODO: confirm exact columns on live equipment; fixture-driven for Phase 1.
    """
    results: list[NormalizedOnu] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "ONT" in line.upper() and "SERIAL" in line.upper():
            continue
        m = _ONT_BRIEF.search(line)
        if not m:
            continue
        ont = m.group("ont")
        parts = ont.split("/")
        pon = f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else None
        results.append(
            NormalizedOnu(
                ont_id=ont,
                pon=pon,
                serial=m.group("serial"),
                status=m.group("status").lower() if m.group("status") else None,
                profile_name=_opt(m.group("profile")),
            )
        )
    return results


def _opt(v: Optional[str]) -> Optional[str]:
    if not v or v.lower() in {"n/a", "-", "none"}:
        return None
    return v
