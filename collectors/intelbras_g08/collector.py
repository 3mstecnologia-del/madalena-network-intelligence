"""Intelbras G08 collector — parsers + optional live interactive CLI.

Live path uses runtime secrets + a read-only allowlist. Tests use MemoryTransport
or collect_from_texts. No customer hosts in this module.
"""

from __future__ import annotations

from typing import Optional

from collectors.common.cli_interactive import InteractiveCliTransport
from collectors.common.secrets import resolve_secrets
from collectors.common.transport import (
    ReadOnlyTransport,
    ReadOnlyViolation,
    Transport,
    TransportError,
    sanitize_error,
)
from collectors.common.types import CollectorResult
from collectors.intelbras_g08.parsers import (
    onus_from_macs,
    parse_ont_brief,
    parse_ont_mac_address,
)
from collectors.intelbras_g08.readonly import (
    COLLECTOR_VERSION,
    G08_MAC_COMMAND_FALLBACK,
    G08_MAC_COMMANDS,
    G08_READ_ALLOWLIST,
)

DOCUMENTED_COMMANDS = {
    "ont_mac_address": "show ont mac-address",
    "ont_mac_table": "show ont mac-address-table interface gpon all",
    "ont_brief": "show ont brief interface gpon all",
    "ont_find": "show ont-find list interface gpon all",
}


class IntelbrasG08Collector:
    collector_type = "intelbras_g08"
    collector_version = COLLECTOR_VERSION

    def __init__(self, secret_provider: str, secret_prefix: str, transport: Optional[Transport] = None):
        self.secret_provider = secret_provider
        self.secret_prefix = secret_prefix
        self._transport = transport

    def collect_from_texts(
        self,
        *,
        ont_brief_text: str = "",
        mac_table_text: str = "",
        mac_command: str = "show ont mac-address",
    ) -> CollectorResult:
        olt_macs = (
            parse_ont_mac_address(mac_table_text, command=mac_command, source="olt")
            if mac_table_text
            else []
        )
        onus = parse_ont_brief(ont_brief_text) if ont_brief_text else onus_from_macs(olt_macs)
        return CollectorResult(
            onus=onus,
            olt_macs=olt_macs,
            meta={
                "mode": "text",
                "documented_commands": DOCUMENTED_COMMANDS,
                "collector_version": self.collector_version,
                "completeness": "complete" if olt_macs or onus else "none",
            },
        )

    def collect_via_transport(self, transport: Transport) -> CollectorResult:
        guarded = ReadOnlyTransport(transport, G08_READ_ALLOWLIST)
        texts: dict[str, str] = {}
        errors: list[str] = []
        ok = failed = 0
        used_command = G08_MAC_COMMANDS[0][1]
        for key, command in G08_MAC_COMMANDS:
            try:
                result = guarded.execute(command)
            except ReadOnlyViolation as exc:
                errors.append(sanitize_error(str(exc)))
                failed += 1
                continue
            except TransportError as exc:
                errors.append(sanitize_error(str(exc)))
                failed += 1
                continue
            body = result.stdout or ""
            if result.ok and body.strip() and not _looks_incomplete(body):
                texts[key] = body
                used_command = command
                ok += 1
                continue
            try:
                fallback = guarded.execute(G08_MAC_COMMAND_FALLBACK)
            except (ReadOnlyViolation, TransportError) as exc:
                errors.append(sanitize_error(str(exc)))
                failed += 1
                continue
            if fallback.ok and (fallback.stdout or "").strip():
                texts[key] = fallback.stdout
                used_command = G08_MAC_COMMAND_FALLBACK
                ok += 1
            else:
                errors.append(sanitize_error(fallback.stderr or "empty mac-address output"))
                failed += 1

        parsed = self.collect_from_texts(
            mac_table_text=texts.get("mac_table", ""),
            mac_command=used_command,
        )
        if failed == 0 and ok:
            completeness = "complete"
            status = "ok"
        elif ok == 0:
            completeness = "none"
            status = "error"
        else:
            completeness = "partial"
            status = "partial"
        parsed.meta.update(
            {
                "mode": "transport",
                "status": status,
                "completeness": completeness,
                "commands_ok": ok,
                "commands_failed": failed,
                "collector_version": self.collector_version,
                "command": used_command,
                "error_summary": "; ".join(errors) if errors else None,
            }
        )
        return parsed

    def collect_live(self) -> CollectorResult:
        if self._transport is not None:
            return self.collect_via_transport(self._transport)
        secrets = resolve_secrets(self.secret_provider, self.secret_prefix)
        if secrets is None:
            return CollectorResult(
                meta={
                    "mode": "live",
                    "status": "skipped",
                    "completeness": "none",
                    "reason": "secrets_unavailable",
                    "collector_version": self.collector_version,
                }
            )
        transport = InteractiveCliTransport(secrets, timeout_sec=180)
        return self.collect_via_transport(transport)


def _looks_incomplete(text: str) -> bool:
    low = text.lower()
    return (
        "ambiguous" in low
        or "incomplete" in low
        or "unknown command" in low
        or "username or password error" in low
        or "username(1-64" in low
    )
