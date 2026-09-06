# Infrastructure Graph UI (evidence-backed)

Madalena Intelligence exposes a navigable, Obsidian-like view of the persisted
infrastructure. It is **not** a hardcoded topology: every node and edge is
assembled at query time from persisted observations, so newly discovered
equipment appears without touching the client.

## Access

- UI: `GET /ui/` (static SPA served by the API).
- Data: `GET /topology/graph?tenant=<slug>`.

## What the graph contains

Nodes come only from infrastructure assets:

| node_type | Meaning |
|-----------|---------|
| `site`    | A site (grouping). |
| `device`  | A managed device (router, OLT, switch, controller, server…). |
| `pon`     | A PON group derived from persisted `olt_onus.pon` under an OLT device. |
| `onu`     | An ONU under a PON (`olt_onus.ont_id`). |

Endpoint/client machines (DHCP/ARP/FDB viewers, phones, notebooks, user MACs)
are deliberately excluded by `GraphService` — they remain in the correlation
tables for enrichment but never become graph nodes.

## Relation vocabulary

Each edge carries `kind`, `status`, `evidence`, `first_seen`, `last_seen`:

| kind | Source of evidence |
|------|--------------------|
| `pertence_a` | `devices.site_id` |
| `contiene` | `olt_onus.pon` / `olt_onus.ont_id` (OLT → PON → ONU) |
| `conectado_a` | correlated `TopologyObservation`/neighbors (only when the remote resolves) |
| `uplink_de` | inventory/uplink observations |
| `alcanzable_via` | routed reachability (reserved, evidence-gated) |
| `anuncia_rede` | advertised network (reserved) |
| `observado_em` | observed-at-site (reserved) |

Kinds without persisted evidence simply emit no edges. Relations are **never
invented** to make the map look complete.

## Frontend

`app/ui/` is a static SPA (HTML/CSS/JS) with the **vendored** Cytoscape.js file
(`app/ui/vendor/cytoscape.min.js`). Features: pan/zoom/fit, node/edge tap
(inspector + side panel), filter chips by asset type and relation kind, a
search box, a legend, and double-tap collapse/expand of nodes that have
children.

Chips, legend, and colors are generated from the API response, so a new
`asset_type` renders without editing the JS. Dependency on the API schema is
deliberate and explicit (see ADR-0005).

## Keeping the vendor file fresh

Pin to a specific version when fetching:

```bash
curl -L -o app/ui/vendor/cytoscape.min.js \
  https://unpkg.com/cytoscape@3.30.0/dist/cytoscape.min.js
```

After touching `app/ui/`, **rebuild the API image** (static files are baked
into the image, not bind-mounted in this compose):

```bash
docker compose build api && docker compose up -d api
```

## Tests

`tests/test_graph.py` covers the service (hierarchy, tenant isolation, no
fabricated edges, endpoint machines excluded) and the HTTP endpoint + `/ui/`
mount.