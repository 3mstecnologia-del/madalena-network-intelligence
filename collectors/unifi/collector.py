"""UniFi Network Integration API collector — GET only.

Live HTTP uses runtime BASE_URL + API_KEY. Tests use MemoryUnifiClient.
Do not invent endpoints. Uplink/port fields are optional.
"""

from __future__ import annotations

from typing import Any, Optional

from collectors.common.secrets import resolve_secrets
from collectors.common.transport import ReadOnlyViolation, TransportError, sanitize_error
from collectors.common.types import CollectorResult, NormalizedInterface, NormalizedInventoryNode
from collectors.unifi.parsers import (
    parse_device_interfaces,
    parse_device_list,
    parse_device_payload,
    parse_sites,
    topology_from_inventory,
)
from collectors.unifi.readonly import COLLECTOR_VERSION
from collectors.unifi.transport_http import MemoryUnifiClient, UnifiHttpClient, UnifiJsonClient

PAGE_LIMIT = 200


class UnifiNetworkCollector:
    collector_type = "unifi_network"
    collector_version = COLLECTOR_VERSION

    def __init__(
        self,
        secret_provider: str,
        secret_prefix: str,
        client: Optional[UnifiJsonClient] = None,
    ):
        self.secret_provider = secret_provider
        self.secret_prefix = secret_prefix
        self._client = client

    def collect_from_payloads(
        self,
        *,
        devices_payload: Any = None,
        detail_payloads: Optional[list[Any]] = None,
        sites_payload: Any = None,
    ) -> CollectorResult:
        nodes_by_id: dict[str, NormalizedInventoryNode] = {}
        unnamed: list[NormalizedInventoryNode] = []
        for node in parse_device_list(devices_payload) if devices_payload is not None else []:
            if node.source_id:
                nodes_by_id[node.source_id] = node
            else:
                unnamed.append(node)
        interfaces: list[NormalizedInterface] = []
        for detail in detail_payloads or []:
            node = parse_device_payload(detail)
            if node is not None and node.source_id:
                nodes_by_id[node.source_id] = node
            elif node is not None:
                unnamed.append(node)
            interfaces.extend(parse_device_interfaces(detail))
        nodes = unnamed + list(nodes_by_id.values())
        links = [link for n in nodes if (link := topology_from_inventory(n)) is not None]
        sites = parse_sites(sites_payload) if sites_payload is not None else []
        return CollectorResult(
            inventory_nodes=nodes,
            topology_links=links,
            interfaces=interfaces,
            meta={
                "mode": "payload",
                "collector_version": self.collector_version,
                "completeness": "complete" if nodes else "none",
                "status": "ok",
                "sites": len(sites),
            },
        )

    def collect_via_client(
        self,
        client: UnifiJsonClient,
        *,
        site_id: Optional[str] = None,
        enabled_collectors: Optional[frozenset[str]] = None,
    ) -> CollectorResult:
        enabled = enabled_collectors or frozenset({"inventory", "device_details"})
        errors: list[str] = []
        ok = failed = 0
        info: Any = None
        try:
            info = client.get_json("/v1/info")
            ok += 1
        except (TransportError, ReadOnlyViolation) as exc:
            errors.append(sanitize_error(str(exc)))
            failed += 1

        sites: list[dict[str, str]] = []
        if "inventory" in enabled:
            try:
                sites = parse_sites(self._paginate(client, "/v1/sites"))
                ok += 1
            except (TransportError, ReadOnlyViolation) as exc:
                errors.append(sanitize_error(str(exc)))
                failed += 1

        target_sites = [s for s in ([site_id] if site_id else [row["id"] for row in sites]) if s]
        list_payloads: list[Any] = []
        listed_by_site: dict[str, list] = {}
        if "inventory" in enabled:
            for sid in target_sites:
                try:
                    chunk = self._paginate(client, f"/v1/sites/{sid}/devices")
                    list_payloads.extend(chunk)
                    listed_by_site[sid] = parse_device_list(chunk)
                    ok += 1
                except (TransportError, ReadOnlyViolation) as exc:
                    errors.append(sanitize_error(str(exc)))
                    failed += 1

        details: list[Any] = []
        if "device_details" in enabled and listed_by_site:
            for sid, listed in listed_by_site.items():
                for node in listed:
                    if not node.source_id:
                        continue
                    try:
                        details.append(client.get_json(f"/v1/sites/{sid}/devices/{node.source_id}"))
                        ok += 1
                    except (TransportError, ReadOnlyViolation) as exc:
                        errors.append(sanitize_error(str(exc)))
                        failed += 1

        parsed = self.collect_from_payloads(
            devices_payload=list_payloads,
            detail_payloads=details,
            sites_payload=sites,
        )
        if failed == 0 and parsed.inventory_nodes:
            completeness, status = "complete", "ok"
        elif ok == 0:
            completeness, status = "none", "error"
        elif parsed.inventory_nodes:
            completeness, status = "partial", "partial"
        else:
            completeness, status = "none", "error" if failed else "ok"

        version = None
        if isinstance(info, dict):
            version = info.get("applicationVersion") or info.get("version")
        parsed.meta.update(
            {
                "mode": "http",
                "status": status,
                "completeness": completeness,
                "commands_ok": ok,
                "commands_failed": failed,
                "collector_version": self.collector_version,
                "error_summary": "; ".join(errors) if errors else None,
                "unifi_application_version": version,
                "sites": len(target_sites),
            }
        )
        return parsed

    def collect_live(self, *, enabled_collectors: Optional[frozenset[str]] = None) -> CollectorResult:
        if self._client is not None:
            secrets = resolve_secrets(self.secret_provider, self.secret_prefix)
            site = secrets.site if secrets else None
            return self.collect_via_client(
                self._client, site_id=site, enabled_collectors=enabled_collectors
            )
        secrets = resolve_secrets(self.secret_provider, self.secret_prefix)
        if secrets is None or not secrets.api_key or not (secrets.base_url or secrets.host):
            return CollectorResult(
                meta={
                    "mode": "live",
                    "status": "skipped",
                    "completeness": "none",
                    "reason": "secrets_unavailable",
                    "collector_version": self.collector_version,
                }
            )
        client = UnifiHttpClient(secrets)
        return self.collect_via_client(
            client, site_id=secrets.site, enabled_collectors=enabled_collectors
        )

    def _paginate(self, client: UnifiJsonClient, path: str) -> list[Any]:
        collected: list[Any] = []
        offset = 0
        while True:
            payload = client.get_json(path, params={"offset": offset, "limit": PAGE_LIMIT})
            if isinstance(payload, list):
                chunk = payload
            elif isinstance(payload, dict) and isinstance(payload.get("data"), list):
                chunk = payload["data"]
            else:
                chunk = []
            collected.extend(chunk)
            if len(chunk) < PAGE_LIMIT:
                break
            offset += PAGE_LIMIT
            if offset > 10000:
                break
        return collected


__all__ = ["UnifiNetworkCollector", "MemoryUnifiClient"]
