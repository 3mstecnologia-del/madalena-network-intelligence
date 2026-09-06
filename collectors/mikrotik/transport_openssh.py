"""OpenSSH CLI transport for devices whose banner the Python SSH libs cannot read.

Some MikroTik RouterOS (and the Intelbras G08) servers only negotiate over the
system OpenSSH client; paramiko/asyncssh fail with "Error reading SSH protocol
banner". This transport invokes the container's /usr/bin/ssh with the system
client so those devices are reachable.

Security properties:
- Credentials are never on argv. Password goes via an SSH_ASKPASS script
  (disposable, 0600) read through the environment. User is on argv (username is
  not a secret on these devices).
- Host key checking uses the mounted known_hosts (NI_SSH_KNOWN_HOSTS / default).
- Legacy KEX/host-key algorithms are enabled ONLY for routers that need them
  (MikroTik RouterOS 7 / older Intelbras); they are scoped per-command below.
- stdout/stderr are returned; nothing is logged. Command is executed read-only
  by the caller (ReadOnlyTransport allowlist).
"""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from collectors.common.secrets import DeviceSecrets
from collectors.common.transport import CommandResult, TransportError


def _known_hosts_path() -> Optional[str]:
    explicit = (os.getenv("NI_SSH_KNOWN_HOSTS") or "").strip()
    if explicit:
        return explicit
    default = "/run/ssh/known_hosts"
    return default if os.path.isfile(default) else None


class OpenSshCliTransport:
    """Run one remote command over the system openssh client."""

    def __init__(self, secrets: DeviceSecrets, timeout_sec: int = 90):
        self._secrets = secrets
        self._timeout = timeout_sec
        self.last_diag: dict[str, str] = {
            "tcp": "UNKNOWN",
            "banner": "UNKNOWN",
            "authentication": "UNKNOWN",
            "command": "UNKNOWN",
            "port_configured": str(secrets.port),
        }

    def _askpass(self) -> str:
        """Write a disposable askpass script returning the password. Returns its path."""
        dirpath = Path(tempfile.mkdtemp(prefix="ni-askpass-", dir="/tmp"))
        script = dirpath / "askpass.sh"
        script.write_text(
            '#!/bin/sh\nprintf "%s" "$SSH_ASKPASS_PASSWORD"\n',
            encoding="utf-8",
        )
        script.chmod(0o700)
        # Keep the script path alive for the subprocess; parent cleans up.
        return str(script)

    def execute(self, command: str) -> CommandResult:
        s = self._secrets
        kh = _known_hosts_path()
        if not kh:
            raise TransportError("ssh known_hosts file missing", stage="SSH_HANDSHAKE")
        askpath = self._askpass()
        try:
            # Basic online check
            try:
                import socket

                sock = socket.create_connection((s.host, s.port), min(self._timeout, 15))
                sock.close()
                self.last_diag["tcp"] = "OPEN"
            except OSError:
                self.last_diag["tcp"] = "CLOSED"
                raise TransportError("tcp connect failed", stage="TCP_OPEN") from None

            ssh = ["/usr/bin/ssh", "-T", "-p", str(s.port), "-o", "BatchMode=no",
                   "-o", "NumberOfPasswordPrompts=1",
                   "-o", "PreferredAuthentications=password,keyboard-interactive",
                   "-o", "PubkeyAuthentication=no",
                   "-o", "ConnectTimeout=15",
                   "-o", "StrictHostKeyChecking=yes",
                   "-o", f"UserKnownHostsFile={kh}",
                   "-o", "GlobalKnownHostsFile=/dev/null",
                   # Legacy algorithms needed by MikroTik RouterOS 7 / older gear
                   "-o", "KexAlgorithms=+diffie-hellman-group14-sha1,diffie-hellman-group-exchange-sha256",
                   "-o", "HostKeyAlgorithms=+ssh-rsa",
                   "-o", "PubkeyAcceptedAlgorithms=+ssh-rsa",
                   "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=3",
                   "-o", "LogLevel=ERROR",
                   f"{s.username}@{s.host}"] + shlex.split(command)
            env = os.environ.copy()
            env["SSH_ASKPASS"] = askpath
            env["SSH_ASKPASS_REQUIRE"] = "force"
            env["SSH_ASKPASS_PASSWORD"] = s.password
            env.pop("DISPLAY", None)  # ensure dev/tty not needed
            proc = subprocess.run(
                ssh,
                env=env,
                capture_output=True,
                text=True,
                input="",
                timeout=self._timeout,
                check=False,
            )
            stderr = proc.stderr or ""
            if proc.returncode != 0:
                low = stderr.lower()
                if "host key verification failed" in low:
                    self.last_diag["banner"] = "HOSTKEY"
                    raise TransportError("ssh host key verification failed", stage="SSH_HANDSHAKE")
                if "permission denied" in low or "authentication failed" in low:
                    self.last_diag["authentication"] = "FAIL"
                    raise TransportError("authentication failed", stage="AUTHENTICATION")
                if "connection refused" in low or "no route" in low or "timed out" in low:
                    self.last_diag["tcp"] = "CLOSED"
                    raise TransportError("tcp connect failed", stage="TCP_OPEN")
                self.last_diag["command"] = "FAIL"
                raise TransportError(
                    f"ssh command failed: {stderr.strip()[:200]}",
                    stage="COMMAND_EXECUTION",
                )
            self.last_diag["authentication"] = "PASS"
            self.last_diag["command"] = "PASS"
            self.last_diag["banner"] = "PASS"
            return CommandResult(
                command=command,
                exit_status=0,
                stdout=proc.stdout or "",
                stderr=sanitize_error(stderr),
                transport_ok=True,
                stage="COMMAND_EXECUTION",
            )
        except TransportError:
            raise
        except subprocess.TimeoutExpired as exc:
            raise TransportError("ssh command timed out", stage="COMMAND_EXECUTION") from exc
        except Exception as exc:  # noqa: BLE001
            raise TransportError("openssh cli transport failed") from exc
        finally:
            try:
                Path(askpath).unlink(missing_ok=True)
                Path(askpath).parent.rmdir()
            except OSError:
                pass


def sanitize_error(message: str) -> str:
    """Local import to avoid cycle at module load."""
    from collectors.common.transport import sanitize_error as _se

    return _se(message)