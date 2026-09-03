# Database model

Core hierarchy: `tenants` → `sites` → `devices` → interfaces / observations.

Identity indexes: `mac_addresses`, `ip_addresses` (per-tenant unique). Canonical MAC: `AA:BB:CC:DD:EE:FF`. IPs stored via `ipaddress` canonical form (IPv4 first-class; IPv6 accepted). Timestamps are timezone-aware; collectors emit UTC.

## History

Observations are temporal. Upsert keys:

| Table | Upsert key |
|-------|------------|
| `dhcp_leases` | tenant, device, mac, ip |
| `arp_observations` | tenant, device, mac, ip, **interface** |
| `mac_observations` | tenant, device, mac, interface |
| `neighbor_observations` | tenant, device, mac, ip, interface, identity |
| `interfaces` | device, name (last_seen updated; never deleted) |

A MAC that changes interface, IP, or observing device keeps the previous row (`first_seen` / `last_seen`). Current state is derived at query time.

Absence of a row in a later collection run is **not** proof of absence.

## Collection runs

`collection_runs`: tenant, site, device, collector_type, collector_version, status, completeness, command counts, record counts, sanitized error_summary, started_at, finished_at.

## Indexes (query paths)

- `(tenant_id, mac)` on DHCP, ARP, FDB, neighbors, `mac_addresses`
- `(tenant_id, ip_address)` on DHCP, ARP, neighbors
- `(tenant_id, started_at)` on `collection_runs`

## Secrets

`device_credentials_reference` stores only `secret_provider` + `secret_prefix`.

## Migrations

Alembic under `db/migrations/` — run only inside containers (`docker compose run --rm migrate`).
