# Security notes

See root `SECURITY.md`.

Infisical (or equivalent) syncs secrets into the runtime environment as `{PREFIX}_HOST`, `{PREFIX}_USERNAME`, `{PREFIX}_PASSWORD`, `{PREFIX}_SSH_PORT`. Collectors call `resolve_secrets(provider, prefix)` and never log values. See `docs/runtime-configuration.md`.

Public repo checklist: placeholders only, secret scan, no real dumps. API/MCP responses must not include `secret_prefix`, passwords, or management host refs.
