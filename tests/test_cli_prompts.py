"""CLI prompt classifiers — no live devices, no secrets."""

import pytest

from collectors.common.cli_interactive import (
    AUTH_FAIL,
    PASSWORD_PROMPT,
    USERNAME_PROMPT,
    InteractiveCliTransport,
    looks_like_device_prompt,
    pager_continuation,
)
from collectors.common.secrets import DeviceSecrets


def test_g08_username_prompt():
    assert USERNAME_PROMPT.search("Username(1-64 chars):")
    assert USERNAME_PROMPT.search("\nUsername(1-64 chars):")
    assert not USERNAME_PROMPT.search("Username or password error")


def test_g08_password_prompt():
    assert PASSWORD_PROMPT.search("Password(1-96 chars):")
    assert PASSWORD_PROMPT.search("Password:")
    assert not PASSWORD_PROMPT.search("Username or password error")


def test_g08_device_prompt():
    assert looks_like_device_prompt("G8>")
    assert looks_like_device_prompt("banner\nG8#")
    assert looks_like_device_prompt("[admin@LAB] >")
    assert not looks_like_device_prompt("Username(1-64 chars):")


def test_g08_auth_fail():
    assert AUTH_FAIL.search("Username or password error")


def test_g08_pager_sends_enter():
    key = pager_continuation("rows...\npress ENTER to next line, CTRL+C to stop")
    assert key == "\r\n"


def test_g08_strip_cli_preserves_row_joined_to_pager_prompt():
    transport = InteractiveCliTransport(
        DeviceSecrets(host="192.0.2.10", username="<USERNAME>", password="<PASSWORD>")
    )
    command = "show ont mac-address-table interface gpon all"
    text = (
        f"{command}\n"
        "AA-BB-CC-DD-EE-FF 30 0/1/14 ALCL12345678 1/128"
        "press ENTER to next line, CTRL+C to stop\n"
        "11-22-33-44-55-66 40 0/1/15 ALCL87654321 1/129\n"
        "G8>\n"
    )

    cleaned = transport._strip_cli(text, command)

    assert cleaned.splitlines() == [
        "AA-BB-CC-DD-EE-FF 30 0/1/14 ALCL12345678 1/128",
        "11-22-33-44-55-66 40 0/1/15 ALCL87654321 1/129",
    ]
    assert "press ENTER" not in cleaned
    assert "CTRL+C" not in cleaned


@pytest.mark.parametrize(
    "prompt",
    [
        "Press any key to continue",
        "-- More -- (q to quit)",
    ],
)
def test_strip_cli_removes_standalone_pager_prompt(prompt):
    transport = InteractiveCliTransport(
        DeviceSecrets(host="192.0.2.10", username="<USERNAME>", password="<PASSWORD>")
    )

    cleaned = transport._strip_cli(f"{prompt}\n", "show data")

    assert cleaned == "\n"


@pytest.mark.parametrize(
    "prompt",
    [
        "Press any key to continue",
        "-- More -- (q to quit)",
    ],
)
def test_strip_cli_preserves_row_joined_to_generic_pager_prompt(prompt):
    transport = InteractiveCliTransport(
        DeviceSecrets(host="192.0.2.10", username="<USERNAME>", password="<PASSWORD>")
    )

    cleaned = transport._strip_cli(f"ROW DATA{prompt}\n", "show data")

    assert cleaned == "ROW DATA\n"


def test_strip_cli_separates_rows_around_inline_pager_prompt():
    transport = InteractiveCliTransport(
        DeviceSecrets(host="192.0.2.10", username="<USERNAME>", password="<PASSWORD>")
    )
    prompt = "press ENTER to next line, CTRL+C to stop"

    cleaned = transport._strip_cli(f"ROW ONE{prompt}ROW TWO\n", "show data")

    assert cleaned.splitlines() == ["ROW ONE", "ROW TWO"]


def test_ssh_reader_answers_each_pager_prompt_only_once(monkeypatch):
    class FakeChannel:
        def __init__(self):
            self.chunks = [
                b"show data\nROW ONEpress ENTER to next line, CTRL+C to stop",
                b"ROW TWO\nG8>\n",
            ]
            self.sent = []

        def recv_ready(self):
            return bool(self.chunks)

        def recv(self, _size):
            return self.chunks.pop(0)

        def send(self, payload):
            self.sent.append(payload)

    monkeypatch.setattr("collectors.common.cli_interactive.time.sleep", lambda _seconds: None)
    transport = InteractiveCliTransport(
        DeviceSecrets(host="192.0.2.10", username="<USERNAME>", password="<PASSWORD>")
    )
    channel = FakeChannel()

    cleaned = transport._read_until_prompt(channel, echo="show data")

    assert channel.sent == ["\r\n"]
    assert cleaned.splitlines() == ["ROW ONE", "ROW TWO"]


def test_telnet_reader_answers_each_pager_prompt_only_once(monkeypatch):
    class FakeTelnet:
        def __init__(self):
            self.chunks = [
                b"show data\nROW ONEpress ENTER to next line, CTRL+C to stop",
                b"ROW TWO\nG8>\n",
            ]
            self.written = []

        def read_very_eager(self):
            return self.chunks.pop(0) if self.chunks else b""

        def write(self, payload):
            self.written.append(payload)

    ticks = iter([0, 1, 2, 3, 200])
    monkeypatch.setattr("collectors.common.cli_interactive.time.time", lambda: next(ticks))
    monkeypatch.setattr("collectors.common.cli_interactive.time.sleep", lambda _seconds: None)
    transport = InteractiveCliTransport(
        DeviceSecrets(host="192.0.2.10", username="<USERNAME>", password="<PASSWORD>"),
        timeout_sec=100,
    )
    telnet = FakeTelnet()

    cleaned = transport._telnet_read_until_prompt(telnet, echo="show data")

    assert telnet.written == [b"\r\n"]
    assert cleaned.splitlines() == ["ROW ONE", "ROW TWO"]


def test_ssh_reader_waits_for_complete_fragmented_pager_marker(monkeypatch):
    class FakeChannel:
        def __init__(self):
            self.chunks = [
                b"show data\nROW ONEpress ENTER to next ",
                b"line, CTRL+C to stopROW TWO\nG8>\n",
            ]
            self.sent = []

        def recv_ready(self):
            return bool(self.chunks)

        def recv(self, _size):
            return self.chunks.pop(0)

        def send(self, payload):
            self.sent.append(payload)

    monkeypatch.setattr("collectors.common.cli_interactive.time.sleep", lambda _seconds: None)
    transport = InteractiveCliTransport(
        DeviceSecrets(host="192.0.2.10", username="<USERNAME>", password="<PASSWORD>")
    )

    cleaned = transport._read_until_prompt(FakeChannel(), echo="show data")

    assert cleaned.splitlines() == ["ROW ONE", "ROW TWO"]


def test_telnet_reader_waits_for_complete_fragmented_pager_marker(monkeypatch):
    class FakeTelnet:
        def __init__(self):
            self.chunks = [
                b"show data\nROW ONEpress ENTER to next ",
                b"line, CTRL+C to stopROW TWO\nG8>\n",
            ]
            self.written = []

        def read_very_eager(self):
            return self.chunks.pop(0) if self.chunks else b""

        def write(self, payload):
            self.written.append(payload)

    ticks = iter([0, 1, 2, 3, 200])
    monkeypatch.setattr("collectors.common.cli_interactive.time.time", lambda: next(ticks))
    monkeypatch.setattr("collectors.common.cli_interactive.time.sleep", lambda _seconds: None)
    transport = InteractiveCliTransport(
        DeviceSecrets(host="192.0.2.10", username="<USERNAME>", password="<PASSWORD>"),
        timeout_sec=100,
    )

    cleaned = transport._telnet_read_until_prompt(FakeTelnet(), echo="show data")

    assert cleaned.splitlines() == ["ROW ONE", "ROW TWO"]


def test_ssh_reader_waits_for_fragmented_pager_suffix(monkeypatch):
    class FakeChannel:
        def __init__(self):
            self.chunks = [
                b"show data\nROW ONEpress ENTER to next line",
                b", CTRL+C to stopROW TWO\nG8>\n",
            ]

        def recv_ready(self):
            return bool(self.chunks)

        def recv(self, _size):
            return self.chunks.pop(0)

        def send(self, _payload):
            pass

    monkeypatch.setattr("collectors.common.cli_interactive.time.sleep", lambda _seconds: None)
    transport = InteractiveCliTransport(
        DeviceSecrets(host="192.0.2.10", username="<USERNAME>", password="<PASSWORD>")
    )

    cleaned = transport._read_until_prompt(FakeChannel(), echo="show data")

    assert cleaned.splitlines() == ["ROW ONE", "ROW TWO"]


def test_telnet_reader_waits_for_fragmented_pager_suffix(monkeypatch):
    class FakeTelnet:
        def __init__(self):
            self.chunks = [
                b"show data\nROW ONEpress ENTER to next line",
                b", CTRL+C to stopROW TWO\nG8>\n",
            ]

        def read_very_eager(self):
            return self.chunks.pop(0) if self.chunks else b""

        def write(self, _payload):
            pass

    ticks = iter([0, 1, 2, 3, 200])
    monkeypatch.setattr("collectors.common.cli_interactive.time.time", lambda: next(ticks))
    monkeypatch.setattr("collectors.common.cli_interactive.time.sleep", lambda _seconds: None)
    transport = InteractiveCliTransport(
        DeviceSecrets(host="192.0.2.10", username="<USERNAME>", password="<PASSWORD>"),
        timeout_sec=100,
    )

    cleaned = transport._telnet_read_until_prompt(FakeTelnet(), echo="show data")

    assert cleaned.splitlines() == ["ROW ONE", "ROW TWO"]
