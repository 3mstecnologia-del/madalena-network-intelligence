# ADR 0004 — Read-only allowlisted transport

## Status

accepted

## Context

Collectors talk to routers and OLTs. An open-ended “run this command from the API/MCP/database” path would turn the product into a remote shell and would risk write operations.

Vendor CLIs also invite fragile fallbacks (“command A failed, try command B”) that can hit incomplete or destructive forms.

## Decision

- Transport only moves bytes. Collectors orchestrate a **positive allowlist** of read operations.
- Arbitrary commands from API, MCP, requests, tenant config, or the database are rejected.
- Protocol (SSH/Telnet/API) and ports are **configured** and tested, not guessed at runtime.
- Device family/version selects known commands (example: G08 MAC table via `show ont mac-address-table interface gpon all`), not opportunistic probing.

Parser failure must not issue a mutating fallback.

## Consequences

- New reads require an allowlist change, tests, and collector docs
- Live lab remains optional and private; public tests use fake transports
- Slightly slower evolution of supported commands in exchange for safety
