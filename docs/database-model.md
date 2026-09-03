# Database model

Core hierarchy: `tenants` → `sites` → `devices` → interfaces / observations.

Identity: `mac_addresses`, `ip_addresses` (per-tenant unique).

Observations (temporal): `dhcp_leases`, `arp_observations`, `mac_observations`, `olt_mac_observations`, `olt_onus`, `olt_profiles`.

Ops: `data_sources`, `collection_runs`.

Secrets: `device_credentials_reference` stores only `secret_provider` + `secret_prefix`.

Canonical MAC format: `AA:BB:CC:DD:EE:FF`.

Migrations: Alembic under `db/migrations/` — run only inside containers.
