# Runtime configuration

Secrets never live in Git, Alembic, or `device_credentials_reference`.

The database stores only:

- `secret_provider` (e.g. `infisical` or `env`)
- `secret_prefix` (logical name such as `DEVICE_EXAMPLE_MIKROTIK`)

At process start, an external system (Infisical sync, Compose `env_file`, orchestrator) must inject:

```
{PREFIX}_HOST
{PREFIX}_USERNAME
{PREFIX}_PASSWORD
{PREFIX}_SSH_PORT   # optional, default 22
```

`collectors.common.secrets.resolve_secrets(provider, prefix)` reads those keys. Missing keys → collection `skipped`, not a crash.

Local Docker: copy `.env.example` to `.env` and keep real values gitignored.

Madalena VPS: [`operations/madalena-deployment.md`](operations/madalena-deployment.md).

## Device collectors

`devices.collectors_enabled` is a JSON array of collector keys (runtime, not Git):

- MikroTik: `identity`, `dhcp`, `arp`, `fdb`, `interfaces`, `neighbors`
- G08: `ont_mac_table`
- UniFi Network: `inventory`, `device_details`

UniFi runtime keys (in addition to the SSH set when used): `{PREFIX}_BASE_URL`, `{PREFIX}_API_KEY`, optional `{PREFIX}_SITE`, optional `{PREFIX}_TLS_CA` (PEM), optional `{PREFIX}_TLS_SERVER_NAME` (DNS SAN when verification is on and the URL host is an IP). Global `NI_TLS_CA_FILE` is the Compose-mounted CA path. Default `{PREFIX}_VERIFY_TLS=true`. Setting `{PREFIX}_VERIFY_TLS=false` is a UniFi-collector-only lab exception; it does not disable TLS for SSH or other collectors, and it does not require CA or `TLS_SERVER_NAME`.

SSH: `NI_SSH_KNOWN_HOSTS` (container path, default `/run/ssh/known_hosts`) plus Compose bind `NI_SSH_KNOWN_HOSTS_FILE` on the host. Unknown host keys are rejected.

A router with no DHCP server omits `dhcp`. The product does not assume which fleet member serves leases.

Optional `devices.collection_interval_sec` skips a device if its last finished run is newer than that interval.

## Exclusion (before persist)

Table `exclusion_policies`: `rule_type` = `vlan` | `cidr` | `source` | `collector` | `interface`, plus optional site/device scope.

Seed may insert a VLAN rule from private env `SEED_EXCLUDE_VLAN` (empty by default).

Do not put customer hostnames, tunnels, or inventory lists in this repository.
