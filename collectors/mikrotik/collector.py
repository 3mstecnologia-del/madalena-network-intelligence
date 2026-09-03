"""MikroTik RouterOS collector — transport separated from parsers.

Phase 1: dry-run / fixture mode. Live SSH/REST planned; secrets via Infisical refs.
"""

from __future__ import annotations

from typing import Optional

from collectors.common.secrets import resolve_secrets
from collectors.common.types import CollectorResult
from collectors.mikrotik.parsers import parse_arp, parse_bridge_fdb, parse_dhcp_leases


class MikroTikCollector:
    """Collect DHCP, ARP, bridge FDB from RouterOS 7."""

    collector_type = "mikrotik"

    def __init__(self, secret_provider: str, secret_prefix: str):
        self.secret_provider = secret_provider
        self.secret_prefix = secret_prefix

    def collect_from_texts(
        self,
        *,
        dhcp_text: str = "",
        arp_text: str = "",
        fdb_text: str = "",
    ) -> CollectorResult:
        return CollectorResult(
            dhcp=parse_dhcp_leases(dhcp_text) if dhcp_text else [],
            arp=parse_arp(arp_text) if arp_text else [],
            fdb=parse_bridge_fdb(fdb_text) if fdb_text else [],
            meta={"mode": "text", "routeros_target": "7"},
        )

    def collect_live(self) -> CollectorResult:
        """Live collection — requires external secrets. Not used in Phase 1 CI."""
        secrets = resolve_secrets(self.secret_provider, self.secret_prefix)
        if secrets is None:
            return CollectorResult(
                meta={
                    "mode": "live",
                    "status": "skipped",
                    "reason": "secrets_unavailable",
                    "todo": "Wire SSH/REST transport after Infisical integration",
                }
            )
        # Transport not implemented in Phase 1 (no lab calls).
        return CollectorResult(
            meta={
                "mode": "live",
                "status": "not_implemented",
                "todo": "Implement SSH and/or REST transport for RouterOS 7",
                "host_configured": True,
            }
        )
