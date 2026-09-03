"""Generic command transport. Collectors must not embed host IPs or secrets."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Protocol

_SECRETISH = re.compile(
    r"(?i)(password|passwd|secret|token|community|private-key|username|user|login)\s*[=:]\s*\S+"
)
_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_MAC = re.compile(r"(?i)(?:[0-9A-F]{2}[:\-]){5}[0-9A-F]{2}")
_SQL_PARAMS = re.compile(r"\[SQL:.*", re.DOTALL)
_USER_QUOTE = re.compile(r"(?i)(?:user(?:name)?|login)\s*[=:]?\s*['\"][^'\"]+['\"]")
_HOST_QUOTE = re.compile(r"(?i)\b(?:to|host|hostname)\s+['\"][^'\"]+['\"]")
_HOSTISH = re.compile(r"(?i)\b(?:host|hostname|server)\s*[=:]\s*\S+")
_SERIALISH = re.compile(r"\b[A-Z]{2,6}-[0-9A-Fa-f]{6,}\b")


def sanitize_error(message: str) -> str:
    """Strip secrets, addresses, identifiers, and SQL blobs before log or persist."""
    text = _SECRETISH.sub(r"\1=<REDACTED>", message)
    text = _USER_QUOTE.sub("user=<REDACTED>", text)
    text = _HOST_QUOTE.sub("host=<REDACTED>", text)
    text = _HOSTISH.sub(lambda m: m.group(0).split("=")[0].split(":")[0] + "=<REDACTED>", text)
    text = _IPV4.sub("<IP>", text)
    text = _MAC.sub("<MAC>", text)
    text = _SERIALISH.sub("<SERIAL>", text)
    text = _SQL_PARAMS.sub("[SQL redacted]", text)
    return text[:500]


def sanitized_exception_message(exc: BaseException) -> str:
    """Safe one-line error for logs, collection runs, API, and MCP."""
    if isinstance(exc, TransportError):
        return str(exc)
    return sanitize_error(f"{type(exc).__name__}: {exc}")


@dataclass
class CommandResult:
    command: str
    exit_status: int
    stdout: str
    stderr: str
    transport_ok: bool = True
    stage: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.transport_ok and self.exit_status == 0


class TransportError(Exception):
    """Transport failed (connectivity, timeout, auth). Message is always sanitized."""

    def __init__(self, message: str = "transport failed", *, stage: Optional[str] = None):
        self.stage = stage
        super().__init__(sanitize_error(message))


class ReadOnlyViolation(Exception):
    """Attempted a command outside the read-only allowlist."""


class Transport(Protocol):
    def execute(self, command: str) -> CommandResult:
        """Run one command. Must not log secrets."""
        ...


_MUTATION_TOKENS = re.compile(
    r"(?i)(?:^|[\s/;])(add|set|remove|enable|disable|move)(?:$|[\s=])"
)


class ReadOnlyTransport:
    """Wrap any transport: only allowlisted read commands may run."""

    def __init__(self, inner: Transport, allowlist: tuple[str, ...]):
        self._inner = inner
        self._allowlist = tuple(a.strip() for a in allowlist)

    def execute(self, command: str) -> CommandResult:
        cmd = command.strip()
        if _MUTATION_TOKENS.search(cmd):
            raise ReadOnlyViolation(f"refusing mutable token in command: {cmd!r}")
        if not self._is_allowed(cmd):
            raise ReadOnlyViolation(f"command not in read-only allowlist: {cmd!r}")
        return self._inner.execute(cmd)

    def _is_allowed(self, command: str) -> bool:
        compact = " ".join(command.split())
        for allowed in self._allowlist:
            if compact == allowed or compact.startswith(allowed + " "):
                return True
        return False


class MemoryTransport:
    """Fixture transport: map exact command → stdout. Never talks to a device."""

    def __init__(self, outputs: dict[str, str], errors: Optional[dict[str, str]] = None):
        self._outputs = outputs
        self._errors = errors or {}
        self.calls: list[str] = []

    def execute(self, command: str) -> CommandResult:
        self.calls.append(command)
        compact = " ".join(command.split())
        if compact in self._errors:
            return CommandResult(
                command=compact,
                exit_status=1,
                stdout="",
                stderr=self._errors[compact],
                transport_ok=True,
                stage="COMMAND_EXECUTION",
            )
        if compact not in self._outputs:
            raise TransportError(f"no fixture for command: {compact}", stage="COMMAND_EXECUTION")
        return CommandResult(
            command=compact,
            exit_status=0,
            stdout=self._outputs[compact],
            stderr="",
            transport_ok=True,
            stage="COMMAND_EXECUTION",
        )
