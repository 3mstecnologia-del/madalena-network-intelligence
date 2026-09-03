# MCP

Runnable package: `mcp_server` (avoids clashing with PyPI name `mcp`). Tools must call the same application/query layer as the API (`QueryService`), not a parallel correlation copy.

Runnable package: `mcp_server` (avoids clashing with PyPI name `mcp`).

Phase 1 protocol: HTTP JSON tools for Hermes/lab. Full MCP stdio/SSE can wrap the same handlers later.

All tools require `tenant`.
