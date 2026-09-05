# Intelbras G08 collector — TODOs

Skill reference (do not duplicate): `hermes-3ms-skills/.../olt-intelbras-g08-ops/`

## Driver contract (validated live)

Family `intelbras-g08` collects MAC observations with:

`show ont mac-address-table interface gpon all`

Live evidence (no private payload): the short form `show ont mac-address` returns `% Incomplete command`. The collector does not probe the incomplete form.

Parsed columns when present: MAC-Address, VID (VLAN observation), ONT-ID, SN (ONU serial, not ONT-ID), ID/GEM, PON derived from ONT-ID.

## Other documented read commands

- `show ont-find list interface gpon all`

## Open items

1. Confirm optional identity command on live G08 without guessing.
2. Profile correlation from `show ont profile` when authorized.
