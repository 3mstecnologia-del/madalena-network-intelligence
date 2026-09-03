# ADR 0002 — Tenant isolation

## Status

accepted

## Context

This product is multi-tenant. MAC and IP addresses are not globally unique identities across customers. A query that omits tenant would leak or mix inventories.

## Decision

Tenant is a **security boundary**. Every observation carries `tenant_id`. API and MCP require an explicit tenant. Device, MAC, IP, history, correlation, and collection-run queries are scoped to that tenant.

The same MAC in two tenants is two records. Cross-tenant access by identifier alone is a defect.

New endpoints that return observations need isolation tests.

## Consequences

- No “global MAC search” without tenant
- Seed and fixtures use more than one tenant when testing isolation
- Performance indexes start from `tenant_id` plus the lookup key
