# Agent notes — madalena-network-intelligence

Multi-tenant **observability and correlation**: evidence in (MikroTik fleet, OLT, …) → observations → PostgreSQL → queryable knowledge for Madalena. Discover by evidence; do not hardcode where an endpoint lives.

## Project Rules and docs

- Cursor: `.cursor/rules/` (purpose + architecture + tenant always apply; the rest is glob-scoped)
- Index: `docs/README.md`
- Architecture: `docs/architecture/overview.md`
- Tests: `docs/testing/strategy.md`
- New collector: `docs/development/adding-a-collector.md`

Do not copy the global 3MS User Rule into this file.

## Commands (Docker)

```bash
make build && make up && make migrate && make seed && make test && make secret-scan
```

## Do not

- Live-collect against customer or lab gear from CI / this public repo
- Issue write commands to MikroTik/OLT (collectors are read-only allowlists)
- Collapse observation history into current-state-only
- Query without `tenant`
- Commit secrets, real dumps, or client topology (VLAN names, “DHCP is router X”, real IPs)
- Modify `hermes-3ms-skills` unless explicitly asked
- Treat CODE PASS as LIVE PASS for collectors
