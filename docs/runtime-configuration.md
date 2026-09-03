# Runtime configuration

Secrets never live in Git, Alembic, or `device_credentials_reference`.

The database stores only:

- `secret_provider` (e.g. `infisical` or `env`)
- `secret_prefix` (logical name such as `DEVICE_EXAMPLE_MIKROTIK`)

At process start, an external system (Infisical sync, Compose `env_file`, orchestrator) must inject:

```
{PREFIX}_HOST
{PREFIX}_USERNAME
{PREFIX}_PASSWORD
{PREFIX}_SSH_PORT   # optional, default 22
```

`collectors.common.secrets.resolve_secrets(provider, prefix)` reads those keys. Missing keys → collection `skipped`, not a crash.

Local Docker: copy `.env.example` to `.env` and keep real values gitignored. Use RFC1918 lab addresses only in your private `.env`.

Do not put customer hostnames, tunnels, or inventory lists in this repository.
