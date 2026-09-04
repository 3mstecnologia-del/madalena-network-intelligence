# ADR 0001 — Observation history

## Status

accepted

## Context

Network evidence changes: a MAC moves IP, interface, or router. Operators (and Madalena) need “where is it now?” and “where was it, according to which collector and run?”.

A current-state-only table that updates in place would destroy that trail. Treating “not seen in the latest run” as delete would also invent disappearances.

## Decision

Persist **temporal observations**. Matching keys update `last_seen`. A changed key inserts a new row. Rows are not deleted because a later collection omitted them.

Current view is derived at query time. Disappearance, if ever inferred, requires an explicit tested policy.

## Consequences

- Schema and ingest are slightly heavier than a single “current MAC” table
- Correlation must distinguish current vs historical vs conflicts
- Collectors and APIs must not collapse history to satisfy a simpler UI
