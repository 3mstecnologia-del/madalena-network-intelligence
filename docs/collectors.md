# Collectors

## Design

Transport ≠ parser. Phase 1 emphasizes parsers + fixtures; live transport returns `skipped` / `not_implemented` without secrets.

## MikroTik

Sources: DHCP leases, ARP, bridge host/FDB, (planned) interfaces/VLANs/identity/resource.

## Intelbras G08

Uses skill-documented commands only. See `collectors/intelbras_g08/TODO.md`.

Do not duplicate `olt-intelbras-g08-ops` skill content here.
