#!/bin/sh
# Prove the stack is serving, not merely that containers exist.
# Host-side script: curl the published loopback ports (not container DNS names).
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "VALIDATE FAILED: $1" >&2
  exit 1
}

published_to_loopback_url() {
  published="$1"
  port="${published##*:}"
  port="${port%]}"
  echo "http://127.0.0.1:${port}"
}

resolve_url() {
  override="$1"
  service="$2"
  container_port="$3"
  default_url="$4"
  if [ -n "$override" ]; then
    echo "$override" | sed 's:/*$::'
    return 0
  fi
  published="$(docker compose port "$service" "$container_port" 2>/dev/null || true)"
  if [ -n "$published" ]; then
    published_to_loopback_url "$published"
    return 0
  fi
  echo "$default_url"
}

API_URL="$(resolve_url "${VALIDATE_API_URL:-}" api 8000 "http://127.0.0.1:8000")"
MCP_URL="$(resolve_url "${VALIDATE_MCP_URL:-}" mcp 8081 "http://127.0.0.1:8081")"

if [ "${1:-}" = "--print-urls" ]; then
  echo "API_URL=$API_URL"
  echo "MCP_URL=$MCP_URL"
  exit 0
fi

wait_http() {
  url="$1"
  label="$2"
  i=0
  while [ "$i" -lt 30 ]; do
    if curl -sf "$url" >/dev/null; then
      return 0
    fi
    i=$((i + 1))
    sleep 2
  done
  fail "$label"
}

docker compose ps --status running >/dev/null 2>&1 || fail "compose not running"

wait_http "$API_URL/health" "API /health"
wait_http "$API_URL/ready" "API /ready (database)"
wait_http "$MCP_URL/health" "MCP /health"
wait_http "$MCP_URL/ready" "MCP /ready (database)"
curl -sf "$MCP_URL/tools" >/dev/null || fail "MCP /tools"

docker compose exec -T db sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  >/dev/null || fail "PostgreSQL not ready"
docker compose exec -T scheduler python -c "from scheduler.main import heartbeat_fresh; import sys; sys.exit(0 if heartbeat_fresh() else 1)" \
  || fail "scheduler heartbeat stale"

echo "VALIDATE OK — API, MCP, PostgreSQL, and scheduler are serving"
