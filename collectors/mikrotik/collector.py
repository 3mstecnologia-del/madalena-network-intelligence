"""MikroTik RouterOS collector — transport separated from parsers.

Read-only. Live SSH uses runtime secrets + allowlisted commands. Tests use
MemoryTransport / collect_from_texts. No customer hostnames in this module.
"""

from __future__ import annotations

from typing import Optional

from collectors.common.secrets import resolve_secrets
from collectors.common.transport import (
    ReadOnlyTransport,
    ReadOnlyViolation,
    Transport,
    TransportError,
    sanitize_error,
)
from collectors.common.types import CollectorResult
from collectors.mikrotik.parsers import (
    parse_arp,
    parse_bridge_fdb,
    parse_dhcp_leases,
    parse_identity,
    parse_interfaces,
    parse_neighbors,
)
from collectors.mikrotik.readonly import (
    COLLECTOR_VERSION,
    MIKROTIK_FULL_COMMANDS,
    MIKROTIK_LIGHT_COMMANDS,
    MIKROTIK_READ_ALLOWLIST,
)
from collectors.mikrotik.transport_ssh import SshTransport


class MikroTikCollector:
    """Collect DHCP, ARP, bridge FDB, identity, interfaces, neighbors (ROS7)."""

    collector_type = "mikrotik"
    collector_version = COLLECTOR_VERSION

    def __init__(self, secret_provider: str, secret_prefix: str, transport: Optional[Transport] = None):
        self.secret_provider = secret_provider
        self.secret_prefix = secret_prefix
        self._transport = transport

    def collect_from_texts(
        self,
        *,
        dhcp_text: str = "",
        arp_text: str = "",
        fdb_text: str = "",
        identity_text: str = "",
        interfaces_text: str = "",
        neighbors_text: str = "",
    ) -> CollectorResult:
        return CollectorResult(
            dhcp=parse_dhcp_leases(dhcp_text) if dhcp_text else [],
            arp=parse_arp(arp_text) if arp_text else [],
            fdb=parse_bridge_fdb(fdb_text) if fdb_text else [],
            identity=parse_identity(identity_text) if identity_text else None,
            interfaces=parse_interfaces(interfaces_text) if interfaces_text else [],
            neighbors=parse_neighbors(neighbors_text) if neighbors_text else [],
            meta={
                "mode": "text",
                "routeros_target": "7",
                "collector_version": self.collector_version,
                "completeness": "complete",
            },
        )

    def collect_via_transport(self, transport: Transport, *, lightweight: bool = True) -> CollectorResult:
        guarded = ReadOnlyTransport(transport, MIKROTIK_READ_ALLOWLIST)
        steps = MIKROTIK_LIGHT_COMMANDS if lightweight else MIKROTIK_FULL_COMMANDS
        texts: dict[str, str] = {}
        errors: list[str] = []
        ok = failed = 0
        for key, command in steps:
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
            if not result.ok:
                errors.append(sanitize_error(result.stderr or f"exit {result.exit_status}"))
                failed += 1
                continue
            texts[key] = result.stdout
            ok += 1
        parsed = self.collect_from_texts(
            dhcp_text=texts.get("dhcp", ""),
            arp_text=texts.get("arp", ""),
            fdb_text=texts.get("fdb", ""),
            identity_text=texts.get("identity", "") + "\n" + texts.get("resource", ""),
            interfaces_text=texts.get("interfaces", ""),
            neighbors_text=texts.get("neighbors", ""),
        )
        if failed == 0:
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
                "error_summary": "; ".join(errors) if errors else None,
            }
        )
        return parsed

    def collect_live(self, *, lightweight: bool = True) -> CollectorResult:
        if self._transport is not None:
            return self.collect_via_transport(self._transport, lightweight=lightweight)
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
        transport = SshTransport(secrets)
        return self.collect_via_transport(transport, lightweight=lightweight)
