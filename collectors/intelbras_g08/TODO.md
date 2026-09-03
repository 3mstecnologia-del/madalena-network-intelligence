# Intelbras G08 collector — TODOs

Skill reference (do not duplicate): `hermes-3ms-skills/.../olt-intelbras-g08-ops/`

## Documented commands used as targets

- `show ont brief interface gpon all`
- `show ont mac-address-table interface gpon all`
- `show ont-find list interface gpon all`
- `show mac-address-table dynamic vlan <vlan>`

## Open items (no invention)

1. Validate exact column layout of MAC address table on live G08.
2. Confirm OLT identity / hostname command for inventory.
3. Implement SSH transport (paging, enable mode) behind secret_prefix.
4. VLAN association completeness when only dynamic MAC table is available.
5. Profile correlation from `show ont profile <ont_id>` when needed.

Phase 1: fixture parsers + structure only. No lab collection.
