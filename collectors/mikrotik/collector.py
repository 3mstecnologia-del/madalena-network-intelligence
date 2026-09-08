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
from collectors.common.types import CollectorResult, NormalizedTopologyLink
from collectors.mikrotik.parsers import (
    parse_arp,
    parse_bridge_fdb,
    parse_dhcp_leases,
    parse_dhcp_report,
    parse_identity,
    parse_interfaces,
    parse_neighbors,
)
from collectors.mikrotik.readonly import (
    COLLECTOR_VERSION,
    MIKROTIK_DHCP_COMMANDS,
    MIKROTIK_FULL_COMMANDS,
    MIKROTIK_LIGHT_COMMANDS,
    MIKROTIK_READ_ALLOWLIST,
    MIKROTIK_STEP_COLLECTOR,
)


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
        neighbors = parse_neighbors(neighbors_text) if neighbors_text else []
        return CollectorResult(
            dhcp=parse_dhcp_leases(dhcp_text) if dhcp_text else [],
            arp=parse_arp(arp_text) if arp_text else [],
            fdb=parse_bridge_fdb(fdb_text) if fdb_text else [],
            identity=parse_identity(identity_text) if identity_text else None,
            interfaces=parse_interfaces(interfaces_text) if interfaces_text else [],
            neighbors=neighbors,
            topology_links=[
                NormalizedTopologyLink(
                    local_interface=n.interface,
                    remote_mac=n.mac,
                    remote_ip=n.ip_address,
                    remote_identity=n.identity,
                    remote_chassis_id=n.chassis_id,
                    remote_interface=n.remote_interface,
                    protocol=n.protocol,
                    observed_at=n.observed_at,
                    source=n.source,
                    evidence={"protocol": n.protocol, "chassis_id": n.chassis_id},
                )
                for n in neighbors
            ],
            meta={
                "mode": "text",
                "routeros_target": "7",
                "collector_version": self.collector_version,
                "completeness": "complete",
            },
        )

    def collect_via_transport(
        self,
        transport: Transport,
        *,
        lightweight: bool = True,
        dhcp_only: bool = False,
        enabled_collectors: Optional[frozenset[str]] = None,
    ) -> CollectorResult:
        guarded = ReadOnlyTransport(transport, MIKROTIK_READ_ALLOWLIST)
        if dhcp_only:
            steps = list(MIKROTIK_DHCP_COMMANDS)
        else:
            steps = list(MIKROTIK_LIGHT_COMMANDS if lightweight else MIKROTIK_FULL_COMMANDS)
        if enabled_collectors is not None:
            steps = [(k, c) for k, c in steps if MIKROTIK_STEP_COLLECTOR.get(k, k) in enabled_collectors]
        if not steps:
            return CollectorResult(
                meta={
                    "mode": "transport",
                    "status": "skipped",
                    "completeness": "none",
                    "reason": "no_enabled_collectors",
                    "collector_version": self.collector_version,
                }
            )
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
        dhcp_report = parse_dhcp_report(texts.get("dhcp", ""))
        parsed = self.collect_from_texts(
            dhcp_text=texts.get("dhcp", ""),
            arp_text=texts.get("arp", ""),
            fdb_text=texts.get("fdb", ""),
            identity_text=texts.get("identity", "") + "\n" + texts.get("resource", ""),
            interfaces_text=texts.get("interfaces", ""),
            neighbors_text=texts.get("neighbors", ""),
        )
        parsed.dhcp = dhcp_report.leases
        parse_failures = dhcp_report.parse_failures if dhcp_only or texts.get("dhcp") else 0
        if failed == 0 and parse_failures == 0:
            completeness = "complete"
            status = "ok"
        elif ok == 0:
            completeness = "none"
            status = "error"
        else:
            completeness = "partial"
            status = "partial"
        if failed == 0 and parse_failures:
            completeness = "partial"
            status = "partial"
        parsed.meta.update(
            {
                "mode": "transport",
                "status": status,
                "completeness": completeness,
                "commands_ok": ok,
                "commands_failed": failed,
                "parse_failures": parse_failures,
                "dhcp_entries_seen": dhcp_report.entries_seen,
                "collector_version": self.collector_version,
                "error_summary": "; ".join(errors) if errors else None,
            }
        )
        return parsed

    def collect_live(
        self,
        *,
        lightweight: bool = True,
        dhcp_only: bool = False,
        enabled_collectors: Optional[frozenset[str]] = None,
    ) -> CollectorResult:
        if self._transport is not None:
            return self.collect_via_transport(
                self._transport,
                lightweight=lightweight,
                dhcp_only=dhcp_only,
                enabled_collectors=enabled_collectors,
            )
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
        proto = (secrets.protocol or "ssh").lower()
        if proto in {"ssh", "ssh2"}:
            # OpenSSH CLI transport handles MikroTik RouterOS 7 servers whose
            # banner paramiko cannot read ("Error reading SSH protocol banner").
            from collectors.mikrotik.transport_openssh import OpenSshCliTransport

            transport = OpenSshCliTransport(secrets, timeout_sec=90)
        elif proto in {"telnet", "telnet23"}:
            from collectors.common.cli_interactive import InteractiveCliTransport

            transport = InteractiveCliTransport(secrets, timeout_sec=90)
        elif proto in {"api", "routeros-api"}:
            from collectors.mikrotik.transport_api import RouterOsApiTransport

            transport = RouterOsApiTransport(secrets)
        else:
            return CollectorResult(
                meta={
                    "mode": "live",
                    "status": "error",
                    "completeness": "none",
                    "reason": "unsupported_mikrotik_protocol",
                    "collector_version": self.collector_version,
                }
            )
        result = self.collect_via_transport(
            transport,
            lightweight=lightweight,
            dhcp_only=dhcp_only,
            enabled_collectors=enabled_collectors,
        )
        if hasattr(transport, "last_diag"):
            result.meta["ssh_diag"] = {
                k: v for k, v in transport.last_diag.items() if k != "host"
            }
        return result
