# Madalena deployment (lab)

Install Network Intelligence on a VPS with Docker. This is a laboratory service: read-only collectors, PostgreSQL history, API + MCP.

Do not put real passwords, hosts, VLANs, or customer names in Git. Inject them at runtime.

## 1. Prerequisites

- Docker and Docker Compose v2
- Git
- Outbound access from the VPS to the devices you will collect from (SSH/Telnet as configured)
- Infisical (or equivalent) **or** a private `.env` on the VPS — never commit it

Host Python/PostgreSQL installs are not required.

## 2. Clone / version

```bash
git clone https://github.com/3mstecnologia-del/madalena-network-intelligence.git
cd madalena-network-intelligence
git checkout <approved-ref>
```

Use the git tag or commit maintainers give you. Do not invent a version.

## 3. Runtime configuration

```bash
cp .env.example .env
```

Edit `.env` (private):

- `POSTGRES_PASSWORD` and matching `DATABASE_URL`
- `SECRET_PROVIDER=env` if secrets are in this `.env`, or keep `infisical` if an external sync injects the same keys
- Scheduler intervals (`SCHEDULER_MIKROTIK_INTERVAL_SEC`, `SCHEDULER_OLT_INTERVAL_SEC`) if you want other than the defaults
- Optional: `SEED_EXCLUDE_VLAN=<id>` only if you will run seed **and** want that VLAN dropped before persist (use the tenant’s real policy in private config, not in Git)

## 4. Secrets

For each device, the database stores only `secret_prefix` (for example `DEVICE_SITE_ROLE`). The process environment must provide:

```
{PREFIX}_HOST
{PREFIX}_USERNAME
{PREFIX}_PASSWORD
{PREFIX}_SSH_PORT     # optional, default 22
{PREFIX}_PROTOCOL     # optional, ssh | telnet (MikroTik also accepts api)
```

Infisical may sync those keys into the Compose environment. This app does not call Infisical as a client.

After first start, register tenant/site/device rows (seed for a synthetic lab, or insert your own labels). Point each device at its prefix. Enable collectors per device with JSON on `devices.collectors_enabled`, for example `["dhcp","arp","fdb"]`. Omit DHCP on routers that should not contribute leases.

Exclusion rules (VLAN, CIDR, source, collector, interface) live in `exclusion_policies`. They apply **after parse, before persist**.

## 5. Docker Compose

```bash
chmod +x scripts/bootstrap.sh scripts/validate-deployment.sh
SEED=true ./scripts/bootstrap.sh
```

Equivalent:

```bash
docker compose build
docker compose up -d
docker compose run --rm migrate
docker compose run --rm api python -m scripts.seed_lab   # synthetic labels only
```

Services: `db`, `migrate`, `api` (:8000), `scheduler`, `mcp` (:8081).

## 6. Migrations

Always:

```bash
docker compose run --rm migrate
```

Never rewrite applied Alembic revisions.

## 7. Health validation

`docker compose ps` is not enough.

```bash
./scripts/validate-deployment.sh
```

Checks:

- API `GET /health` (process up)
- API `GET /ready` (database)
- MCP `GET /health` and `GET /ready`
- PostgreSQL `pg_isready`

Scheduler health is the Compose healthcheck on a heartbeat file (alive loop, not “import succeeded”).

## 8. MCP validation

```bash
curl -sf http://127.0.0.1:8081/tools
curl -sf -X POST http://127.0.0.1:8081/tools/get_collection_status \
  -H 'content-type: application/json' \
  -d '{"tenant":"example-tenant"}'
```

Replace `example-tenant` with your tenant slug. Tools: `find_mac`, `find_ip`, `get_mac_history`, `get_collection_status` (plus inventory helpers). Tenant is required.

Manual collection cycle (no LLM):

```bash
docker compose run --rm scheduler python -m scheduler.main --once
```

## 9. Rollback / stop

Stop:

```bash
docker compose down
```

Data stays in volume `madalena_pgdata`. Wipe lab data only if you intend to: `docker compose down -v`.

## 10. Upgrade

```bash
git fetch && git checkout <new-approved-ref>
docker compose build
docker compose up -d
docker compose run --rm migrate
./scripts/validate-deployment.sh
```
