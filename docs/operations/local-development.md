# Local development

Docker-first operations for this repository. Host needs Docker, Compose, and Git only.

Secrets, customer IPs, and lab dotenv files stay **outside** Git. Copy `.env.example` → `.env` and keep real values gitignored.

## Bring the stack up

```bash
cp .env.example .env
docker compose config
make build
make up
make migrate
make seed
make test
```

Health:

- API: `http://127.0.0.1:8000/health` (process) and `/ready` (database). OpenAPI at `/docs`
- MCP: `http://127.0.0.1:8081/health` and `/ready`
- Full stack check: `./scripts/validate-deployment.sh`

Makefile wrappers: `build`, `up`, `down`, `logs`, `migrate`, `test`, `seed`, `secret-scan`. Persistence restart (`test-persist`) and lab (`lab-collect`, `lab-validate`) exist only when defined in the local `Makefile`.

## Migrate

Always inside Compose:

```bash
make migrate
# equivalent: docker compose run --rm migrate
```

Never rewrite an Alembic revision that may already have been applied. Add a new file under `db/migrations/versions/`.

## Tests

```bash
make test
make secret-scan
```

Strategy and lab-only targets: [testing/strategy.md](../testing/strategy.md).

Lab collection is optional, private, and not public CI. If the Makefile defines `lab-collect`, pass `LAB_SECRETS_FILE` to a dotenv **outside** this repository. Do not commit that file or its command output.

## Collection status

After seed or a run:

```bash
curl -sf "http://127.0.0.1:8000/collection-runs?tenant=example-tenant"
curl -sf -X POST http://127.0.0.1:8081/tools/get_collection_status \
  -H 'content-type: application/json' \
  -d '{"tenant":"example-tenant"}'
```

MCP tools are `POST /tools/<name>`. Seed tenant slug: `.env` `SEED_TENANT_SLUG` (placeholder `example-tenant` in `.env.example`). Completeness and sanitized `error_summary` are the operational signal — not raw CLI.

## Backup / restore (local volume only)

Compose volume: `madalena_pgdata`. This is **development** data.

Backup:

```bash
docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > /tmp/madalena-ni-dev.sql
```

Restore (destroys current DB content):

```bash
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < /tmp/madalena-ni-dev.sql
```

Use the same user/database names as in your private `.env`. Do not paste real dumps into the repo.

To reset the volume entirely: `docker compose down` then remove the named volume only if you intend to wipe local data (`docker volume ls` / `docker volume rm …`). That is destructive; do not run it against anything but a local dev volume.

## Troubleshooting without leaking secrets

| Symptom | Check |
|---------|--------|
| API/MCP unhealthy | `make logs`; `/health`; `migrate` completed |
| Empty inventory | `make seed`; tenant slug on the query |
| Collector skipped | Missing `{PREFIX}_HOST` / user / password in runtime env — fix privately, do not log values |
| Partial runs | `collection-runs` completeness, `commands_failed`, sanitized `error_summary` |
| Cross-tenant 404 | Expected when the MAC exists only in another tenant |

Do not dump RouterOS/OLT output, `.env`, or `docker compose config` with resolved secrets into issues or PRs.
