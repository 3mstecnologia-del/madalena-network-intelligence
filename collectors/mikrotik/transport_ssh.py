"""Optional SSH transport for RouterOS. Credentials come from runtime only.

Never import this from parsers. Tests use MemoryTransport, not SSH.
This module does not contain hostnames or passwords.
"""

from __future__ import annotations

from collectors.common.secrets import DeviceSecrets
from collectors.common.transport import CommandResult, TransportError


class SshTransport:
    """Execute one remote command over SSH using runtime DeviceSecrets.

    Implementation uses Paramiko inside the collector container. Callers must
    wrap this with ReadOnlyTransport. Does not log password or command output.
    """

    def __init__(self, secrets: DeviceSecrets, timeout_sec: int = 30):
        self._secrets = secrets
        self._timeout = timeout_sec

    def execute(self, command: str) -> CommandResult:
        try:
            import paramiko
        except ImportError as exc:
            raise TransportError("paramiko is not installed in this image") from exc
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            client.load_system_host_keys()
        except OSError:
            pass
        try:
            client.connect(
                hostname=self._secrets.host,
                port=self._secrets.port,
                username=self._secrets.username,
                password=self._secrets.password,
                timeout=self._timeout,
                allow_agent=False,
                look_for_keys=False,
            )
            stdin, stdout, stderr = client.exec_command(command, timeout=self._timeout)
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
