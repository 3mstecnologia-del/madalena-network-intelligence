# Agent notes — madalena-network-intelligence

## What this repo is

Multi-tenant network inventory / correlation platform for Madalena/Hermes.

## What this repo is not

- Not a replacement for `hermes-3ms-skills` operational skills
- Not a place to store customer credentials or real lab dumps

## Layers

| Layer | Role |
|-------|------|
| Skill (`hermes-3ms-skills`) | Teaches Hermes how to operate equipment |
| Collector (this repo) | Periodically collects and normalizes data |
| MCP (`mcp_server`) | Lets Hermes query the structured inventory |

## Hard rules

- Docker-only runtime for app dependencies
- No live collection against real customer gear in CI or this public repo
- Tenant required on every query path
- MikroTik collectors are read-only (print/get allowlist)
- Preserve observation history; never collapse to current-state-only
- Secret scan before any public GitHub publish
- Do not modify `hermes-3ms-skills` unless explicitly asked

## Future GitHub

Intended remote: `3mstecnologia-del/madalena-network-intelligence` — create/push only when maintainers authorize after finalize + secret scan.
