"""UniFi Network Integration API parsers and collector (synthetic fixtures)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from collectors.common.transport import ReadOnlyViolation, TransportError, sanitize_error
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


def _fake_httpx(monkeypatch, captured: dict):
    class FakeClient:
        def __init__(self, timeout=None, verify=True):
            captured["verify"] = verify

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url, params=None, headers=None):
            class Resp:
                status_code = 200

                def json(self):
                    return {"applicationVersion": "10.4.57"}

            return Resp()

    monkeypatch.setattr("collectors.unifi.transport_http.httpx.Client", FakeClient)


def test_unifi_tls_default_verifies():
    from collectors.common.secrets import DeviceSecrets
    from collectors.unifi.transport_http import tls_client_verify, tls_verify_setting

    secrets = DeviceSecrets(base_url="https://unifi.example.invalid/integration", api_key="k")
    assert tls_verify_setting(secrets) is True
    assert tls_client_verify(secrets) is True
    unset = DeviceSecrets(
        base_url="https://unifi.example.invalid/integration",
        api_key="k",
        verify_tls=True,
    )
    assert tls_verify_setting(unset) is True


def test_unifi_tls_uses_ca_file_when_verification_on(tmp_path, monkeypatch):
    from collectors.common.secrets import DeviceSecrets, resolve_secrets
    from collectors.unifi.transport_http import UnifiHttpClient, tls_verify_setting

    ca = tmp_path / "unifi-ca.pem"
    ca.write_text("-----BEGIN CERTIFICATE-----\nMIIBsynthetic\n-----END CERTIFICATE-----\n", encoding="utf-8")
    secrets = DeviceSecrets(
        base_url="https://unifi.example.invalid/integration",
        api_key="k",
        verify_tls=True,
        tls_ca_file=str(ca),
    )
    assert tls_verify_setting(secrets) == str(ca)
    captured: dict = {}
    _fake_httpx(monkeypatch, captured)
    UnifiHttpClient(secrets).get_json("/v1/info")
    assert captured["verify"] == str(ca)
    assert captured["verify"] is not False

    monkeypatch.setenv("U_API_KEY", "k")
    monkeypatch.setenv("U_BASE_URL", "https://unifi.example.invalid/integration")
    monkeypatch.setenv("NI_TLS_CA_FILE", str(ca))
    resolved = resolve_secrets("env", "U")
    assert resolved is not None
    assert resolved.verify_tls is True
    assert resolved.tls_ca_file == str(ca)
    assert tls_verify_setting(resolved) == str(ca)


def test_unifi_tls_verify_false_only_when_explicit(tmp_path, monkeypatch, caplog):
    from collectors.common.secrets import DeviceSecrets, resolve_secrets
    from collectors.unifi.transport_http import (
        TLS_VERIFY_DISABLED_WARNING,
        UnifiHttpClient,
        tls_client_verify,
        tls_verify_setting,
    )

    ca = tmp_path / "unifi-ca.pem"
    ca.write_text("-----BEGIN CERTIFICATE-----\nMIIBsynthetic\n-----END CERTIFICATE-----\n", encoding="utf-8")
    secrets = DeviceSecrets(
        base_url="https://unifi.example.invalid/integration",
        api_key="k",
        verify_tls=False,
        tls_ca_file=str(ca),
        tls_server_name="unifi.example.invalid",
    )
    assert tls_verify_setting(secrets) is False
    assert tls_client_verify(secrets) is False
    captured: dict = {}
    _fake_httpx(monkeypatch, captured)
    with caplog.at_level("WARNING", logger="collectors.unifi.transport_http"):
        UnifiHttpClient(secrets).get_json("/v1/info")
    assert captured["verify"] is False
    assert TLS_VERIFY_DISABLED_WARNING in caplog.text
    assert "unifi.example.invalid" not in caplog.text
    assert "integration" not in caplog.text
    assert "api_key" not in caplog.text.lower()
    assert "X-API-Key" not in caplog.text

    monkeypatch.setenv("U_API_KEY", "k")
    monkeypatch.setenv("U_BASE_URL", "https://unifi.example.invalid/integration")
    monkeypatch.setenv("U_VERIFY_TLS", "false")
    monkeypatch.setenv("NI_TLS_CA_FILE", str(ca))
    monkeypatch.setenv("U_TLS_SERVER_NAME", "unifi.example.invalid")
    resolved = resolve_secrets("env", "U")
    assert resolved is not None
    assert resolved.verify_tls is False
    assert tls_verify_setting(resolved) is False
    assert tls_client_verify(resolved) is False


def test_unifi_tls_server_name_pins_certificate_hostname():
    import ssl

    from collectors.common.secrets import DeviceSecrets
    from collectors.unifi.transport_http import attach_tls_server_name, tls_client_verify

    ctx = ssl.create_default_context()
    seen: dict = {}

    def spy(sock, *args, server_hostname=None, **kwargs):
        seen["server_hostname"] = server_hostname
        raise OSError("stop")

    ctx.wrap_socket = spy  # type: ignore[method-assign]
    attach_tls_server_name(ctx, "unifi.example.invalid")
    try:
        ctx.wrap_socket(object(), server_hostname="10.30.9.9")
    except OSError:
        pass
    assert seen["server_hostname"] == "unifi.example.invalid"
    assert ctx.check_hostname is True
    assert ctx.verify_mode == ssl.CERT_REQUIRED

    secrets = DeviceSecrets(
        base_url="https://10.30.9.9/integration",
        api_key="k",
        tls_server_name="unifi.example.invalid",
    )
    verify = tls_client_verify(secrets)
    assert verify is not False
    assert isinstance(verify, ssl.SSLContext)


def test_unifi_tls_server_name_rejects_ip_when_verifying():
    from collectors.common.secrets import DeviceSecrets
    from collectors.unifi.transport_http import tls_client_verify

    bad = DeviceSecrets(
        base_url="https://10.30.9.9/integration",
        api_key="k",
        tls_server_name="10.30.9.9",
    )
    with pytest.raises(TransportError) as exc:
        tls_client_verify(bad)
    assert "server name" in str(exc.value).lower()


def test_unifi_tls_server_name_from_env_and_httpx(monkeypatch):
    import ssl

    from collectors.common.secrets import resolve_secrets
    from collectors.unifi.transport_http import UnifiHttpClient

    monkeypatch.setenv("U_API_KEY", "k")
    monkeypatch.setenv("U_BASE_URL", "https://10.30.9.9/integration")
    monkeypatch.setenv("U_TLS_SERVER_NAME", "unifi.example.invalid")
    resolved = resolve_secrets("env", "U")
    assert resolved is not None
    assert resolved.tls_server_name == "unifi.example.invalid"
    assert resolved.verify_tls is True

    captured: dict = {}
    _fake_httpx(monkeypatch, captured)
    UnifiHttpClient(resolved).get_json("/v1/info")
    assert captured["verify"] is not False
    assert isinstance(captured["verify"], ssl.SSLContext)


def test_unifi_tls_missing_ca_file_is_config_error(tmp_path):
    from collectors.common.secrets import DeviceSecrets
    from collectors.unifi.transport_http import tls_verify_setting

    secrets = DeviceSecrets(
        base_url="https://unifi.example.invalid/integration",
        api_key="k",
        tls_ca_file=str(tmp_path / "missing.pem"),
    )
    with pytest.raises(TransportError) as exc:
        tls_verify_setting(secrets)
    assert "tls ca" in str(exc.value).lower()


def test_verify_tls_false_is_unifi_http_only():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "collectors"
    offenders = []
    for path in root.rglob("*.py"):
        if path.as_posix().endswith("collectors/unifi/transport_http.py"):
            continue
        text = path.read_text(encoding="utf-8")
        if "verify=False" in text or "verify = False" in text:
            offenders.append(str(path.relative_to(root.parent)))
    assert offenders == []
