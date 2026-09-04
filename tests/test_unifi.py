"""UniFi Network Integration API parsers and collector (synthetic fixtures)."""

from __future__ import annotations

import json
from pathlib import Path

from collectors.common.transport import ReadOnlyViolation, sanitize_error
from collectors.unifi.collector import UnifiNetworkCollector
from collectors.unifi.parsers import parse_device_list, parse_device_payload, parse_sites
from collectors.unifi.readonly import unifi_get_allowed
from collectors.unifi.transport_http import MemoryUnifiClient

FIX = Path(__file__).parent / "fixtures"
SITE = "11111111-1111-4111-8111-111111111111"
SW = "22222222-2222-4222-8222-222222222222"
AP = "33333333-3333-4333-8333-333333333333"


def _json(name: str):
    return json.loads((FIX / name).read_text())


def test_unifi_allowlist_get_only():
    assert unifi_get_allowed("/v1/info")
    assert unifi_get_allowed(f"/v1/sites/{SITE}/devices/{SW}")
    assert not unifi_get_allowed(f"/v1/sites/{SITE}/devices/{SW}/actions")
    client = MemoryUnifiClient({})
    try:
        client.get_json("/v1/pending-devices")
        raise AssertionError("write path must be rejected")
    except ReadOnlyViolation:
        pass


def test_parse_unifi_inventory_and_optional_uplink():
    sites = parse_sites(_json("unifi_sites.json"))
    assert sites[0]["id"] == SITE
    listed = parse_device_list(_json("unifi_devices.json"))
    assert {n.mac for n in listed} == {"AA:BB:CC:20:00:01", "AA:BB:CC:20:00:02"}
    ap = parse_device_payload(_json("unifi_device_ap.json"))
    assert ap is not None
    assert ap.uplink_source_id == SW
    assert ap.ip_address == "10.30.2.20"
    isolated = parse_device_payload(_json("unifi_device_ap_no_uplink.json"))
    assert isolated is not None
    assert isolated.uplink_source_id is None


def test_unifi_collector_complete_and_partial(monkeypatch):
    responses = {
        "/v1/info": _json("unifi_info.json"),
        "/v1/sites": _json("unifi_sites.json"),
        f"/v1/sites/{SITE}/devices": _json("unifi_devices.json"),
        f"/v1/sites/{SITE}/devices/{SW}": _json("unifi_device_switch.json"),
        f"/v1/sites/{SITE}/devices/{AP}": _json("unifi_device_ap.json"),
    }
    client = MemoryUnifiClient(responses)
    collector = UnifiNetworkCollector("env", "DEVICE_EXAMPLE_UNIFI", client=client)
    result = collector.collect_via_client(client, site_id=SITE)
    assert result.meta["completeness"] == "complete"
    assert len(result.inventory_nodes) == 2
    assert any(link.remote_source_id == SW for link in result.topology_links)
    assert any(i.name == "port-24" for i in result.interfaces)

    partial_client = MemoryUnifiClient(responses, failures={f"/v1/sites/{SITE}/devices/{AP}"})
    partial = collector.collect_via_client(partial_client, site_id=SITE)
    assert partial.meta["completeness"] == "partial"
    assert partial.inventory_nodes


def test_unifi_error_sanitizes_api_key():
    text = sanitize_error("unifi HTTP 401 api-key=super-secret-unifi-key host=10.30.2.1")
    assert "super-secret-unifi-key" not in text
    assert "<REDACTED>" in text
    assert "10.30.2.1" not in text
