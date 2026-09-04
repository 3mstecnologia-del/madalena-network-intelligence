# Testing strategy

How this repository is tested. Global 3MS testing principles stay in User Rules; this file is the **product matrix**.

## What CI / default `make test` runs

`make test` → `docker compose run --rm --no-deps api pytest -q`

Public tests also cover policy exclusion (dropped rows never persist), multi-MikroTik DHCP, scheduler continuation after one device fails, topology correlation, UniFi inventory fixtures, and `/ready`.

There is no live collection in public CI. Do not add it.

## What requires Docker (and PostgreSQL)

| Target | What it proves |
|--------|----------------|
| `make test` | Public pytest (SQLite in-memory for most tests; no live gear) |
| `make migrate` | Alembic against Compose Postgres |
| `make test-persist` | Write → restart `db` → read (when this target exists) |
| `make secret-scan` | Tracked files vs leak patterns (inside the API image) |

Use Compose. Do not install Python/Postgres on the host to run the suite.

## What is lab-only

Lab Makefile targets (`lab-collect`, `lab-diag`, `lab-validate`) when present, with `LAB_SECRETS_FILE` pointing **outside** this repo.

- Credentials are runtime-only
- Not executed by public CI
- Real CLI output must **never** become a Git fixture
- CODE PASS ≠ LAB PASS ≠ operational pass

## Categories

### Unit

Parsers, MAC/IP normalization, correlation pure logic, error sanitization, future policy filters (VLAN/network exclusion).

Fixtures: synthetic text that preserves vendor syntax. See [adding a collector](../development/adding-a-collector.md).

### Integration

PostgreSQL + migrations when the behavior depends on real SQL; persistence upserts; history; tenant isolation; HTTP API; MCP HTTP tools.

If the consumer is API or MCP, do not treat “the row is in SQL” as the only proof.

### Transport contract

Success, timeout, EOF, authentication failure, malformed output, partial output, custom port, read-only allowlist rejection.

Tests use in-memory/fake transports (`MemoryTransport` or equivalent). Live SSH belongs in lab-only scripts.

### Collector completeness

| Result | When |
|--------|------|
| **complete** | Approved commands succeeded **and** the parser did not drop material lines |
| **partial** | Some commands or some lines failed/unparsed; some observations may still be stored |
| **failed** | Transport/auth/command failure such that the run cannot be trusted as a collection |
| **indeterminate** | Skipped, not implemented, missing secrets, or unknown |

If the command executed but the parser lost lines, the run is **not** complete.

The `collection_runs` table currently stores `status` plus `completeness` (`complete` / `partial` / `none` / `unknown`). Map honestly onto those fields. Renaming to the four words above is a versioned contract change.

Record when possible: seen / created / updated, parse failures, sanitized errors, started_at / finished_at, collector version, device/source.

Repeated ingest of the same observation key must be idempotent (update `last_seen`, not duplicate rows).

### Security

- Cross-tenant: MAC/IP/device/run of tenant A never appears in tenant B
- Unsafe / non-allowlisted commands blocked
- Secrets and management hosts redacted from logs, `error_summary`, API, MCP
- No command injection from tenant config or request bodies (collectors do not execute caller-supplied CLI)

### Persistence

- Restart Postgres (`make test-persist` or equivalent) and still read history
- Repeated collection does not invent duplicate current-state rows for the same upsert key
- Temporal history kept when the key changes

## Adding a regression test

1. Reproduce with a **synthetic** fixture or in-memory DB.
2. Assert the behavior that failed (parser line, completeness, 404 across tenants, conflict list, etc.).
3. Fix minimally.
4. If API/MCP contract changed, extend `tests/test_api.py` / `tests/test_mcp.py` and docs.

## Definition of done (collectors)

| Gate | Meaning |
|------|---------|
| Implementation | Code + allowlist + parser |
| Test | Public pytest covers happy, malformed, partial, allowlist |
| Lab validation | Optional; private; documented as lab-only |
| Operational validation | Production/tenant rollout — out of scope for Git |

A collector is not “done” because unit tests passed.
