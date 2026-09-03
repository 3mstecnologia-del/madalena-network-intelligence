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

1. Create `collectors/<vendor>/parsers.py` (pure, fixture-tested)
2. Create `collectors/<vendor>/collector.py` (transport separate from parsers)
3. Register device_type and scheduler job
4. Document commands only when validated; mark TODOs otherwise
5. Never invent vendor CLI

## Adding a tenant

Use the API/DB seed pattern: Tenant → Site → Device → DeviceCredentialReference (secret prefix only).
