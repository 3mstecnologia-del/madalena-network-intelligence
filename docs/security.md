# Security notes

See root `SECURITY.md`.

Infisical (or equivalent) syncs secrets into the runtime environment as `{PREFIX}_HOST`, `{PREFIX}_USERNAME`, `{PREFIX}_PASSWORD`, `{PREFIX}_SSH_PORT`. Collectors call `resolve_secrets(provider, prefix)` and never log values.

Public repo checklist: placeholders only, secret scan, no real dumps.
