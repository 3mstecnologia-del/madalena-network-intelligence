"""Optional SSH transport for exec-style CLIs (RouterOS). Runtime secrets only."""

from __future__ import annotations

import logging
import os

from collectors.common.secrets import DeviceSecrets
from collectors.common.transport import CommandResult, TransportError


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
    except OSError:
        pass


class SshTransport:
    """Execute one remote command over SSH using runtime DeviceSecrets.

    Callers must wrap this with ReadOnlyTransport. Does not log password or output.
    """

    def __init__(self, secrets: DeviceSecrets, timeout_sec: int = 60):
        self._secrets = secrets
        self._timeout = timeout_sec

    def execute(self, command: str) -> CommandResult:
        try:
            import paramiko
        except ImportError as exc:
            raise TransportError("paramiko is not installed in this image") from exc
        client = paramiko.SSHClient()
        logging.getLogger("paramiko").setLevel(logging.CRITICAL)
        apply_host_key_policy(client)
        try:
            client.connect(
                hostname=self._secrets.host,
                port=self._secrets.port,
                username=self._secrets.username,
                password=self._secrets.password,
                timeout=self._timeout,
                banner_timeout=self._timeout,
                auth_timeout=self._timeout,
                allow_agent=False,
                look_for_keys=False,
            )
            _stdin, stdout, stderr = client.exec_command(command, timeout=self._timeout)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            status = stdout.channel.recv_exit_status()
            return CommandResult(
                command=command,
                exit_status=status,
                stdout=out,
                stderr=err,
                transport_ok=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise TransportError("ssh transport failed") from exc
        finally:
            client.close()
