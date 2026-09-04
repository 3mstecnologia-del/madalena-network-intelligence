# Collectors

Workflow to add a family: [development/adding-a-collector.md](development/adding-a-collector.md). This file is the spec of collectors that already exist.

## Design

Transport ≠ parser. Parsers consume text fixtures or transport stdout. Live SSH is optional and uses runtime secrets only.

Read-only: MikroTik collection never issues `add` / `set` / `remove` / `enable` / `disable` / `move`.

## Collector lifecycle

1. Scheduler selects enabled devices of a type.
2. `IngestService.start_run` records tenant/site/device/version.
3. Collector runs exact allowlisted read commands (light or full). Suffixes, chaining, and extra modifiers are rejected.
4. Successful command outputs are parsed and ingested. Failed commands increment `commands_failed` and mark completeness `partial` or `none`.
5. `finish_run` stores counts, sanitized errors, completeness. Commit. Prior observations remain.

## MikroTik (RouterOS 7)

Sources: identity, resource, interfaces, ARP, DHCP leases, bridge/FDB, IP neighbors.

| Mode | Commands |
|------|----------|
| light | identity, ARP, DHCP, FDB, neighbors |
| full | light + resource, interfaces |

Live: `MikroTikCollector.collect_live` uses **only** the configured protocol (`{PREFIX}_PROTOCOL`) on `{PREFIX}_PORT` / `{PREFIX}_SSH_PORT`. SSH does not fall back to Telnet or API. Without `{PREFIX}_HOST` / `_USERNAME` / `_PASSWORD` the run is `skipped`. Per-device `collectors_enabled` selects which command groups run (a fleet member may omit `dhcp`).

SSH host-key checking is reject-unknown. Deploy mounts a trusted `known_hosts` at `/run/ssh/known_hosts` (`NI_SSH_KNOWN_HOSTS`). Do not use `NI_SSH_MISSING_HOST_KEY=accept-new` as the supported configuration.

Neighbor fields are optional. Missing identity, remote interface, protocol, or version is not an error. Neighbors also produce `topology_links` (observations, not correlated truth).

Tests must use `MemoryTransport` or `collect_from_texts`.

## UniFi Network (Integration API)

Read-only HTTP GET against the documented Integration API (`X-API-Key`). Runtime:

- `{PREFIX}_BASE_URL` — Integration root (no hostname hardcoded)
- `{PREFIX}_API_KEY`
- `{PREFIX}_SITE` — optional site UUID; if omitted, `GET /v1/sites` then devices per site
- `{PREFIX}_TLS_CA` or global `NI_TLS_CA_FILE` — PEM CA/chain so TLS verification stays on
- `{PREFIX}_TLS_SERVER_NAME` — DNS SAN used for TLS hostname verification when `BASE_URL` uses an IP
- `{PREFIX}_VERIFY_TLS` — default true; do not use `false` as the deploy path

Allowlisted GET paths only: `/v1/info`, `/v1/sites`, `/v1/sites/{siteId}/devices`, `/v1/sites/{siteId}/devices/{deviceId}`. No adopt, actions, port control, or unadopt.

Inventory fields follow the documented schema (`id`, `mac`/`macAddress`, `name`, `model`, `state`, `type`, optional `ipAddress`, `firmwareVersion`). Uplink in the documented schema is `{ "deviceId": "<uuid>" }` and is stored when present. Ports (`interfaces.ports[].idx`) become local interfaces `port-{idx}` when the detail payload includes them.

Live HTTP is not exercised in CI. Tests use `MemoryUnifiClient` and synthetic JSON fixtures.

## Intelbras G08

Live collection uses an interactive CLI transport (SSH or Telnet from runtime secrets) behind a show-only allowlist. The G08 driver command is `show ont mac-address-table interface gpon all`. See `collectors/intelbras_g08/TODO.md`.

Do not duplicate `olt-intelbras-g08-ops` skill content here.

## Adding a collector

1. Add parsers under `collectors/<vendor>/parsers.py` (text in, normalized dataclasses out).
2. Implement `collect_from_texts` and optionally `collect_via_transport` using `collectors.common.transport.Transport`.
3. Wrap live transports with a read-only allowlist.
4. Extend `CollectorResult` only if a new observation kind is required; otherwise map into existing types.
5. Teach `IngestService` to upsert without deleting history.
6. Register the device_type in the scheduler.
7. Add synthetic fixtures + tests. No customer dumps.

## Runtime configuration (no secrets in Git)

See [runtime-configuration.md](runtime-configuration.md).
