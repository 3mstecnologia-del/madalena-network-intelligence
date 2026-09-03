"""Generic command transport. Collectors must not embed host IPs or secrets."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Protocol

_SECRETISH = re.compile(
    r"(?i)(password|passwd|secret|token|community|private-key)\s*[=:]\s*\S+"
)


def sanitize_error(message: str) -> str:
    """Strip secret-like key=value pairs from error text before persistence."""
    return _SECRETISH.sub(r"\1=<REDACTED>", message)[:1000]


@dataclass
class CommandResult:
    command: str
    exit_status: int
    stdout: str
    stderr: str
    transport_ok: bool = True

    @property
    def ok(self) -> bool:
        return self.transport_ok and self.exit_status == 0


class TransportError(Exception):
    """Transport failed (connectivity, timeout). Not a CLI syntax error."""


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
            )
        if compact not in self._outputs:
            raise TransportError(f"no fixture for command: {compact}")
        return CommandResult(
            command=compact,
            exit_status=0,
            stdout=self._outputs[compact],
            stderr="",
            transport_ok=True,
        )
