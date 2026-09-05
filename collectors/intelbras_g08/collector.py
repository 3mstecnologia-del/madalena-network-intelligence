"""Intelbras G08 collector — parsers + optional live interactive CLI.

Live path uses runtime secrets + a show-only allowlist. The G08 driver command is
`show ont mac-address-table interface gpon all` (live evidence: the short form
`show ont mac-address` is incomplete on this family). Tests use MemoryTransport
or collect_from_texts.
"""

from __future__ import annotations

import re
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
    parse_ont_mac_address_with_count,
)
from collectors.intelbras_g08.readonly import (
    COLLECTOR_VERSION,
    G08_FAMILY,
    G08_MAC_TABLE_COMMAND,
    G08_READ_ALLOWLIST,
)

DOCUMENTED_COMMANDS = {
    "ont_mac_table": G08_MAC_TABLE_COMMAND,
    "ont_brief": "show ont brief interface gpon all",
    "ont_find": "show ont-find list interface gpon all",
}

_TOTAL = re.compile(r"(?i)total entries:\s*(\d+)")


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
        mac_command: str = G08_MAC_TABLE_COMMAND,
    ) -> CollectorResult:
        olt_macs, parsed_rows = (
            parse_ont_mac_address_with_count(mac_table_text, command=mac_command, source="olt")
            if mac_table_text
            else ([], 0)
        )
        onus = parse_ont_brief(ont_brief_text) if ont_brief_text else onus_from_macs(olt_macs)
        declared = _declared_total(mac_table_text)
        parse_failures = abs(declared - parsed_rows) if declared is not None else 0
        if olt_macs and parse_failures == 0:
            completeness = "complete"
        elif olt_macs:
            completeness = "partial"
        else:
            completeness = "none"
        return CollectorResult(
            onus=onus,
            olt_macs=olt_macs,
            meta={
                "mode": "text",
                "family": G08_FAMILY,
                "documented_commands": DOCUMENTED_COMMANDS,
                "collector_version": self.collector_version,
                "command": mac_command,
                "declared_entries": declared,
                "parsed_entries": parsed_rows,
                "parse_failures": parse_failures,
                "completeness": completeness,
            },
        )

    def collect_via_transport(self, transport: Transport) -> CollectorResult:
        guarded = ReadOnlyTransport(transport, G08_READ_ALLOWLIST)
        command = G08_MAC_TABLE_COMMAND
        try:
            result = guarded.execute(command)
        except ReadOnlyViolation as exc:
            return self._failed(sanitize_error(str(exc)), command)
        except TransportError as exc:
            return self._failed(sanitize_error(str(exc)), command)
        body = result.stdout or ""
        if not result.ok or not body.strip():
            return self._failed(sanitize_error(result.stderr or "empty mac-address-table output"), command)
        parsed = self.collect_from_texts(mac_table_text=body, mac_command=command)
        completeness = parsed.meta.get("completeness", "none")
        status = "ok" if completeness == "complete" else ("partial" if completeness == "partial" else "error")
        parsed.meta.update(
            {
                "mode": "transport",
                "status": status,
                "commands_ok": 1,
                "commands_failed": 0,
                "collector_version": self.collector_version,
                "command": command,
                "family": G08_FAMILY,
            }
        )
        return parsed

    def collect_live(self, *, enabled_collectors: Optional[frozenset[str]] = None) -> CollectorResult:
        if enabled_collectors is not None and "ont_mac_table" not in enabled_collectors:
            return CollectorResult(
                meta={
                    "mode": "live",
                    "status": "skipped",
                    "completeness": "none",
                    "reason": "no_enabled_collectors",
                    "collector_version": self.collector_version,
                    "family": G08_FAMILY,
                    "command": G08_MAC_TABLE_COMMAND,
                }
            )
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
                    "family": G08_FAMILY,
                    "command": G08_MAC_TABLE_COMMAND,
                }
            )
        transport = InteractiveCliTransport(secrets, timeout_sec=180)
        return self.collect_via_transport(transport)

    def _failed(self, error: str, command: str) -> CollectorResult:
        return CollectorResult(
            meta={
                "mode": "transport",
                "status": "error",
                "completeness": "none",
                "commands_ok": 0,
                "commands_failed": 1,
                "collector_version": self.collector_version,
                "command": command,
                "family": G08_FAMILY,
                "error_summary": error,
            }
        )


def _declared_total(text: str) -> Optional[int]:
    m = _TOTAL.search(text or "")
    if not m:
        return None
    return int(m.group(1))
