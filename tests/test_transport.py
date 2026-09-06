from pathlib import Path

import pytest

from collectors.common.transport import (
    MemoryTransport,
    ReadOnlyTransport,
    ReadOnlyViolation,
    TransportError,
    sanitize_error,
)
from collectors.intelbras_g08.collector import IntelbrasG08Collector
from collectors.intelbras_g08.readonly import (
    G08_MAC_TABLE_COMMAND,
    G08_ONT_BRIEF_COMMAND,
    G08_READ_ALLOWLIST,
)
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
    assert inner.calls == []


@pytest.mark.parametrize(
    "cmd",
    [
        "/system identity print ; /system reboot",
        "/system identity print\n/system reboot",
        "/ip arp print detail && /system reboot",
        "/ip arp print detail || /system reboot",
        "/ip arp print detail | /system reboot",
        "/ip arp print detail # comment",
        "/ip arp print detail { /system reboot }",
        "/ip arp print detail;/system reboot",
        "/ip arp print detail without-paging extra",
        "/ip arp print detail where address=10.0.0.1",
    ],
)
def test_readonly_rejects_command_chaining_and_suffixes(cmd):
    inner = MemoryTransport(
        {
            "/system identity print": "ok",
            "/ip arp print detail": "ok",
            cmd: "should-not-run",
        }
    )
    guarded = ReadOnlyTransport(inner, MIKROTIK_READ_ALLOWLIST)
    with pytest.raises(ReadOnlyViolation):
        guarded.execute(cmd)
    assert inner.calls == []


def test_readonly_allows_explicit_without_paging():
    inner = MemoryTransport(
        {"/ip dhcp-server lease print detail without-paging": "ok"}
    )
    guarded = ReadOnlyTransport(inner, MIKROTIK_READ_ALLOWLIST)
    result = guarded.execute("/ip dhcp-server lease print detail without-paging")
    assert result.ok
    assert inner.calls == ["/ip dhcp-server lease print detail without-paging"]


def test_g08_readonly_rejects_suffix_on_mac_table():
    inner = MemoryTransport({})
    guarded = ReadOnlyTransport(inner, G08_READ_ALLOWLIST)
    with pytest.raises(ReadOnlyViolation):
        guarded.execute("show ont mac-address-table interface gpon all ; reboot")
    assert inner.calls == []


def test_sanitize_error_redacts_quoted_and_json_secrets():
    quoted = sanitize_error('auth failed community="alpha beta gamma" extra')
    assert "alpha" not in quoted
    assert "<REDACTED>" in quoted
    colon = sanitize_error("login failed token: alpha beta gamma")
    assert "alpha" not in colon
    assert "gamma" not in colon
    nested = sanitize_error('{"token": "alpha beta", "host": "10.30.9.9"}')
    assert "alpha" not in nested
    assert "<REDACTED>" in nested
    assert "<IP>" in nested


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
        "/ip neighbor print detail": (FIX / "mikrotik_neighbors.txt").read_text(),
    }
    errors = {
        "/interface bridge host print detail": "timeout",
    }
    transport = MemoryTransport(outputs, errors=errors)
    collector = MikroTikCollector("env", "EXAMPLE", transport=transport)
    result = collector.collect_via_transport(transport, lightweight=True)
    assert result.meta["completeness"] == "partial"
    assert result.meta["status"] == "partial"
    assert result.meta["commands_ok"] == 4
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
    inner = MemoryTransport(
        {"show ont mac-address-table interface gpon all": "ONT ID MAC\n0/1/14 AA:BB:CC:DD:EE:FF"}
    )
    guarded = ReadOnlyTransport(inner, G08_READ_ALLOWLIST)
    result = guarded.execute("show ont mac-address-table interface gpon all")
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


def test_mikrotik_dhcp_partial_parse():
    transport = MemoryTransport(
        {"/ip dhcp-server lease print detail without-paging": (FIX / "mikrotik_dhcp_partial.txt").read_text()}
    )
    result = MikroTikCollector("env", "EXAMPLE").collect_via_transport(transport, dhcp_only=True)
    assert result.meta["completeness"] == "partial"
    assert result.meta["status"] == "partial"
    assert result.meta["parse_failures"] == 1
    assert len(result.dhcp) == 1


def test_mikrotik_command_failure_is_error():
    transport = MemoryTransport(
        {},
        errors={"/ip dhcp-server lease print detail without-paging": "syntax error"},
    )
    result = MikroTikCollector("env", "EXAMPLE").collect_via_transport(transport, dhcp_only=True)
    assert result.meta["status"] == "error"
    assert result.meta["completeness"] == "none"
    assert result.meta["commands_failed"] == 1
    assert "syntax error" in (result.meta.get("error_summary") or "")


def test_mikrotik_dhcp_only():
    transport = MemoryTransport(
        {"/ip dhcp-server lease print detail without-paging": (FIX / "mikrotik_dhcp.txt").read_text()}
    )
    collector = MikroTikCollector("env", "EXAMPLE")
    result = collector.collect_via_transport(transport, dhcp_only=True)
    assert result.meta["completeness"] == "complete"
    assert len(result.dhcp) == 2
    assert result.arp == []


def test_g08_driver_uses_table_command_only():
    from collectors.intelbras_g08.collector import IntelbrasG08Collector
    from collectors.intelbras_g08.readonly import G08_MAC_TABLE_COMMAND

    transport = MemoryTransport(
        {G08_MAC_TABLE_COMMAND: (FIX / "g08_mac_vid_table.txt").read_text()}
    )
    result = IntelbrasG08Collector("env", "EXAMPLE").collect_via_transport(transport)
    assert result.meta["status"] == "ok"
    assert result.meta["command"] == G08_MAC_TABLE_COMMAND
    assert transport.calls == [G08_MAC_TABLE_COMMAND]
    assert len(result.olt_macs) == 2


def test_g08_driver_collects_enabled_mac_and_brief_commands():
    transport = MemoryTransport(
        {
            G08_MAC_TABLE_COMMAND: (FIX / "g08_mac_vid_table.txt").read_text(),
            G08_ONT_BRIEF_COMMAND: (FIX / "g08_ont_brief.txt").read_text(),
        }
    )

    result = IntelbrasG08Collector("env", "EXAMPLE").collect_via_transport(
        transport, enabled_collectors=frozenset({"ont_mac_table", "ont_brief"})
    )

    assert transport.calls == [G08_MAC_TABLE_COMMAND, G08_ONT_BRIEF_COMMAND]
    assert result.meta["status"] == "ok"
    assert result.meta["completeness"] == "complete"
    assert {(onu.ont_id, onu.status, onu.profile_name) for onu in result.onus} == {
        ("0/1/14", "online", "CORPORATIVO"),
        ("0/1/15", "offline", "HOME"),
        ("0/2/3", "online", "R1v2"),
    }


def test_g08_driver_collects_brief_only_when_enabled():
    transport = MemoryTransport({G08_ONT_BRIEF_COMMAND: (FIX / "g08_ont_brief.txt").read_text()})

    result = IntelbrasG08Collector("env", "EXAMPLE").collect_via_transport(
        transport, enabled_collectors=frozenset({"ont_brief"})
    )

    assert transport.calls == [G08_ONT_BRIEF_COMMAND]
    assert result.meta["status"] == "ok"
    assert result.meta["completeness"] == "complete"
    assert len(result.onus) == 3
    assert result.olt_macs == []


def test_g08_duplicate_service_serial_variant_is_complete():
    result = IntelbrasG08Collector("env", "EXAMPLE").collect_from_texts(
        mac_table_text="""\
MAC-Address         VID  ONT-ID  SN            ID/GEM
AA-BB-CC-DD-EE-FF  30   0/1/14  TEST-12345678  1/128
AA-BB-CC-DD-EE-FF  30   0/1/14  TEST-87654321  1/128
Total entries: 2
"""
    )

    assert len(result.olt_macs) == 1
    assert result.meta["parse_failures"] == 0
    assert result.meta["completeness"] == "complete"


def test_g08_declared_total_smaller_than_parseable_rows_is_partial():
    result = IntelbrasG08Collector("env", "EXAMPLE").collect_from_texts(
        mac_table_text="""\
MAC-Address         VID  ONT-ID  SN            ID/GEM
AA-BB-CC-DD-EE-FF  30   0/1/14  TEST-12345678  1/128
11-22-33-44-55-66 40   0/1/15  TEST-87654321  2/129
Total entries: 1
"""
    )

    assert result.meta["parse_failures"] == 1
    assert result.meta["completeness"] == "partial"


def test_g08_collect_via_transport():
    from collectors.intelbras_g08.collector import IntelbrasG08Collector

    transport = MemoryTransport(
        {"show ont mac-address-table interface gpon all": (FIX / "g08_mac_address.txt").read_text()}
    )
    collector = IntelbrasG08Collector("env", "EXAMPLE")
    result = collector.collect_via_transport(transport)
    assert result.meta["status"] == "ok"
    assert len(result.olt_macs) == 2
    assert result.olt_macs[0].source == "olt"
    assert result.onus


def test_enabled_collectors_skips_other_commands():
    transport = MemoryTransport({"/ip arp print detail": (FIX / "mikrotik_arp.txt").read_text()})
    result = MikroTikCollector("env", "EXAMPLE").collect_via_transport(
        transport, lightweight=True, enabled_collectors=frozenset({"arp"})
    )
    assert transport.calls == ["/ip arp print detail"]
    assert result.arp
    assert result.dhcp == []
