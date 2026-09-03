# Security Policy

## Public repository rules

This project is intended to be published publicly. Therefore:

- Never commit credentials, tokens, private keys, SNMP communities, or real customer IPs.
- Never commit running-configs, dumps, or real laboratory `.env` files.
- Device access must use external secret references (`secret_provider` + `secret_prefix`), e.g. Infisical.
- The table `device_credentials_reference` stores **references only**, never passwords.

## Reporting

Report suspected secret exposure privately to 3MS Tecnologia maintainers. Rotate any exposed secret immediately.

## Before publishing

1. `make secret-scan`
2. Review `git log -p` / `git grep` for lab hostnames and passwords
3. Confirm `.env` is gitignored and absent from history
4. Confirm fixtures contain only synthetic RFC1918-style examples

## Multi-tenant isolation

All API and MCP tools require an explicit `tenant` parameter. Cross-tenant reads must not be possible by MAC/IP alone.
