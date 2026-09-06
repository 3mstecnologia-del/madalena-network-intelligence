"""Hermetic tests for the OpenSSH CLI transport (MikroTik banner quirk)."""

from __future__ import annotations

import subprocess

import pytest

from collectors.common.secrets import DeviceSecrets
from collectors.mikrotik.transport_openssh import OpenSshCliTransport


@pytest.fixture()
def secrets() -> DeviceSecrets:
    return DeviceSecrets(
        host="192.0.2.202",
        username="mkadmin",
        password="sekret",
        port=8822,
        protocol="ssh",
    )


def _fake_run_success(**kw):
    return subprocess.CompletedProcess(
        kw.get("args", []), 0,
        stdout=" 0   address=1.2.3.4 mac-address=AA:BB:CC:DD:EE:FF\n",
        stderr="",
    )


@pytest.fixture()
def _sock_open(monkeypatch):
    """Stub socket.create_connection so no real TCP is attempted."""
    import socket

    class _S:
        def close(self):
            pass

    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: _S())


def test_execute_calls_ssh_and_returns_stdout(monkeypatch, secrets, tmp_path, _sock_open):
    called = {}
    kh = tmp_path / "known_hosts"
    kh.write_text("", encoding="utf-8")
    monkeypatch.setenv("NI_SSH_KNOWN_HOSTS", str(kh))

    def fake_run(args, **kw):
        called["args"] = args
        called["askpass"] = kw.get("env", {}).get("SSH_ASKPASS")
        called["passenv"] = kw.get("env", {}).get("SSH_ASKPASS_PASSWORD")
        return subprocess.CompletedProcess(args, 0, stdout="AABB.CCDD.EEFF bridge-lan\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    t = OpenSshCliTransport(secrets, timeout_sec=10)
    res = t.execute("/ip arp print")
    assert res.exit_status == 0
    assert "bridge-lan" in res.stdout
    # credential on argv? never
    assert "sekret" not in " ".join(called["args"])
    assert called["passenv"] == "sekret"  # via env, not argv
    assert called["askpass"]  # askpass script is wired
    assert str(kh) in " ".join(called["args"])


def test_execute_auth_failure(monkeypatch, secrets, tmp_path, _sock_open):
    kh = tmp_path / "known_hosts"
    kh.write_text("", encoding="utf-8")
    monkeypatch.setenv("NI_SSH_KNOWN_HOSTS", str(kh))

    def fake_run(args, **kw):
        return subprocess.CompletedProcess(args, 255, stdout="", stderr="Permission denied, please try again.")

    monkeypatch.setattr(subprocess, "run", fake_run)
    from collectors.common.transport import TransportError

    t = OpenSshCliTransport(secrets, timeout_sec=10)
    with pytest.raises(TransportError):
        t.execute("/ip arp print")
    assert t.last_diag["authentication"] == "FAIL"


def test_execute_missing_known_hosts(secrets, monkeypatch):
    monkeypatch.delenv("NI_SSH_KNOWN_HOSTS", raising=False)
    monkeypatch.setattr("collectors.mikrotik.transport_openssh._known_hosts_path", lambda: None)
    from collectors.common.transport import TransportError

    t = OpenSshCliTransport(secrets, timeout_sec=10)
    with pytest.raises(TransportError):
        t.execute("/ip arp print")