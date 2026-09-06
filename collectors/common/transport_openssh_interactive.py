"""Interactive OpenSSH CLI transport with legacy KEX + pty.

Some CLI-only devices (the Intelbras G08 OLT, and some MikroTik RouterOS 7
servers) only negotiate over the system OpenSSH client and require an
interactive pty session. paramiko/asyncssh either cannot read the banner or the
interactive shell never produces output because the device only offers legacy
KX algorithms (diffie-hellman-group1-sha1 / group14-sha1). The system client
with `-tt` closes that gap.

This transport drives one interactive session per execute():
- connects via `ssh -tt` with legacy KEX + host-key algorithms,
- answers the device Username:/Password: prompts via a disposable SSH_ASKPASS
  script (password never on argv),
- waits for the device prompt,
- sends the read-only command,
- answers every pager prompt exactly once,
- returns the command output stripped of the echo and terminal prompt.

Credentials are never on argv and never logged. Callers MUST wrap with
`ReadOnlyTransport` so only allowlisted read commands can run.
"""

from __future__ import annotations

import os
import pathlib
import pty
import re
import selectors
import subprocess
import time
from typing import Optional

from collectors.common.secrets import DeviceSecrets
from collectors.common.transport import CommandResult, TransportError

USERNAME_PROMPT = re.compile(r"(?i)(?:^|\n)\s*(?:user\s*name|username|login)\s*(?:\([^)]*\))?\s*:")
PASSWORD_PROMPT = re.compile(r"(?i)(?:^|\n)\s*password\s*(?:\([^)]*\))?\s*:")
DEVICE_PROMPT = re.compile(r"(?m)(?:^G8[>#]\s*$|^GPON[>#]\s*$|^\S+[>#]\s*$|^\[.+?\]\s*>\s*$|^[>#]\s*$)")
AUTH_FAIL = re.compile(r"(?i)username or password error|authentication failed|login failed|access denied")
PAGER_PROMPT = re.compile(
    r"(?i)--\s*more\s*--(?:\(\d+%\))?\s*"
    r"|press\s+any\s+key(?:\s+to\s+continue)?"
    r"|press\s+enter\s+to\s+next\s+line(?:\s*[,.]\s*[a-z_]+[^.]{0,60})?"
    r"|press\s+enter\s+to\s+next\s+line\s*,?\s*(?:other\s+key\s+to\s+next\s+page|ctrl[_+ ]?c\s+to\s+(?:break|stop))"
    r"|other\s+key\s+to\s+next\s+page"
    r"|press\s+q\s+to\s+quit"
)


_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _decode(b: bytes) -> str:
    return _ANSI.sub("", b.decode("utf-8", errors="replace").replace("\r", ""))


def _looks_like_prompt(text: str) -> bool:
    last = text.strip().splitlines()[-1].strip() if text.strip() else ""
    return bool(DEVICE_PROMPT.search(last))


def _pager_continuation(text: str) -> Optional[str]:
    if not PAGER_PROMPT.search(text[-180:]):
        return None
    return "\n"  # G08: advance one pager screen/line


class OpenSshInteractiveTransport:
    """Run one command in an interactive `ssh -tt` session (legacy-KEX CLI gear)."""

    def __init__(self, secrets: DeviceSecrets, timeout_sec: int = 90):
        self._secrets = secrets
        self._timeout = timeout_sec
        self.last_login = _LoginState()

    def execute(self, command: str) -> CommandResult:
        proto = (self._secrets.protocol or "ssh").lower()
        if proto not in ("ssh", "ssh2"):
            raise TransportError("OpenSshInteractiveTransport supports ssh only", stage="PROTOCOL")
        output = self._run_interactive(command)
        return CommandResult(
            command=command,
            exit_status=0,
            stdout=output,
            stderr="",
            transport_ok=True,
            stage="COMMAND_EXECUTION",
        )

    # --- internals ---

    def _run_interactive(self, command: str) -> str:
        s = self._secrets
        ask = pathlib.Path(
            subprocess.run(
                ["mktemp", "-d", "-p", "/tmp", "ni-askpass-XXXXXX"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
        ) / "askpass.sh"
        try:
            ask.write_text('#!/bin/sh\nprintf -- "%s" "$SSH_ASKPASS_PW"\n', encoding="utf-8")
            ask.chmod(0o700)
        except OSError as exc:
            raise TransportError("cannot stage askpass helper") from exc

        env = os.environ.copy()
        env.pop("DISPLAY", None)
        env["SSH_ASKPASS"] = str(ask)
        env["SSH_ASKPASS_REQUIRE"] = "force"
        env["SSH_ASKPASS_PW"] = s.password

        cmdv = [
            "/usr/bin/ssh", "-tt", "-p", str(s.port),
            "-o", "BatchMode=no",
            "-o", "NumberOfPasswordPrompts=1",
            "-o", "PreferredAuthentications=password,keyboard-interactive",
            "-o", "PubkeyAuthentication=no",
            "-o", "ConnectTimeout=15",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "GlobalKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR",
            "-o", "KexAlgorithms=+diffie-hellman-group14-sha1,diffie-hellman-group1-sha1",
            "-o", "HostKeyAlgorithms=+ssh-rsa",
            "-o", "PubkeyAcceptedAlgorithms=+ssh-rsa",
            f"{s.username}@{s.host}",
        ]
        master, slave = pty.openpty()
        try:
            proc = subprocess.Popen(
                cmdv, stdin=slave, stdout=slave, stderr=slave,
                env=env, close_fds=True, start_new_session=True,
            )
        except OSError as exc:
            raise TransportError("cannot spawn openssh client") from exc
        finally:
            try:
                os.close(slave)
            except OSError:
                pass

        selector = selectors.DefaultSelector()
        selector.register(master, selectors.EVENT_READ)
        buf = ""
        sent_user = sent_pass = False
        attempted_cmd = False
        stage = "SSH_CONNECT"
        cursor = 0  # consumed upto; only answer pager markers at/after this offset
        timeout_at = time.time() + self._timeout
        try:
            while time.time() < timeout_at:
                if proc.poll() is not None and not buf:
                    stage = "SSH_EXITED_EARLY"
                    break
                ready = selector.select(0.2)
                if not ready:
                    continue
                try:
                    data = os.read(master, 65536)
                except OSError:
                    break
                if not data:
                    break
                buf += _decode(data)

                # Answer each pager continuation exactly once, in order, using a
                # consumption cursor (never re-answer an already-served marker).
                m = PAGER_PROMPT.search(buf, cursor)
                if m is not None:
                    os.write(master, b"\r\n")
                    cursor = m.end()
                    continue

                if not attempted_cmd:
                    # --- LOGIN ---
                    if AUTH_FAIL.search(buf) and sent_pass:
                        self.last_login.auth_error = True
                        raise TransportError("cli authentication failed", stage="AUTHENTICATION")
                    if (not sent_user) and USERNAME_PROMPT.search(buf):
                        os.write(master, (s.username + "\n").encode())
                        sent_user = True
                        buf = ""
                        continue
                    if (not sent_pass) and PASSWORD_PROMPT.search(buf):
                        os.write(master, (s.password + "\n").encode())
                        sent_pass = True
                        buf = ""
                        continue
                    if sent_pass and _looks_like_prompt(buf):
                        self.last_login.reached_prompt = True
                        os.write(master, (command + "\n").encode())
                        attempted_cmd = True
                        buf = ""
                        continue
                else:
                    # Collect command output until prompt reappears after echo.
                    # Mirror the validated probe: drain the pager inline marker
                    # (split at each continuation) and stop only on a terminal
                    # device prompt, never on the pager line itself.
                    if command in buf and _looks_like_prompt(buf) and not PAGER_PROMPT.search(buf[-200:]):
                        selector.unregister(master)
                        os.write(master, b"exit\n")
                        try:
                            os.close(master)
                        except OSError:
                            pass
                        return self._strip_output(buf, command)
                    # Timeout safety: if prompt comes back idle after output.
            # --- fallback on timeout with buffered output ---
            if buf:
                try:
                    os.close(master)
                except OSError:
                    pass
                if attempted_cmd:
                    return self._strip_output(buf, command)
            raise TransportError(f"openssh interactive session failed (stage={stage})", stage=stage)
        finally:
            selector.close()
            try:
                proc.kill()
            except Exception:
                pass
            try:
                ask.unlink(missing_ok=True)
                ask.parent.rmdir()
            except OSError:
                pass

    @staticmethod
    def _strip_output(text: str, command: str) -> str:
        out: list[str] = []
        for line in text.splitlines():
            s = line.strip()
            if not s:
                continue
            if s == command or s.startswith(command + " "):
                continue
            if DEVICE_PROMPT.search(s):
                continue
            # Inline pager marker: split it out, strip trailing punctuation from
            # row fragments, and keep data rows. The G08 joins a row to the
            # pager marker with a run of dots (e.g. "....press ENTER....<row>..").
            parts = PAGER_PROMPT.split(s)
            for part in parts:
                p = part.strip().strip(".-_ ")
                if not p or set(p) <= set(".:-_ "):
                    continue
                out.append(p)
        return "\n".join(out).strip() + "\n"


class _LoginState:
    reached_prompt: bool = False
    saw_username_prompt: bool = False
    saw_password_prompt: bool = False
    auth_error: bool = False
    chars: int = 0