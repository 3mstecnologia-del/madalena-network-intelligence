# Adding a collector

Product workflow for a new device family or observation source. Command lists for collectors that already exist: [collectors.md](../collectors.md).

Do not invent vendor CLI. Document commands only after they are specified (skill, vendor doc, or lab-validated driver). Skills in `hermes-3ms-skills` stay the operational manuals; this repo stores **normalized observations**.

## Workflow

```
SPEC
  → transport / driver contract
  → parser + synthetic fixtures
  → unit tests
  → persistence / correlation
  → API / MCP when the new evidence is queryable
  → integration tests
  → optional real lab (private)
  → review
```

### 1. SPEC

Write down, before code:

- Device family / version assumptions
- Transport (SSH, Telnet, API, …) and that it is read-only
- Exact allowlisted commands (positive list)
- Fields produced and their semantics (do not mix ONT-ID with serial, GEM, PON)
- Completeness and failure rules
- Limitations

Keep customer names, VLANs, and IPs out of the spec in Git. Use placeholders.

### 2. Transport / driver contract

- `Transport.execute(command)` returns raw text + status. No business rules.
- Wrap with a read-only allowlist. Refuse mutation tokens and anything not listed.
- Protocol and port come from **runtime** secrets/config, not from “try the next protocol”.
- For Intelbras G08 MAC tables the driver command is:

  `show ont mac-address-table interface gpon all`

  Do not probe incomplete commands hoping one of them works.

### 3. Parser fixtures

Under `tests/fixtures/`, synthetic identifiers only. Preserve layout/syntax the parser must handle (headers, paging junk, columns). Cover at least: happy path, partial/malformed lines, empty.

Never commit a sanitized dump of a real customer network.

### 4. Unit tests

Parser in / dataclasses out. Completeness: command OK + dropped lines → **not** complete. Sanitization tests if the collector logs or stores errors.

### 5. Persistence and correlation

Ingest through the existing observation types when possible. New tables need a **new** Alembic migration, `tenant_id`, timestamps, source, `collection_run_id` when applicable.

History: upsert on the observation key; do not delete rows missing from a later run.

If the source can disagree with DHCP/ARP/FDB/OLT, correlation must expose `conflicts` rather than picking a winner.

### 6. API / MCP

Only if callers need the new evidence. Use `QueryService` / `CorrelationEngine`. Tenant parameter required. Pagination on lists. OpenAPI + `docs/mcp.md` if tools change.

### 7. Integration tests

Tenant isolation, repeated ingest, and the HTTP path if you added API/MCP fields.

### 8. Optional lab

Private dotenv **outside** the repo (`LAB_SECRETS_FILE`). Do not paste lab output into fixtures. Record “lab validated” in the PR text, not as a Git golden file of real MACs.

### 9. Review

Allowlist, completeness honesty, no secrets, docs: collector spec + this workflow if the process changed.

## Directory layout

```
collectors/<vendor>/
  parsers.py      # pure
  collector.py    # orchestration
  readonly.py     # allowlist
  transport_*.py  # optional; protocol only
```

Register `device_type` in the scheduler. Tests must not require live gear.

## Bugs in an existing collector

reproduce → regression fixture/test → minimal fix → integration test if ingest/API broke → update collector docs if the contract (fields, completeness, commands) changed.
