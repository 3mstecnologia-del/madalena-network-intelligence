# ADR 0005 — Evidence-backed infrastructure graph (no hardcoded topology)

## Status

accepted

## Context

Madalena Intelligence persists observations and correlates topology, but the
product had no unified, navigable view of the infrastructure. The goal is a
product interface inspired by an Obsidian Graph View: a navigable graph of
real, discovered assets (core, routers, switches, APs, OLTs, PONs, ONUs,
servers) with typed relations carrying their provenance/evidence and time
windows.

Two constraints shape the design:

1. **No hardcoded topology in the frontend.** The graph must be produced from
   persisted knowledge/evidence so newly discovered equipment appears without
   changing the client. Hardcoding relations would freeze the view and hide
   correlation gaps.
2. **No fabricated relations.** Only relations supported by real evidence may
   be drawn. When a relation cannot be determined safely it is `unknown` or the
   edge is simply not created — never invented to make the map look "nice".

Endpoint/client machines (phones, notebooks, user MACs) are intentionally kept
out of the initial infrastructure graph; they remain in correlation tables for
internal enrichment.

## Decision

- New service `app/services/graph.py` (`GraphService`) assembles the graph at
  query-time from persisted observations. It is **not** a separate stored
  graph: nodes and edges are derived from `devices`, `sites`, `olt_onus`
  (PON/ONU hierarchy), and the correlated topology service.
- New endpoint `GET /topology/graph?tenant=<slug>` returns
  `{tenant, asset_types, relation_kinds, nodes, edges}`. Nodes expose a generic
  `asset_type` (mapped from `device_type` with an unknown-type fall-through);
  edges carry `kind`, `status`, `evidence`, `first_seen`, `last_seen`.
- Relation vocabulary is open and future-proof: `pertence_a`, `contiene`,
  `conectado_a`, `uplink_de`, `alcanzable_via`, `anuncia_rede`,
  `observado_em`. Kinds without persisted evidence simply emit no edges; the
  schema already admits them so collectors/frontend stay decoupled.
- Frontend `app/ui/` is a static SPA served by FastAPI under `/ui/`, using the
  vendored **Cytoscape.js** (MIT, self-contained, no build step). It renders
  whatever the API returns: filter chips, legend and colors are generated from
  the payload — new asset types appear without JS changes.
- Endpoint machines (DHCP/ARP/FDB) are excluded from `GraphService` by
  construction; only infra assets become nodes.

## Consequences

- The view is always current: as collectors persist new devices/ONUs/links they
  appear in the graph on reload — no manual edits.
- Client is decoupled from vendor-specific types via the stable `asset_type`
  vocabulary and open `relation_kind` set.
- Query-time assembly means large graphs must be paginated/visualized
  carefully (nice-to-have: client-side collapse by node for big PONs).
- Static vendor file must be kept in sync with the pinned version; a future
  build pipeline could pin it via lockfile.