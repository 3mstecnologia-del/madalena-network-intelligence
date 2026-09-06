# Runtime configuration

Secrets never live in Git, Alembic, or `device_credentials_reference`.

The database stores only:

- `secret_provider` (e.g. `infisical` or `env`)
- `secret_prefix` (logical name such as `DEVICE_EXAMPLE_MIKROTIK`)

At process start, `resolve_secrets(provider, prefix)` resolves device credentials:

- **`env`** — reads injected runtime variables:
  ```
  {PREFIX}_HOST        # (alias {PREFIX}_IP for OLT-style references)
  {PREFIX}_USERNAME
  {PREFIX}_PASSWORD
  {PREFIX}_SSH_PORT    # optional, default 22 (alias {PREFIX}_PORT)
  {PREFIX}_PROTOCOL    # ssh | telnet | https
  ```
- **`infisical`** (default when `SECRET_PROVIDER=infisical`) — fetches the same
  `{PREFIX}_*` keys directly from the Cofre Central at runtime, so device
  credentials only live in Infisical. The scheduler mounts an Infisical machine
  identity via `INFISICAL_URL`, `INFISICAL_CLIENT_ID`,
  `INFISICAL_CLIENT_SECRET`, `INFISICAL_PROJECT_ID`, `INFISICAL_ENV`
  (default `production`). Device secrets may live under any folder; the client
  enumerates folders recursively. Environment variables still override Cofre
  values when both are set.

Missing keys → collection `skipped: secrets_unavailable`, never a crash.

Register real devices (tenant/site/name/type/secret_prefix only, never values)
with the operator tool:
```
docker compose run --rm api python -m scripts.register_devices \
    --tenant uniplac --site uniplac-main --name OLT-G08 \
    --type intelbras_g08 --prefix OLT_UNIPLAC
# or batch: python -m scripts.register_devices --spec /path/devices.json
```
The JSON spec and any credential values are gitignored and must never commit.

Local Docker: copy `.env.example` to `.env` and keep real values gitignored.

Madalena VPS: [`operations/madalena-deployment.md`](operations/madalena-deployment.md).

## Device collectors

`devices.collectors_enabled` is a JSON array of collector keys (runtime, not Git):

- MikroTik: `identity`, `dhcp`, `arp`, `fdb`, `interfaces`, `neighbors`
- G08: `ont_mac_table`, `ont_brief`
- UniFi Network: `inventory`, `device_details`

UniFi runtime keys (in addition to the SSH set when used): `{PREFIX}_BASE_URL`, `{PREFIX}_API_KEY`, optional `{PREFIX}_SITE`, optional `{PREFIX}_TLS_CA` (PEM), optional `{PREFIX}_TLS_SERVER_NAME` (DNS SAN when verification is on and the URL host is an IP). Global `NI_TLS_CA_FILE` is the Compose-mounted CA path. Default `{PREFIX}_VERIFY_TLS=true`. Setting `{PREFIX}_VERIFY_TLS=false` is a UniFi-collector-only lab exception; it does not disable TLS for SSH or other collectors, and it does not require CA or `TLS_SERVER_NAME`.

SSH: `NI_SSH_KNOWN_HOSTS` (container path, default `/run/ssh/known_hosts`) plus Compose bind `NI_SSH_KNOWN_HOSTS_FILE` on the host. Unknown host keys are rejected.

A router with no DHCP server omits `dhcp`. The product does not assume which fleet member serves leases.

Optional `devices.collection_interval_sec` skips a device if its last finished run is newer than that interval.

## Exclusion (before persist)

Table `exclusion_policies`: `rule_type` = `vlan` | `cidr` | `source` | `collector` | `interface`, plus optional site/device scope.

Seed may insert a VLAN rule from private env `SEED_EXCLUDE_VLAN` (empty by default).

Do not put customer hostnames, tunnels, or inventory lists in this repository.
