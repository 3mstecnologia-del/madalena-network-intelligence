# Architectural decisions

Light ADRs for durable choices. Skip this folder for trivial implementation details.

Format: **Context**, **Decision**, **Consequences**, **Status** (`proposed` / `accepted` / `superseded`).

| ID | Title | Status |
|----|--------|--------|
| [0001](0001-observation-history.md) | Observations are history, not overwrite-only inventory | accepted |
| [0002](0002-tenant-isolation.md) | Tenant is the security boundary on every query path | accepted |
| [0003](0003-pre-persistence-exclusion.md) | Drop out-of-scope evidence before persisting endpoints | accepted |
| [0004](0004-readonly-allowlist-transport.md) | Collectors use configured read-only transports and allowlists | accepted |
