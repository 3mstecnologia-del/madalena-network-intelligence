"""Per-device enabled collector keys. No customer topology here."""

from __future__ import annotations

import json
from typing import Optional

from app.models.entities import Device

DEFAULT_COLLECTORS: dict[str, tuple[str, ...]] = {
    "mikrotik": ("identity", "dhcp", "arp", "fdb", "interfaces", "neighbors"),
    "intelbras_g08": ("ont_mac_table", "ont_brief"),
    "unifi_network": ("inventory", "device_details"),
}


def parse_collectors_enabled(raw: Optional[str], device_type: str) -> frozenset[str]:
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = [p.strip() for p in raw.split(",") if p.strip()]
        if isinstance(data, list) and data:
            return frozenset(str(x).strip() for x in data if str(x).strip())
    return frozenset(DEFAULT_COLLECTORS.get(device_type, ()))


def enabled_collectors(device: Device) -> frozenset[str]:
    return parse_collectors_enabled(device.collectors_enabled, device.device_type)
