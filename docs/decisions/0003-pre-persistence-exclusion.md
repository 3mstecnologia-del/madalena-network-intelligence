# ADR 0003 — Pre-persistence exclusion

## Status

accepted

## Context

Tenants may have networks that must not be stored (example class: a VLAN used by a population that the contract excludes). Collecting everything “because the CLI returned it” fights privacy and data minimization.

Hardcoding VLAN IDs, customer names, or subnets in a public repository would leak operational knowledge and would not transfer across tenants.

## Decision

Exclusion is **runtime / private tenant configuration**. Prefer dropping matching evidence **before** persisting endpoint observations.

Filters may later include VLAN, network, device/source, or observation class. Exclusion must be testable with synthetic data and auditable (policy applied, payload not stored).

Public code must not contain real customer VLANs, names, or management networks.

## Consequences

- `IngestService` applies `exclusion_policies` plus per-device `collectors_enabled` after parse and before insert
- Tests use synthetic VLAN/network IDs, never production identifiers
- “We deleted it later” is not an acceptable substitute for not persisting
