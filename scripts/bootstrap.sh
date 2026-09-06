#!/bin/sh
# Idempotent lab/VPS bootstrap. No secrets in this script.
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example — set POSTGRES_PASSWORD and device {PREFIX}_HOST/_USERNAME/_PASSWORD before collecting."
fi

docker compose config >/dev/null
docker compose build
docker compose up -d
docker compose run --rm migrate

if [ "${SEED:-false}" = "true" ]; then
  docker compose run --rm api python -m scripts.seed_lab
fi

echo "Bootstrap finished. Validate with: ./scripts/validate-deployment.sh"
