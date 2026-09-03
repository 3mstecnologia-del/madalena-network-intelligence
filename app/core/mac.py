"""Canonical MAC address normalization."""

from __future__ import annotations

import re

_HEX = re.compile(r"[^0-9A-Fa-f]")


def normalize_mac(value: str) -> str:
    """Normalize any common MAC notation to AA:BB:CC:DD:EE:FF.

    Accepts colon, hyphen, Cisco dotted, or bare hex.
    """
    if value is None:
        raise ValueError("MAC is required")
    raw = str(value).strip()
    if not raw:
        raise ValueError("MAC is empty")
    hex_only = _HEX.sub("", raw)
    if len(hex_only) != 12:
        raise ValueError(f"Invalid MAC length after normalization: {value!r}")
    try:
        int(hex_only, 16)
    except ValueError as exc:
        raise ValueError(f"Invalid MAC hex: {value!r}") from exc
    parts = [hex_only[i : i + 2].upper() for i in range(0, 12, 2)]
    return ":".join(parts)


def macs_equal(a: str, b: str) -> bool:
    return normalize_mac(a) == normalize_mac(b)
