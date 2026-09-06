"""Hermetic tests for OpenSshInteractiveTransport prompt/strip logic.

No real network: only the pure helper functions are exercised (prompt
recognition and output stripping), mirroring how the other transports are
unit-tested.
"""

from __future__ import annotations

import pytest

from collectors.common.secrets import DeviceSecrets
from collectors.common.transport_openssh_interactive import (
    _decode,
    _looks_like_prompt,
    _pager_continuation,
    OpenSshInteractiveTransport,
)


@pytest.fixture()
def secrets() -> DeviceSecrets:
    return DeviceSecrets(
        host="192.0.2.203",
        username="oltadmin",
        password="placeholder_test_pw",
        port=22,
        protocol="ssh",
    )


def test_looks_like_prompt_g8():
    assert _looks_like_prompt("MAC-Address  VID\nG8>")
    assert _looks_like_prompt("...rows...\nG8>")
    assert not _looks_like_prompt("MAC-Address  VID  ONT-ID")
    assert not _looks_like_prompt("")  # empty -> no prompt


def test_looks_like_prompt_generic_routeros():
    assert _looks_like_prompt("[admin@mk] >")
    assert not _looks_like_prompt("login as:")


def test_pager_continuation_detects_g08_pager():
    assert _pager_continuation(
        "...press ENTER to next line, CTRL+C to stop..."
    ) is not None
    assert _pager_continuation("MAC-Address ...  without pager marker") is None


def test_strip_output_keeps_rows_and_drops_echo_and_prompt(secrets):
    t = OpenSshInteractiveTransport(secrets, timeout_sec=5)
    raw = (
        "show ont mac-address-table interface gpon all\n"
        "MAC-Address        VID  ONT-ID\n"
        "AA:BB:CC:00:00:01  100  0/2/23\n"
        "AA:BB:CC:00:00:02  100  0/1/9\n"
        "G8>"
    )
    out = t._strip_output(raw, "show ont mac-address-table interface gpon all")
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert "AA:BB:CC:00:00:01  100  0/2/23" in out
    assert "show ont mac-address-table" not in out
    assert "G8>" not in out
    assert len(lines) == 3  # header + 2 rows


def test_strip_output_drops_inline_pager_marker(secrets):
    t = OpenSshInteractiveTransport(secrets, timeout_sec=5)
    raw = (
        "MAC-Address        VID  ONT-ID\n"
        "AA:BB:CC:00:00:01  100  0/2/23\n"
        "....press ENTER to next line, other key to next page....AA:BB:CC:00:00:02  100  0/1/9\n"
        "G8>"
    )
    out = t._strip_output(raw, "cmd")
    # pager marker removed, pager-fragment (dots) removed, both rows preserved
    assert "press ENTER" not in out
    assert "AA:BB:CC:00:00:01  100  0/2/23" in out
    assert "AA:BB:CC:00:00:02  100  0/1/9" in out
    assert set(out.splitlines()[1]) <= set(".: 0123456789abcdef") or len(out.splitlines()) == 3


def test_decode_strips_ansi_and_carriage_returns():
    assert _decode(b"\x1b[24;1Habc\r\ndef") == "abc\ndef"