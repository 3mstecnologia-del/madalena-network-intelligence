#!/bin/sh
# Prove the stack is serving, not merely that containers exist.
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "VALIDATE FAILED: $1" >&2
  exit 1
}

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

wait_http http://127.0.0.1:8000/health "API /health"
wait_http http://127.0.0.1:8000/ready "API /ready (database)"
wait_http http://127.0.0.1:8081/health "MCP /health"
wait_http http://127.0.0.1:8081/ready "MCP /ready (database)"
curl -sf http://127.0.0.1:8081/tools >/dev/null || fail "MCP /tools"

docker compose exec -T db pg_isready >/dev/null || fail "PostgreSQL not ready"
docker compose exec -T scheduler python -c "from scheduler.main import heartbeat_fresh; import sys; sys.exit(0 if heartbeat_fresh() else 1)" \
  || fail "scheduler heartbeat stale"

echo "VALIDATE OK — API, MCP, PostgreSQL, and scheduler are serving"
