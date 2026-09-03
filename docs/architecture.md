# Architecture

## Data flow

1. Scheduler triggers collectors per interval (MikroTik light / OLT / full inventory).
2. Collectors resolve secrets via external provider reference (`secret_prefix`), never from DB passwords.
3. Parsers emit normalized objects; ingest upserts temporal observations.
4. Correlation engine joins by `(tenant_id, mac)` without deleting raw rows.
5. REST API and MCP tools expose tenant-scoped queries.

## Isolation

Every observation table carries `tenant_id`. Query services require tenant slug. MAC equality across tenants must not leak.

## Containers

| Service | Role |
|---------|------|
| `db` | PostgreSQL 16 |
| `migrate` | Alembic one-shot |
| `api` | FastAPI |
| `scheduler` | APScheduler worker |
| `mcp` | MCP tools HTTP (`mcp_server`) |

Network: Docker bridge `madalena`. Named volume `madalena_pgdata`.
