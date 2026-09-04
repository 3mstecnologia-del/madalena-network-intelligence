"""IP address normalization. IPv4 is first-class; IPv6 is accepted and stored canonically."""

from __future__ import annotations

import ipaddress


def normalize_ip(value: str) -> str:
    """Return a canonical IP string (IPv4 or IPv6). Raises ValueError if invalid."""
    if value is None:
        raise ValueError("IP is required")
    raw = str(value).strip()
    if not raw:
        raise ValueError("IP is empty")
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError as exc:
        raise ValueError(f"Invalid IP address: {value!r}") from exc


def normalize_ipv4(value: str) -> str:
    """Canonical dotted IPv4. Rejects IPv6."""
    addr = ipaddress.ip_address(str(value).strip())
    if not isinstance(addr, ipaddress.IPv4Address):
        raise ValueError(f"Not an IPv4 address: {value!r}")
    return str(addr)
