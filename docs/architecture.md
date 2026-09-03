# Architecture

## Data flow

```
Collectors → Scheduler → Normalization → PostgreSQL → Correlation Engine → REST API + MCP → Hermes/Madalena
```

1. Scheduler triggers collectors per interval (MikroTik light / OLT / full inventory).
2. Collectors receive **runtime credentials** via `secret_provider` + `secret_prefix` (environment mapping). No passwords in Git or PostgreSQL.
3. A `Transport.execute(command)` returns raw CLI text. Parsers are transport-agnostic.
4. Ingest upserts temporal observations. Matching keys update `last_seen`; a new key (MAC moved interface/IP/device) inserts a **new row**. Rows are never deleted because a later run omitted them.
5. Correlation derives current state from latest timestamps and exposes `conflicts` when evidence disagrees. Raw history remains.
6. REST API and MCP tools expose tenant-scoped queries. Tenant slug is required on every operational path.

## Isolation

Every observation table carries `tenant_id`. Query services require tenant slug. The same MAC in two tenants is two identities.

## Collection run lifecycle

Each execution has its own `collection_runs` row:

- tenant, site, device
- started_at / finished_at (UTC)
- collector type + version
- status (`running` | `success` | `partial` | `error` | `skipped` | `not_implemented`)
- completeness (`complete` | `partial` | `none` | `unknown`)
- records_seen / created / updated
- commands_ok / commands_failed
- sanitized error_summary
- freshness is derived (`now - finished_at`)

A device failure records an error/partial run and **does not** delete prior observations. Absence of an interface in one run is not treated as proof the interface is gone.

## Transport (MikroTik)

```
ReadOnlyTransport(allowlist)
    → Transport.execute(command)
    → raw RouterOS text
    → parsers
    → normalized observations
    → ingest
```

- Collectors must not know customer hosts, tunnels, or secret names.
- Live path: `SshTransport` + runtime `DeviceSecrets`. Tests: `MemoryTransport`.
- Allowlist is print/get only. Tokens `add` / `set` / `remove` / `enable` / `disable` / `move` are refused. Parser failure never issues a fallback mutation.

## Correlation

Joins by `(tenant_id, mac)` / `(tenant_id, ip)`. Current IPs and locations are those sharing the latest observation timestamp. Multiple values at that timestamp become `conflicts` (`ambiguous_ip`, `ambiguous_device`, `ambiguous_location`). Provenance (`source`, `device`, `collection_run_id`) is kept on timeline events.

## Containers

| Service | Role |
|---------|------|
| `db` | PostgreSQL 16 |
| `migrate` | Alembic one-shot |
| `api` | FastAPI |
| `scheduler` | APScheduler worker |
| `mcp` | MCP tools HTTP (`mcp_server`) |

Network: Docker bridge `madalena`. Named volume `madalena_pgdata`.
