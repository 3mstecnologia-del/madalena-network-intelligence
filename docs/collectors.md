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

Live: `MikroTikCollector.collect_live` → `SshTransport` wrapped in `ReadOnlyTransport`. Without `{PREFIX}_HOST` / `_USERNAME` / `_PASSWORD` the run is `skipped`.

Tests must use `MemoryTransport` or `collect_from_texts`.

## Intelbras G08

Parser scaffold for ONT brief + MAC table using skill-documented read commands. Live transport remains `not_implemented` / `skipped`. Do not invent a CLI dialect here. See `collectors/intelbras_g08/TODO.md`.

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
