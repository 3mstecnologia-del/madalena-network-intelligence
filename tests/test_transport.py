from pathlib import Path

import pytest

from collectors.common.transport import (
    MemoryTransport,
    ReadOnlyTransport,
    ReadOnlyViolation,
    TransportError,
    sanitize_error,
)
from collectors.mikrotik.collector import MikroTikCollector
from collectors.mikrotik.readonly import MIKROTIK_READ_ALLOWLIST

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


def test_memory_transport_missing_command():
    transport = MemoryTransport({})
    with pytest.raises(TransportError):
        transport.execute("/ip arp print detail")
