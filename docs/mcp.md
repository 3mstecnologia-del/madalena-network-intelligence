# MCP

Runnable package: `mcp_server` (avoids clashing with PyPI name `mcp`). Tools must call the same application/query layer as the API (`QueryService`), not a parallel correlation copy.

Runnable package: `mcp_server` (avoids clashing with PyPI name `mcp`).

Protocol: HTTP JSON tools for Hermes/lab. Full MCP stdio/SSE can wrap the same handlers later.

All tools require `tenant`. Responses include a short `text` (for an agent) plus structured `data`.

| Tool | Purpose |
|------|---------|
| `find_mac` | Current correlated view of a MAC |
| `find_ip` | MACs observed on an IP (ambiguity listed in `conflicts`) |
| `get_device` | Device inventory row (no secret refs) |
| `list_devices` | Tenant devices |
| `list_tenant_network_assets` | Device count + recent MACs |
| `get_mac_history` | Timeline + provenance (`source`, device, interface, IP, collection_run_id) |
| `get_collection_status` | Recent runs, completeness, freshness_seconds |

`GET /tools` lists them. HTTP base in Compose: `http://127.0.0.1:8081`.
