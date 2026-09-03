# Collectors

## Design

Transport ≠ parser. Parsers consume text fixtures or transport stdout. Live SSH is optional and uses runtime secrets only.

Read-only: MikroTik collection never issues `add` / `set` / `remove` / `enable` / `disable` / `move`.

## Collector lifecycle

1. Scheduler selects enabled devices of a type.
2. `IngestService.start_run` records tenant/site/device/version.
3. Collector runs allowlisted read commands (light or full).
4. Successful command outputs are parsed and ingested. Failed commands increment `commands_failed` and mark completeness `partial` or `none`.
5. `finish_run` stores counts, sanitized errors, completeness. Commit. Prior observations remain.

## MikroTik (RouterOS 7)

Sources: identity, resource, interfaces, ARP, DHCP leases, bridge/FDB, IP neighbors.

| Mode | Commands |
|------|----------|
| light | identity, ARP, DHCP, FDB |
| full | light + resource, interfaces, neighbors |

Live: `MikroTikCollector.collect_live` uses **only** the configured protocol (`{PREFIX}_PROTOCOL`) on `{PREFIX}_PORT` / `{PREFIX}_SSH_PORT`. SSH does not fall back to Telnet or API. Without `{PREFIX}_HOST` / `_USERNAME` / `_PASSWORD` the run is `skipped`.

Tests must use `MemoryTransport` or `collect_from_texts`.

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
