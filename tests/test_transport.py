from pathlib import Path

import pytest

from collectors.common.transport import (
    MemoryTransport,
    ReadOnlyTransport,
    ReadOnlyViolation,
    TransportError,
    sanitize_error,
)
from collectors.intelbras_g08.readonly import G08_READ_ALLOWLIST
from collectors.mikrotik.collector import MikroTikCollector
from collectors.mikrotik.readonly import MIKROTIK_READ_ALLOWLIST
from collectors.mikrotik.transport_api import (
    cli_command_to_api,
    encode_length,
    encode_sentence,
    sentences_to_print_text,
)

FIX = Path(__file__).parent / "fixtures"


def test_readonly_allows_print():
    inner = MemoryTransport({"/ip arp print detail": "ok"})
    guarded = ReadOnlyTransport(inner, MIKROTIK_READ_ALLOWLIST)
    result = guarded.execute("/ip arp print detail")
    assert result.ok
    assert result.stdout == "ok"


@pytest.mark.parametrize(
    "cmd",
    [
        "/ip arp add address=10.0.0.1",
        "/interface set ether1 disabled=yes",
        "/ip dhcp-server lease remove 0",
        "/interface enable ether1",
        "/interface disable ether1",
        "/interface bridge port move 0 destination=1",
    ],
)
def test_readonly_refuses_mutations(cmd):
    inner = MemoryTransport({})
    guarded = ReadOnlyTransport(inner, MIKROTIK_READ_ALLOWLIST)
    with pytest.raises(ReadOnlyViolation):
        guarded.execute(cmd)
    assert inner.calls == []


def test_readonly_refuses_unknown_read():
    inner = MemoryTransport({"/foo print": "nope"})
    guarded = ReadOnlyTransport(inner, MIKROTIK_READ_ALLOWLIST)
    with pytest.raises(ReadOnlyViolation):
        guarded.execute("/system reboot")


def test_sanitize_error_redacts_password():
    assert "<REDACTED>" in sanitize_error("login failed password=super-secret-value host=x")


def test_sanitize_error_redacts_mac_and_sql():
    text = sanitize_error(
        'duplicate key (tenant_id, mac)=(abc, AA:BB:CC:DD:EE:FF) already exists.\n'
        '[SQL: INSERT INTO mac_addresses (mac) VALUES (%(mac__0)s)]'
    )
    assert "AA:BB:CC:DD:EE:FF" not in text
    assert "<MAC>" in text
    assert "INSERT" not in text


def test_collect_via_transport_partial():
    outputs = {
        "/system identity print": (FIX / "mikrotik_identity.txt").read_text(),
        "/ip arp print detail": (FIX / "mikrotik_arp.txt").read_text(),
        "/ip dhcp-server lease print detail": (FIX / "mikrotik_dhcp.txt").read_text(),
    }
    errors = {
        "/interface bridge host print detail": "timeout",
    }
    transport = MemoryTransport(outputs, errors=errors)
    collector = MikroTikCollector("env", "EXAMPLE", transport=transport)
    result = collector.collect_via_transport(transport, lightweight=True)
    assert result.meta["completeness"] == "partial"
    assert result.meta["status"] == "partial"
    assert result.meta["commands_ok"] == 3
    assert result.meta["commands_failed"] == 1
    assert result.dhcp
    assert result.arp
    assert result.fdb == []


def test_collect_via_transport_complete_full():
    outputs = {
        "/system identity print": (FIX / "mikrotik_identity.txt").read_text(),
        "/ip arp print detail": (FIX / "mikrotik_arp.txt").read_text(),
        "/ip dhcp-server lease print detail": (FIX / "mikrotik_dhcp.txt").read_text(),
        "/interface bridge host print detail": (FIX / "mikrotik_fdb.txt").read_text(),
        "/system resource print": "version=7.15",
        "/interface print detail": (FIX / "mikrotik_interfaces.txt").read_text(),
        "/ip neighbor print detail": (FIX / "mikrotik_neighbors.txt").read_text(),
    }
    transport = MemoryTransport(outputs)
    collector = MikroTikCollector("env", "EXAMPLE")
    result = collector.collect_via_transport(transport, lightweight=False)
    assert result.meta["completeness"] == "complete"
    assert result.identity is not None
    assert result.identity.name == "LAB-ROUTER"
    assert len(result.interfaces) == 3
    assert len(result.neighbors) == 2


def test_g08_readonly_refuses_config():
    inner = MemoryTransport({})
    guarded = ReadOnlyTransport(inner, G08_READ_ALLOWLIST)
    with pytest.raises(ReadOnlyViolation):
        guarded.execute("configure terminal")
    with pytest.raises(ReadOnlyViolation):
        guarded.execute("enable")
    assert inner.calls == []


def test_g08_readonly_allows_show_mac():
    inner = MemoryTransport({"show ont mac-address": "ONT ID MAC\n0/1/14 AA:BB:CC:DD:EE:FF"})
    guarded = ReadOnlyTransport(inner, G08_READ_ALLOWLIST)
    result = guarded.execute("show ont mac-address")
    assert result.ok


def test_api_cli_mapping_and_print_text():
    assert cli_command_to_api("/ip dhcp-server lease print detail without-paging") == (
        "/ip/dhcp-server/lease/print"
    )
    assert encode_length(0) == b"\x00"
    assert encode_sentence(["/login"])[-1:] == b"\x00"
    text = sentences_to_print_text(
        [
            ["!re", "=mac-address=AA:BB:CC:DD:EE:FF", "=address=10.30.1.50", "=status=bound"],
            ["!done"],
        ]
    )
    assert "mac-address=AA:BB:CC:DD:EE:FF" in text
    assert "address=10.30.1.50" in text


def test_memory_transport_missing_command():
    transport = MemoryTransport({})
    with pytest.raises(TransportError):
        transport.execute("/ip arp print detail")


def test_mikrotik_dhcp_only():
    transport = MemoryTransport(
        {"/ip dhcp-server lease print detail without-paging": (FIX / "mikrotik_dhcp.txt").read_text()}
    )
    collector = MikroTikCollector("env", "EXAMPLE")
    result = collector.collect_via_transport(transport, dhcp_only=True)
    assert result.meta["completeness"] == "complete"
    assert len(result.dhcp) == 2
    assert result.arp == []


def test_g08_login_error_body_is_incomplete_fallback():
    from collectors.intelbras_g08.collector import IntelbrasG08Collector

    transport = MemoryTransport(
        {
            "show ont mac-address": "Username or password error\nUsername(1-64 chars):",
            "show ont mac-address-table interface gpon all": (FIX / "g08_mac_address.txt").read_text(),
        }
    )
    result = IntelbrasG08Collector("env", "EXAMPLE").collect_via_transport(transport)
    assert result.meta["status"] == "ok"
    assert len(result.olt_macs) == 2
    assert transport.calls[0] == "show ont mac-address"
    assert "mac-address-table" in transport.calls[1]


def test_g08_collect_via_transport():
    from collectors.intelbras_g08.collector import IntelbrasG08Collector

    transport = MemoryTransport(
        {"show ont mac-address": (FIX / "g08_mac_address.txt").read_text()}
    )
    collector = IntelbrasG08Collector("env", "EXAMPLE")
    result = collector.collect_via_transport(transport)
    assert result.meta["status"] == "ok"
    assert len(result.olt_macs) == 2
    assert result.olt_macs[0].source == "olt"
    assert result.onus
