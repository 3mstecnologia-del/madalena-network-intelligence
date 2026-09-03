# MCP package location

The runnable MCP tool server lives in `mcp_server/` to avoid shadowing the
PyPI package name `mcp`.

Start via Docker Compose service `mcp`:

```bash
docker compose up -d mcp
curl -s http://127.0.0.1:8081/health
curl -s http://127.0.0.1:8081/tools
```

Phase 1: HTTP JSON tools. Full MCP stdio/SSE protocol is a follow-up.
