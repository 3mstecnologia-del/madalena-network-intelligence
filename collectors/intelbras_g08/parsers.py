"""Parsers for Intelbras G08 CLI outputs.

Commands referenced from hermes skill olt-intelbras-g08-ops (operational knowledge).
Does not invent CLI. Live collection uses `show ont mac-address-table interface gpon all`.
The short form `show ont mac-address` is incomplete on the validated G08 family.
"""

from __future__ import annotations

import re
from typing import Optional

from app.core.mac import normalize_mac
from collectors.common.types import NormalizedOltMac, NormalizedOnu

_MAC_TOKEN = re.compile(
    r"(?P<mac>"
    r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}|"
    r"[0-9A-Fa-f]{2}(?:-[0-9A-Fa-f]{2}){5}|"
    r"[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}|"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}|"
    r"[0-9A-Fa-f]{12}"
    r")"
)
_ONT_ID = re.compile(r"\b(\d+/\d+/\d+)\b")
_PON = re.compile(r"(?i)\b(?:gpon\s+)?(\d+/\d+)\b")
_VLAN_LABELED = re.compile(r"(?i)\bvlan(?:-?id)?\s*[:=]?\s*(\d{1,4})\b")
_GEM_LABELED = re.compile(r"(?i)\bgem(?:port)?\s*[:=]?\s*(\d+)\b")

# Live G08: MAC-Address  VID  ONT-ID  SN  ID/GEM
_MAC_VID_ONT = re.compile(
    r"(?P<mac>"
    r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}|"
    r"[0-9A-Fa-f]{2}(?:-[0-9A-Fa-f]{2}){5}|"
    r"[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}|"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}"
    r")\s+"
    r"(?P<vid>\d{1,4})\s+"
    r"(?P<ont>\d+/\d+/\d+)\s+"
    r"(?P<sn>\S+)"
    r"(?:\s+(?P<gem>\S+))?",
)
_MAC_ROW = re.compile(
    r"(?P<ont>\d+/\d+/\d+)\s+"
    r"(?:gpon\s*)?(?P<pon>\d+/\d+)?\s*"
    r"(?P<mac>[0-9A-Fa-f:\-\.]+)\s*"
    r"(?:vlan\s*)?(?P<vlan>\d+)?\s*"
    r"(?:gem\s*)?(?P<gem>\d+)?",
    re.IGNORECASE,
)

_ONT_BRIEF = re.compile(
    r"(?P<ont>\d+/\d+/\d+)\s+"
    r"(?P<serial>[A-Za-z0-9]+)\s+"
    r"(?P<status>online|offline|los|dying-gasp|\S+)\s*"
    r"(?P<profile>\S+)?",
    re.IGNORECASE,
)


def parse_ont_mac_address(
    text: str, *, command: str = "show ont mac-address-table interface gpon all", source: str = "olt"
) -> list[NormalizedOltMac]:
    """Parse `show ont mac-address` / mac-address-table style tables."""
    results, _ = parse_ont_mac_address_with_count(text, command=command, source=source)
    return results


def parse_ont_mac_address_with_count(
    text: str, *, command: str = "show ont mac-address-table interface gpon all", source: str = "olt"
) -> tuple[list[NormalizedOltMac], int]:
    """Return distinct service rows and the number of syntactically parsed rows."""
    results: list[NormalizedOltMac] = []
    parsed_rows = 0
    seen: set[tuple[str, Optional[str], Optional[str], Optional[int], Optional[str]]] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        upper = line.upper()
        if "MAC" in upper and ("ONT" in upper or "ADDRESS" in upper) and not _MAC_TOKEN.search(line):
            continue
        if set(line) <= set("-_= "):
            continue
        row = _parse_mac_line(line, command=command, source=source)
        if row is None:
            continue
        parsed_rows += 1
        key = (row.mac, row.ont_id, row.pon, row.vlan_id, row.gem)
        if key in seen:
            continue
        seen.add(key)
        results.append(row)
    return results, parsed_rows


def parse_ont_mac_address_table(text: str) -> list[NormalizedOltMac]:
    """Backward-compatible name used by fixtures and collect_from_texts."""
    return parse_ont_mac_address(
        text, command="show ont mac-address-table interface gpon all", source="olt"
    )


def _parse_mac_line(line: str, *, command: str, source: str) -> Optional[NormalizedOltMac]:
    mac_m = _MAC_TOKEN.search(line)
    if not mac_m:
        return None
    try:
        mac = normalize_mac(mac_m.group("mac"))
    except ValueError:
        return None

    ont = None
    pon = None
    vlan = None
    gem = None
    serial = None

    vid_row = _MAC_VID_ONT.search(line)
    if vid_row:
        try:
            mac = normalize_mac(vid_row.group("mac"))
        except ValueError:
            vid_row = None
        else:
            ont = vid_row.group("ont")
            vlan = int(vid_row.group("vid"))
            serial = _opt(vid_row.group("sn"))
            gem = vid_row.group("gem")

    if ont is None:
        row = _MAC_ROW.search(line)
        if row:
            try:
                mac = normalize_mac(row.group("mac"))
            except ValueError:
                pass
            else:
                ont = row.group("ont")
                pon = row.group("pon")
                if row.group("vlan"):
                    vlan = int(row.group("vlan"))
                gem = row.group("gem")

    if ont is None:
        ont_m = _ONT_ID.search(line)
        if ont_m:
            ont = ont_m.group(1)

    if pon is None:
        if ont:
            parts = ont.split("/")
            if len(parts) >= 2:
                pon = f"{parts[0]}/{parts[1]}"
        else:
            pon_m = _PON.search(line)
            if pon_m:
                pon = pon_m.group(1)

    labeled_vlan = _VLAN_LABELED.search(line)
    if labeled_vlan:
        vlan = int(labeled_vlan.group(1))
    labeled_gem = _GEM_LABELED.search(line)
    if labeled_gem:
        gem = labeled_gem.group(1)

    return NormalizedOltMac(
        mac=mac,
        ont_id=ont,
        pon=pon,
        vlan_id=vlan,
        gem=gem,
        serial=serial,
        source=source,
        command=command,
    )


def parse_ont_brief(text: str) -> list[NormalizedOnu]:
    """Parse output of: show ont brief interface gpon all"""
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


def onus_from_macs(macs: list[NormalizedOltMac]) -> list[NormalizedOnu]:
    """Minimal ONU rows implied by MAC observations. No invented serial/status."""
    seen: dict[str, NormalizedOnu] = {}
    for row in macs:
        if not row.ont_id:
            continue
        if row.ont_id not in seen:
            seen[row.ont_id] = NormalizedOnu(
                ont_id=row.ont_id, pon=row.pon, serial=getattr(row, "serial", None)
            )
        elif getattr(row, "serial", None) and not seen[row.ont_id].serial:
            seen[row.ont_id].serial = row.serial
    return list(seen.values())


def _opt(v: Optional[str]) -> Optional[str]:
    if not v or v.lower() in {"n/a", "-", "none"}:
        return None
    return v
