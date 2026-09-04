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

## 4b. SSH known_hosts (required for MikroTik)

Host-key verification stays **on**. The scheduler/API load `/run/ssh/known_hosts`.

On the VPS, keep a private file **outside Git** (OpenSSH `known_hosts` format) and point Compose at it:

```bash
# .env (private)
NI_SSH_KNOWN_HOSTS_FILE=/etc/madalena-ni/known_hosts
NI_SSH_KNOWN_HOSTS=/run/ssh/known_hosts
```

Do not set `NI_SSH_MISSING_HOST_KEY=accept-new`. If the mounted file is empty, SSH collection will fail until the trusted keys are present.

## 4c. UniFi TLS

Default: TLS verification **on**. Optional mounted CA/chain and `{PREFIX}_TLS_SERVER_NAME` apply only while verification stays on:

```bash
# .env (private)
NI_TRUST_DIR=/etc/madalena-ni/tls
NI_TLS_CA_FILE=/run/tls/unifi-ca.pem
# optional when BASE_URL is an IP and the certificate has DNS SANs:
# {PREFIX}_TLS_SERVER_NAME=unifi.example.invalid
```

Lab exception (UniFi collector / that device prefix only): this laboratory does not require a verifiable UniFi CA/SAN. Set explicitly:

```bash
# .env (private) — UniFi device prefix only; does not affect SSH or other collectors
{PREFIX}_VERIFY_TLS=false
```

That wins over CA and `TLS_SERVER_NAME`. The collector logs a sanitized warning and does not log the URL or API key. Do not set a global TLS-off flag. MikroTik SSH still requires `known_hosts`.

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

If API/MCP are published on alternate loopback ports (Compose override), either let the script read `docker compose port` or set:

```bash
VALIDATE_API_URL=http://127.0.0.1:<api-port> \
VALIDATE_MCP_URL=http://127.0.0.1:<mcp-port> \
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
```

If this upgrade includes SSH known_hosts / UniFi CA support, **before** recreate:

1. Write the trusted OpenSSH `known_hosts` to `/etc/madalena-ni/known_hosts` (or another private path).
2. Add to private `.env`: `NI_SSH_KNOWN_HOSTS_FILE=/etc/madalena-ni/known_hosts` and `NI_SSH_KNOWN_HOSTS=/run/ssh/known_hosts`.
3. If UniFi TLS uses a private CA: put `unifi-ca.pem` in `/etc/madalena-ni/tls/`, set `NI_TRUST_DIR=/etc/madalena-ni/tls` and `NI_TLS_CA_FILE=/run/tls/unifi-ca.pem`.
4. Remove any `NI_SSH_MISSING_HOST_KEY=accept-new`.
5. UniFi: `{PREFIX}_VERIFY_TLS=false` is the approved UniFi-only lab exception. Optional `NI_TLS_CA_FILE` / `{PREFIX}_TLS_SERVER_NAME` are unused while that exception is set.

Then:

```bash
docker compose build
docker compose up -d
docker compose run --rm migrate
./scripts/validate-deployment.sh
```
