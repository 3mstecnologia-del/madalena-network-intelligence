"""Interactive CLI transport (SSH or Telnet) for devices without exec_command.

Used by OLT collectors and as a MikroTik fallback. Never logs credentials or
command output. Callers must wrap with ReadOnlyTransport.

Prompt matching is based on documented appliance CLI (Intelbras G08 Username/
Password(1-N chars): then G8>; RouterOS [user@id] >).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

from collectors.common.secrets import DeviceSecrets
from collectors.common.transport import CommandResult, TransportError

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
PAGER_PROMPT = re.compile(
    r"(?i)--\s*more\s*--|press\s+any\s+key|press\s+enter\s+to\s+next"
)
# G08: Username(1-64 chars):  — must not match "Username or password error"
USERNAME_PROMPT = re.compile(
    r"(?i)(?:^|\n)\s*(?:user\s*name|username|login)\s*(?:\([^)]*\))?\s*:"
)
# G08: Password(1-96 chars):  — must not match "Username or password error"
PASSWORD_PROMPT = re.compile(r"(?i)(?:^|\n)\s*password\s*(?:\([^)]*\))?\s*:")
DEVICE_PROMPT = re.compile(
    r"(?m)(?:^G8[>#]\s*$|^GPON[>#]\s*$|^\S+[>#]\s*$|^\[.+?\]\s*>\s*$|^[>#]\s*$)"
)
AUTH_FAIL = re.compile(
    r"(?i)username or password error|authentication failed|login failed|access denied"
)
_CRLF = "\r\n"


@dataclass
class CliLoginState:
    reached_prompt: bool = False
    saw_username_prompt: bool = False
    saw_password_prompt: bool = False
    auth_error: bool = False
    chars: int = 0


def last_line(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    return stripped.splitlines()[-1].strip()


def looks_like_device_prompt(text: str) -> bool:
    return bool(DEVICE_PROMPT.search(last_line(text)))


def pager_continuation(text: str) -> Optional[str]:
    tail = text[-120:]
    if not PAGER_PROMPT.search(tail):
        return None
    if re.search(r"(?i)press\s+enter", tail):
        return _CRLF
    return " "


def _decode(buf: bytes) -> str:
    return _ANSI.sub("", buf.decode("utf-8", errors="replace").replace("\r", ""))


class InteractiveCliTransport:
    """One-shot interactive session: connect, run one command, disconnect."""

    def __init__(
        self,
        secrets: DeviceSecrets,
        timeout_sec: int = 120,
        prompt_hint: Optional[str] = None,
    ):
        self._secrets = secrets
        self._timeout = timeout_sec
        self._prompt_hint = prompt_hint
        self.last_login = CliLoginState()

    def execute(self, command: str) -> CommandResult:
        proto = (self._secrets.protocol or "ssh").lower()
        if proto in {"ssh", "ssh2"}:
            text = self._ssh_command(command)
        elif proto in {"telnet", "telnet23"}:
            text = self._telnet_command(command)
        else:
            raise TransportError("unsupported cli protocol")
        return CommandResult(
            command=command,
            exit_status=0,
            stdout=text,
            stderr="",
            transport_ok=True,
        )

    def _ssh_command(self, command: str) -> str:
        try:
            import paramiko
        except ImportError as exc:
            raise TransportError("paramiko is not installed in this image") from exc
        from collectors.mikrotik.transport_ssh import apply_host_key_policy

        client = paramiko.SSHClient()
        logging.getLogger("paramiko").setLevel(logging.CRITICAL)
        apply_host_key_policy(client)
        try:
            self._paramiko_connect(client)
            chan = client.invoke_shell(term="vt100", width=200, height=200)
            chan.settimeout(self._timeout)
            self._login_and_wait_prompt(chan)
            self._send_chan(chan, command)
            return self._read_until_prompt(chan, echo=command)
        except TransportError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TransportError("interactive ssh failed") from exc
        finally:
            client.close()

    def _paramiko_connect(self, client) -> None:
        common = {
            "hostname": self._secrets.host,
            "port": self._secrets.port,
            "username": self._secrets.username,
            "password": self._secrets.password,
            "timeout": self._timeout,
            "banner_timeout": self._timeout,
            "auth_timeout": self._timeout,
            "allow_agent": False,
            "look_for_keys": False,
        }
        try:
            client.connect(**common)
            return
        except Exception:
            pass
        try:
            client.connect(
                **common,
                disabled_algorithms={"pubkeys": ["rsa-sha2-512", "rsa-sha2-256"]},
            )
        except Exception as exc:  # noqa: BLE001
            raise TransportError("interactive ssh failed") from exc

    def _telnet_command(self, command: str) -> str:
        try:
            import telnetlib
        except ImportError as exc:
            raise TransportError("telnetlib is not available") from exc
        tn = None
        try:
            tn = telnetlib.Telnet(self._secrets.host, self._secrets.port, self._timeout)
            self._telnet_login(tn)
            tn.write(command.encode("ascii", errors="replace") + b"\r\n")
            return self._telnet_read_until_prompt(tn, echo=command)
        except TransportError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TransportError("interactive telnet failed") from exc
        finally:
            if tn is not None:
                tn.close()

    def _send_chan(self, chan, text: str) -> None:
        chan.send(text + _CRLF)

    def _drive_login(self, buf: str, sent_user: bool, sent_pass: bool) -> tuple[Optional[str], bool, bool, bool]:
        """Return (to_send, sent_user, sent_pass, done). Never includes secret values."""
        state = self.last_login
        state.chars = max(state.chars, len(buf))
        if USERNAME_PROMPT.search(buf):
            state.saw_username_prompt = True
        if PASSWORD_PROMPT.search(buf):
            state.saw_password_prompt = True
        if AUTH_FAIL.search(buf) and sent_pass:
            state.auth_error = True
            raise TransportError("cli authentication failed")
        if looks_like_device_prompt(buf):
            state.reached_prompt = True
            return None, sent_user, sent_pass, True
        if (not sent_user) and USERNAME_PROMPT.search(buf):
            return self._secrets.username, True, sent_pass, False
        if (not sent_pass) and PASSWORD_PROMPT.search(buf):
            return self._secrets.password, sent_user, True, False
        return None, sent_user, sent_pass, False

    def _telnet_login(self, tn) -> None:
        deadline = time.time() + min(self._timeout, 45)
        buf = ""
        sent_user = sent_pass = False
        while time.time() < deadline:
            chunk = tn.read_very_eager()
            if chunk:
                buf += _decode(chunk)
                payload, sent_user, sent_pass, done = self._drive_login(buf, sent_user, sent_pass)
                if done:
                    return
                if payload is not None:
                    tn.write(payload.encode("utf-8", errors="replace") + b"\r\n")
                    buf = ""
                    continue
            time.sleep(0.1)
        if looks_like_device_prompt(buf):
            self.last_login.reached_prompt = True
            return
        raise TransportError("cli login did not reach a prompt")

    def _login_and_wait_prompt(self, chan) -> None:
        deadline = time.time() + min(self._timeout, 45)
        buf = ""
        sent_user = sent_pass = False
        while time.time() < deadline:
            if chan.recv_ready():
                buf += _decode(chan.recv(65535))
                payload, sent_user, sent_pass, done = self._drive_login(buf, sent_user, sent_pass)
                if done:
                    return
                if payload is not None:
                    self._send_chan(chan, payload)
                    buf = ""
                    continue
            time.sleep(0.05)
        raise TransportError("cli did not reach a prompt")

    def _wait_prompt(self, chan) -> None:
        self._login_and_wait_prompt(chan)

    def _read_until_prompt(self, chan, echo: str) -> str:
        deadline = time.time() + self._timeout
        buf = ""
        idle = 0
        while time.time() < deadline:
            if chan.recv_ready():
                buf += _decode(chan.recv(65535))
                idle = 0
                cont = pager_continuation(buf)
                if cont is not None:
                    chan.send(cont)
                    continue
                if looks_like_device_prompt(buf) and echo in buf:
                    return self._strip_cli(buf, echo)
            else:
                idle += 1
                if idle > 20 and buf and looks_like_device_prompt(buf):
                    return self._strip_cli(buf, echo)
            time.sleep(0.05)
        if buf:
            return self._strip_cli(buf, echo)
        raise TransportError("cli command produced no output")

    def _telnet_read_until_prompt(self, tn, echo: str) -> str:
        deadline = time.time() + self._timeout
        buf = ""
        while time.time() < deadline:
            chunk = tn.read_very_eager()
            if chunk:
                buf += _decode(chunk)
                cont = pager_continuation(buf)
                if cont is not None:
                    tn.write(cont.encode("ascii"))
                    continue
                if looks_like_device_prompt(buf) and echo in buf:
                    return self._strip_cli(buf, echo)
            time.sleep(0.05)
        if buf:
            return self._strip_cli(buf, echo)
        raise TransportError("cli command produced no output")

    def _strip_cli(self, text: str, echo: str) -> str:
        lines = text.splitlines()
        out: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped == echo or stripped.startswith(echo + " "):
                continue
            if DEVICE_PROMPT.search(stripped):
                continue
            if PAGER_PROMPT.search(stripped):
                continue
            out.append(line)
        return "\n".join(out).strip() + "\n"
