# Intelbras G08 collector — TODOs

Skill reference (do not duplicate): `hermes-3ms-skills/.../olt-intelbras-g08-ops/`

## Documented read commands

- `show ont mac-address` (lab-authorized primary)
- `show ont mac-address-table interface gpon all` (skill form, fallback only)
- `show ont brief interface gpon all`
- `show ont-find list interface gpon all`

## Live

Interactive CLI transport is read-only and allowlisted. Identity/paging CLI extras are not invented.

## Open items

1. Confirm optional identity command on live G08 without guessing.
2. VLAN completeness when the MAC table omits VLAN.
3. Profile correlation from `show ont profile` when authorized.
