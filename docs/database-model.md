# Database model

Concepts (observation vs current view vs correlated conclusion): [data-model/concepts.md](data-model/concepts.md).

Core hierarchy: `tenants` → `sites` → `devices` → interfaces / observations.

Identity indexes: `mac_addresses`, `ip_addresses` (per-tenant unique). Canonical MAC: `AA:BB:CC:DD:EE:FF`. IPs stored via `ipaddress` canonical form (IPv4 first-class; IPv6 accepted). Timestamps are timezone-aware; collectors emit UTC.

## History

Observations are temporal. Upsert keys:

| Table | Upsert key |
|-------|------------|
| `dhcp_leases` | tenant, device, mac, ip |
| `arp_observations` | tenant, device, mac, ip, **interface** |
| `mac_observations` | tenant, device, mac, interface |
| `olt_mac_observations` | tenant, device, mac, ont, pon, VLAN, GEM |
| `neighbor_observations` | tenant, device, mac, ip, interface, identity, **protocol** |
| `inventory_node_observations` | tenant, controller device, source_id (else mac) |
| `topology_observations` | tenant, local device, local interface, remote_mac **or** remote_source_id **or** remote_identity, source, protocol |
| `interfaces` | device, name (last_seen updated; never deleted) |

A MAC that changes interface, IP, or observing device keeps the previous row (`first_seen` / `last_seen`). Current state is derived at query time.

Absence of a row in a later collection run is **not** proof of absence.

## Collection runs

`collection_runs`: tenant, site, device, collector_type, collector_version, status, completeness, command counts, record counts (`seen` / `created` / `updated` / `excluded`), `parse_failures`, sanitized error_summary, started_at, finished_at.

`devices.collectors_enabled` (JSON list) and `devices.collection_interval_sec` are runtime. `exclusion_policies` holds VLAN/CIDR/source/collector/interface rules per tenant (optional site/device). `devices.chassis_mac` / `devices.source_ref` are last-known identity hints for correlation (not Zabbix IDs).

Topology observations are **not** maps. A later Zabbix Map adapter should read this query layer; do not store Zabbix IDs on topology rows.

## Physical topology entities (migration 007)

`Interface` is a first-class entity and each device guards its interfaces with
`unique(device_id, name)`. Temporal evidence per interface lives in
`interface_observations` (a new row on each observed change; raw `evidence` and
`source_identifiers` preserved — ingestion never collapses history).

| Table | Purpose | Provenance kept |
|-------|---------|-----------------|
| `interfaces` | current per-interface fact (owned by one `device_id`) | `first_seen` / `last_seen` / `source` / `collection_run_id` |
| `interface_observations` | temporal per-interface evidence (name/desc/type/status/mac) | `observed_at` / `source` / `collection_run_id` / raw `evidence` |
| `device_identifiers` | trustworthy identity tokens used to correlate links (chassis-id, serial, source_id, mac, mgmt ip) | `kind` / `value` / `source` / `first_seen` / `last_seen` |
| `physical_links` | one consolidated link between two devices, tenant-scoped | `directly_observed` / `inferred` / `confidence` / first/last_seen / `source` / `protocol` |
| `link_evidence` | each contributing observation/source for a link | `source` / `protocol` / `observed_at` / `directly_observed` / `inferred` / `confidence` / raw `evidence` |

- `physical_links` is protected by `unique(tenant_id, device_a_id, device_b_id)`:
  observations from different collectors (e.g. MikroTik neighbor + UniFi uplink)
  that resolve to the same device pair consolidate into ONE row.
- Correlation uses `device_identifiers` (MAC, chassis-id, serial, source_id,
  management IP). A name-only or ambiguous identifier never materializes a link —
  evidence must be sufficient.
- Downlink is never inferred by blindly inverting an uplink; it requires its own
  reverse evidence.

A link between two interfaces anchors on `interface_a_id` / `interface_b_id`
(0..1 allowed); a link between two devices without port evidence still persists
with `interface_*_id` NULL.

## Indexes (query paths)

- `(tenant_id, mac)` on DHCP, ARP, FDB, neighbors, `mac_addresses`
- `(tenant_id, ip_address)` on DHCP, ARP, neighbors
- `(tenant_id, started_at)` on `collection_runs`

## Secrets

`device_credentials_reference` stores only `secret_provider` + `secret_prefix`.

## Migrations

Alembic under `db/migrations/` — run only inside containers (`docker compose run --rm migrate`).
