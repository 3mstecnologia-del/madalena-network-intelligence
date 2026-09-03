# Contributing

## Principles

- 100% Docker: do not require Python/Node/Postgres on the host.
- No real secrets in code, fixtures, docs, or commits.
- Multi-tenant from day one — every observation belongs to a tenant.
- Collectors parse and normalize; skills in `hermes-3ms-skills` teach Hermes how to operate gear.

## Workflow

```bash
cp .env.example .env
make build
make up
make migrate
make test
make secret-scan
```

## Adding a collector

Full workflow (spec → allowlist → synthetic fixtures → tests → ingest → API/MCP → optional lab): [`docs/development/adding-a-collector.md`](docs/development/adding-a-collector.md).

Definition of done and test matrix: [`docs/testing/strategy.md`](docs/testing/strategy.md).

## Adding a tenant

Use the API/DB seed pattern: Tenant → Site → Device → DeviceCredentialReference (secret prefix only). Do not hardcode customer topology.

Project Rules: `.cursor/rules/`. Docs index: `docs/README.md`.
