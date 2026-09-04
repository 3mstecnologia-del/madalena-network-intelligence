"""SSH transport for exec-style CLIs (RouterOS). Uses the configured port.

Never logs credentials, hosts, or command output. Callers wrap with ReadOnlyTransport.
TCP probe and SSH share one socket so a banner peek cannot reset the session.
"""

from __future__ import annotations

import logging
import os
import socket
from typing import Any, Optional

from collectors.common.secrets import DeviceSecrets
from collectors.common.transport import CommandResult, TransportError, sanitize_error

SSH_STAGES = (
    "TCP_OPEN",
    "SSH_BANNER",
    "SSH_HANDSHAKE",
    "AUTHENTICATION",
    "ROUTEROS_PROMPT",
    "COMMAND_EXECUTION",
)


def apply_host_key_policy(client) -> None:
    """Default reject unknown keys. Lab may set NI_SSH_MISSING_HOST_KEY=accept-new."""
    import paramiko

    policy = (os.getenv("NI_SSH_MISSING_HOST_KEY") or "reject").strip().lower()
    if policy == "accept-new":
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            client.load_system_host_keys()
        except (OSError, AttributeError):
            pass


class SshTransport:
    """Execute one remote command over SSH using runtime DeviceSecrets.port."""

    def __init__(self, secrets: DeviceSecrets, timeout_sec: int = 60):
        self._secrets = secrets
        self._timeout = timeout_sec
        self.last_diag: dict[str, str] = {
            "tcp": "UNKNOWN",
            "banner": "UNKNOWN",
            "handshake": "UNKNOWN",
            "authentication": "UNKNOWN",
            "routeros": "UNKNOWN",
            "command": "UNKNOWN",
            "port_configured": str(secrets.port),
        }

    def execute(self, command: str) -> CommandResult:
        sock: Optional[socket.socket] = None
        client = None
        try:
            sock = self._tcp_open_and_peek()
            try:
                import paramiko
            except ImportError as exc:
                raise TransportError("paramiko is not installed in this image", stage="SSH_HANDSHAKE") from exc

            client = paramiko.SSHClient()
            logging.getLogger("paramiko").setLevel(logging.CRITICAL)
            apply_host_key_policy(client)
            try:
                self._connect(client, paramiko, sock)
            except Exception:
                sock.close()
                sock = None
                raise
            sock = None
            self.last_diag["handshake"] = "PASS"
            self.last_diag["authentication"] = "PASS"
            self.last_diag["routeros"] = "PASS"
            _stdin, stdout, stderr = client.exec_command(command, timeout=self._timeout)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            status = stdout.channel.recv_exit_status()
            self.last_diag["command"] = "PASS" if status == 0 else "FAIL"
            return CommandResult(
                command=command,
                exit_status=status,
                stdout=out,
                stderr=sanitize_error(err) if err else "",
                transport_ok=True,
                stage="COMMAND_EXECUTION",
            )
        except TransportError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._classify(exc) from None
        finally:
            if client is not None:
                client.close()
            elif sock is not None:
                sock.close()

    def _tcp_open_and_peek(self) -> socket.socket:
        try:
            sock = socket.create_connection((self._secrets.host, self._secrets.port), self._timeout)
        except OSError:
            self.last_diag["tcp"] = "CLOSED"
            raise TransportError("tcp connect failed", stage="TCP_OPEN") from None
        self.last_diag["tcp"] = "OPEN"
        sock.settimeout(min(self._timeout, 8))
        peek = b""
        try:
            peek = sock.recv(64, socket.MSG_PEEK)
        except OSError:
            peek = b""
        if peek.startswith(b"SSH-"):
            self.last_diag["banner"] = "YES"
            return sock
        if peek:
            self.last_diag["banner"] = "NOT_SSH"
            sock.close()
            raise TransportError("tcp open but banner is not ssh", stage="SSH_BANNER") from None
        self.last_diag["banner"] = "EMPTY"
        return sock

    def _connect(self, client, paramiko, sock: socket.socket) -> None:
        try:
            client.connect(
                hostname=self._secrets.host,
                port=self._secrets.port,
                username=self._secrets.username,
                password=self._secrets.password,
                sock=sock,
                timeout=self._timeout,
                banner_timeout=self._timeout,
                auth_timeout=self._timeout,
                allow_agent=False,
                look_for_keys=False,
            )
        except paramiko.AuthenticationException:
            self.last_diag["handshake"] = "PASS"
            self.last_diag["authentication"] = "FAIL"
            raise TransportError("authentication failed", stage="AUTHENTICATION") from None
        except paramiko.ssh_exception.NoValidConnectionsError:
            self.last_diag["tcp"] = "CLOSED"
            raise TransportError("tcp connect failed", stage="TCP_OPEN") from None
        except paramiko.SSHException as exc:
            self._raise_ssh_exception(exc)

    def _raise_ssh_exception(self, exc: BaseException) -> None:
        text = sanitize_error(str(exc)).lower()
        if "banner" in text or "eof" in text:
            self.last_diag["banner"] = "FAIL"
            raise TransportError("ssh banner failed", stage="SSH_BANNER") from None
        self.last_diag["handshake"] = "FAIL"
        raise TransportError("ssh handshake failed", stage="SSH_HANDSHAKE") from None

    def _classify(self, exc: BaseException) -> TransportError:
        name = type(exc).__name__
        if name in {"AuthenticationException", "BadAuthenticationType"}:
            self.last_diag["authentication"] = "FAIL"
            return TransportError("authentication failed", stage="AUTHENTICATION")
        if name in {"NoValidConnectionsError", "ConnectionRefusedError", "TimeoutError"}:
            self.last_diag["tcp"] = "CLOSED"
            return TransportError("tcp connect failed", stage="TCP_OPEN")
        if "banner" in sanitize_error(str(exc)).lower():
            self.last_diag["banner"] = "FAIL"
            return TransportError("ssh banner failed", stage="SSH_BANNER")
        self.last_diag["command"] = "FAIL"
        return TransportError("ssh command failed", stage="COMMAND_EXECUTION")


def diag_summary(transport: SshTransport) -> dict[str, str]:
    """Sanitized stage map for lab diagnostics. Never includes host or secrets."""
    out: dict[str, Any] = dict(transport.last_diag)
    out["protocol"] = (transport._secrets.protocol or "ssh").lower()
    return {str(k): str(v) for k, v in out.items()}
