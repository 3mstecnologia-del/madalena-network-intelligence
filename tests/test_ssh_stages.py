"""SSH transport stages, custom port, and sanitization. No live devices."""

from __future__ import annotations

import paramiko
import pytest

from collectors.common.secrets import DeviceSecrets
from collectors.common.transport import TransportError, sanitize_error, sanitized_exception_message
from collectors.mikrotik.collector import MikroTikCollector
from collectors.mikrotik.transport_ssh import SshTransport

_PW = "super-secret"
SECRETS = DeviceSecrets(
    host="192.0.2.8",
    username="labuser",
    password=_PW,
    port=8822,
    protocol="ssh",
)


class _Sock:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.closed = False

    def settimeout(self, _t):
        return None

    def recv(self, _n, flags=0):
        return self.payload

    def close(self):
        self.closed = True


def test_ssh_uses_configured_custom_port(monkeypatch):
    seen = {}

    def fake_conn(addr, timeout=None):
        seen["addr"] = addr
        return _Sock(b"SSH-2.0-OpenSSH_9.0\r\n")

    monkeypatch.setattr("collectors.mikrotik.transport_ssh.socket.create_connection", fake_conn)

    class FakeClient:
        def __init__(self):
            self.kwargs = None

        def set_missing_host_key_policy(self, _p):
            return None

        def connect(self, **kwargs):
            self.kwargs = kwargs
            raise paramiko.AuthenticationException("Authentication failed.")

        def close(self):
            return None

        def load_system_host_keys(self):
            return None

        def load_host_keys(self, _path):
            return None

    monkeypatch.setattr(paramiko, "SSHClient", FakeClient)
    transport = SshTransport(SECRETS, timeout_sec=5)
    with pytest.raises(TransportError) as exc:
        transport.execute("/ip dhcp-server lease print detail without-paging")
    assert seen["addr"][1] == 8822
    assert seen["addr"][0] == "192.0.2.8"
    assert exc.value.stage == "AUTHENTICATION"
    assert _PW not in str(exc.value)
    assert "labuser" not in str(exc.value)
    assert "192.0.2.8" not in str(exc.value)


def test_tcp_open_non_ssh_banner(monkeypatch):
    monkeypatch.setattr(
        "collectors.mikrotik.transport_ssh.socket.create_connection",
        lambda addr, timeout=None: _Sock(b"Login: "),
    )
    transport = SshTransport(SECRETS, timeout_sec=5)
    with pytest.raises(TransportError) as exc:
        transport.execute("/system identity print")
    assert exc.value.stage == "SSH_BANNER"
    assert transport.last_diag["tcp"] == "OPEN"
    assert transport.last_diag["banner"] == "NOT_SSH"


def test_tcp_open_ssh_handshake_fails(monkeypatch):
    sock = _Sock(b"SSH-2.0-OpenSSH_9.0\r\n")
    monkeypatch.setattr(
        "collectors.mikrotik.transport_ssh.socket.create_connection",
        lambda addr, timeout=None: sock,
    )

    class FakeClient:
        def set_missing_host_key_policy(self, _p):
            return None

        def connect(self, **_kwargs):
            raise paramiko.SSHException("kex protocol error")

        def close(self):
            return None

        def load_system_host_keys(self):
            return None

        def load_host_keys(self, _path):
            return None

    monkeypatch.setattr(paramiko, "SSHClient", FakeClient)
    transport = SshTransport(SECRETS, timeout_sec=5)
    with pytest.raises(TransportError) as exc:
        transport.execute("/system identity print")
    assert exc.value.stage == "SSH_HANDSHAKE"
    assert transport.last_diag["tcp"] == "OPEN"
    assert transport.last_diag["banner"] == "YES"
    assert transport.last_diag["handshake"] == "FAIL"


def test_tcp_closed(monkeypatch):
    def fail(addr, timeout=None):
        raise ConnectionRefusedError()

    monkeypatch.setattr("collectors.mikrotik.transport_ssh.socket.create_connection", fail)
    transport = SshTransport(SECRETS, timeout_sec=5)
    with pytest.raises(TransportError) as exc:
        transport.execute("/system identity print")
    assert exc.value.stage == "TCP_OPEN"
    assert transport.last_diag["tcp"] == "CLOSED"


def test_authentication_failure_sanitized_before_str():
    dirty = TransportError(
        "Authentication failed for user 'labuser' to '192.0.2.8' password" + "=" + _PW,
        stage="AUTHENTICATION",
    )
    text = str(dirty)
    assert "labuser" not in text
    assert "192.0.2.8" not in text
    assert "super-secret" not in text
    assert dirty.stage == "AUTHENTICATION"


def test_sanitized_exception_message_used_before_persist():
    class Boom(Exception):
        pass

    msg = sanitized_exception_message(
        Boom("login failed password=hunter2 host=192.0.2.9 user='admin' ITBS-aabbccddee")
    )
    assert "hunter2" not in msg
    assert "192.0.2.9" not in msg
    assert "admin" not in msg
    assert "ITBS-aabbccddee" not in msg
    assert "<IP>" in msg or "<REDACTED>" in msg


def test_collect_live_honors_ssh_port_no_fallback(monkeypatch):
    monkeypatch.setenv("EX_HOST", "192.0.2.8")
    monkeypatch.setenv("EX_USERNAME", "u")
    monkeypatch.setenv("EX_PASSWORD", "p")
    monkeypatch.setenv("EX_PORT", "8822")
    monkeypatch.setenv("EX_PROTOCOL", "ssh")
    seen = {}

    def fake_via(self, transport, **_kw):
        seen["type"] = type(transport).__name__
        seen["port"] = transport._secrets.port
        from collectors.common.types import CollectorResult

        return CollectorResult(meta={"status": "ok", "completeness": "complete"})

    monkeypatch.setattr(MikroTikCollector, "collect_via_transport", fake_via)
    MikroTikCollector("env", "EX").collect_live(dhcp_only=True)
    assert seen["type"] == "SshTransport"
    assert seen["port"] == 8822


def test_sanitize_error_strips_quoted_user_and_serial():
    text = sanitize_error("failed for user 'madalena' to 'core.example' SN=FHTT-c139d28f")
    assert "madalena" not in text
    assert "core.example" not in text
    assert "FHTT-c139d28f" not in text


def test_known_hosts_loaded_with_reject_policy(tmp_path, monkeypatch):
    import paramiko as real_paramiko

    from collectors.mikrotik.transport_ssh import apply_host_key_policy

    hosts = tmp_path / "known_hosts"
    hosts.write_text("# synthetic placeholder\n", encoding="utf-8")
    monkeypatch.setenv("NI_SSH_KNOWN_HOSTS", str(hosts))
    monkeypatch.delenv("NI_SSH_MISSING_HOST_KEY", raising=False)
    monkeypatch.setenv("MK_VERIFY_TLS", "false")
    seen: dict = {}

    class Client:
        def set_missing_host_key_policy(self, policy):
            seen["policy"] = type(policy).__name__

        def load_host_keys(self, path):
            seen["path"] = path

        def load_system_host_keys(self):
            seen["system"] = True

    apply_host_key_policy(Client())
    assert seen["policy"] == "RejectPolicy"
    assert seen["path"] == str(hosts)
    assert seen.get("system") is True
    assert issubclass(real_paramiko.RejectPolicy, real_paramiko.MissingHostKeyPolicy)


def test_known_hosts_missing_file_is_config_error(monkeypatch):
    from collectors.mikrotik.transport_ssh import apply_host_key_policy

    monkeypatch.setenv("NI_SSH_KNOWN_HOSTS", "/no/such/known_hosts")
    monkeypatch.delenv("NI_SSH_MISSING_HOST_KEY", raising=False)

    class Client:
        def set_missing_host_key_policy(self, _p):
            return None

    with pytest.raises(TransportError) as exc:
        apply_host_key_policy(Client())
    assert exc.value.stage == "SSH_HANDSHAKE"
    assert "known_hosts" in str(exc.value).lower()
