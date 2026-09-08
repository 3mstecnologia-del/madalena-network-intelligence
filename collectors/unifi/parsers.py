"""Parse UniFi Network Integration API JSON into normalized observations.

Field names follow the documented Integration schema. List vs detail payloads
disagree on `mac` vs `macAddress` — both are accepted. Missing fields are not errors.
Uplink in the documented schema is `{ "deviceId": "<uuid>" }` only.
"""

from __future__ import annotations

from typing import Any, Optional

from app.core.ip import normalize_ip
from app.core.mac import normalize_mac
from collectors.common.types import (
    NormalizedInterface,
    NormalizedInventoryNode,
    NormalizedTopologyLink,
)


def parse_sites(payload: Any) -> list[dict[str, str]]:
    sites: list[dict[str, str]] = []
    for item in _items(payload):
        if not isinstance(item, dict):
            continue
        site_id = _clean(item.get("id"))
        if not site_id:
            continue
        sites.append(
            {
                "id": site_id,
                "name": _clean(item.get("name")) or site_id,
                "internal_reference": _clean(item.get("internalReference")) or "",
            }
        )
    return sites


def parse_device_payload(item: Any) -> Optional[NormalizedInventoryNode]:
    if not isinstance(item, dict):
        return None
    source_id = _clean(item.get("id"))
    mac = _safe_mac(item.get("macAddress") or item.get("mac"))
    name = _clean(item.get("name"))
    if not source_id and not mac and not name:
        return None
    uplink = item.get("uplink")
    uplink_id = None
    if isinstance(uplink, dict):
        uplink_id = _clean(uplink.get("deviceId"))
    uplink_id = uplink_id or _clean(item.get("uplinkDeviceId"))
    uplink_port = None
    if isinstance(uplink, dict):
        uplink_port = _clean(uplink.get("portIdx"))
    uplink_port = uplink_port or _clean(item.get("uplinkPortIdx"))
    features = item.get("features") if isinstance(item.get("features"), (dict, list)) else None
    kind = _clean(item.get("type")) or ""

    def _feature_flag(key: str) -> bool:
        # Integration v1 returns features as a list (e.g. ["accessPoint"]) in the
        # list payload and as a dict whose keys are the flags in the detail
        # payload (e.g. {"accessPoint": {}}). Detect by key presence, not value
        # truthiness: {"accessPoint": {}} is a flag even though the dict is empty.
        if isinstance(features, list):
            return key in features
        if isinstance(features, dict):
            return key in features
        return False

    if _feature_flag("switching") or kind.lower() in {"switch", "usw", "sw"}:
        category = "unifi_switch"
    elif _feature_flag("accessPoint") or kind.lower() in {"ap", "uap"}:
        category = "unifi_ap"
    elif kind.lower() in {"gateway", "ugw", "udm"} or _feature_flag("gateway"):
        category = "unifi_gateway"
    else:
        category = "unifi_device"
    serial = _clean(item.get("serialNumber") or item.get("serial"))
    return NormalizedInventoryNode(
        source_id=source_id,
        name=name,
        mac=mac,
        ip_address=_safe_ip(item.get("ipAddress") or item.get("ip")),
        model=_clean(item.get("model")),
        category=category,
        state=_clean(item.get("state")),
        firmware=_clean(item.get("firmwareVersion")),
        uplink_source_id=uplink_id,
        source="unifi_inventory",
        serial=serial,
        identifiers={key: value for key, value in {"source_id": source_id, "serial": serial}.items() if value},
        uplink_port_idx=uplink_port,
    )


def parse_device_list(payload: Any) -> list[NormalizedInventoryNode]:
    nodes: list[NormalizedInventoryNode] = []
    for item in _items(payload):
        node = parse_device_payload(item)
        if node is not None:
            nodes.append(node)
    return nodes


def parse_device_interfaces(item: Any) -> list[NormalizedInterface]:
    if not isinstance(item, dict):
        return []
    interfaces_obj = item.get("interfaces")
    if not isinstance(interfaces_obj, dict):
        return []
    ports = interfaces_obj.get("ports")
    if not isinstance(ports, list):
        return []
    results: list[NormalizedInterface] = []
    for port in ports:
        if not isinstance(port, dict):
            continue
        idx = port.get("idx")
        if idx is None:
            continue
        name = _clean(port.get("name")) or f"port-{idx}"
        connector = _clean(port.get("connector"))
        state = _clean(port.get("state"))
        results.append(
            NormalizedInterface(
                name=name,
                if_type=connector,
                oper_status=state,
                source="unifi_interface",
                owner_source_id=_clean(item.get("id")),
                description=_clean(port.get("description")),
                mac=_safe_mac(port.get("macAddress") or port.get("mac")),
                identifiers={"port_idx": str(idx)},
                evidence={
                    key: port.get(key)
                    for key in ("connector", "idx", "maxSpeedMbps", "poe", "speedMbps", "state")
                    if port.get(key) is not None
                },
            )
        )
    return results


def topology_from_inventory(node: NormalizedInventoryNode) -> Optional[NormalizedTopologyLink]:
    if not node.uplink_source_id:
        return None
    return NormalizedTopologyLink(
        local_mac=node.mac,
        local_source_id=node.source_id,
        remote_source_id=node.uplink_source_id,
        remote_interface=f"port-{node.uplink_port_idx}" if node.uplink_port_idx else None,
        remote_identity=None,
        protocol="unifi_uplink",
        source="unifi_uplink",
        observed_at=node.observed_at,
    )


def _items(payload: Any) -> list[Any]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return data
        offset_data = payload.get("offset")
        if isinstance(payload.get("data"), list):
            return payload["data"]
        if offset_data is not None and isinstance(payload.get("data"), list):
            return payload["data"]
    return []


def _clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_mac(value: Any) -> Optional[str]:
    raw = _clean(value)
    if not raw:
        return None
    try:
        return normalize_mac(raw)
    except ValueError:
        return None


def _safe_ip(value: Any) -> Optional[str]:
    raw = _clean(value)
    if not raw:
        return None
    try:
        return normalize_ip(raw)
    except ValueError:
        return None
