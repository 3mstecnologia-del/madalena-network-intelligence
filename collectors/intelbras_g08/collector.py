"""Intelbras G08 collector — structure + fixture parsers.

Live transport is intentionally not called in Phase 1.
Operational CLI knowledge lives in hermes skill olt-intelbras-g08-ops.
"""

from __future__ import annotations

from collectors.common.secrets import resolve_secrets
from collectors.common.types import CollectorResult
from collectors.intelbras_g08.parsers import parse_ont_brief, parse_ont_mac_address_table

# Documented read commands (from skill) — do not invent new ones.
DOCUMENTED_COMMANDS = {
    "identity_todo": "TODO: confirm exact identity/show version command on G08 lab",
    "ont_brief": "show ont brief interface gpon all",
    "ont_mac_table": "show ont mac-address-table interface gpon all",
    "ont_find": "show ont-find list interface gpon all",
    "mac_vlan": "show mac-address-table dynamic vlan <vlan>",
}


class IntelbrasG08Collector:
    collector_type = "intelbras_g08"

    def __init__(self, secret_provider: str, secret_prefix: str):
        self.secret_provider = secret_provider
        self.secret_prefix = secret_prefix

    def collect_from_texts(
        self,
        *,
        ont_brief_text: str = "",
        mac_table_text: str = "",
    ) -> CollectorResult:
        return CollectorResult(
            onus=parse_ont_brief(ont_brief_text) if ont_brief_text else [],
            olt_macs=parse_ont_mac_address_table(mac_table_text) if mac_table_text else [],
            meta={
                "mode": "text",
                "documented_commands": DOCUMENTED_COMMANDS,
            },
        )

    def collect_live(self) -> CollectorResult:
        secrets = resolve_secrets(self.secret_provider, self.secret_prefix)
        if secrets is None:
            return CollectorResult(
                meta={
                    "mode": "live",
                    "status": "skipped",
                    "reason": "secrets_unavailable",
                }
            )
        return CollectorResult(
            meta={
                "mode": "live",
                "status": "not_implemented",
                "todo": "SSH transport + enable/paging handling; no live UNIPLAC calls in Phase 1",
                "documented_commands": DOCUMENTED_COMMANDS,
            }
        )
