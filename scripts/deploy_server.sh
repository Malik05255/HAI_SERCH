#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ROLLBACK_SHA="${1:-}"

if [[ ! -f .env ]]; then
  echo ".env is missing" >&2
  exit 1
fi

python3 scripts/validate_production_env.py .env

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)
"${COMPOSE[@]}" config >/dev/null

rollback() {
  local reason="$1"
  echo "Deployment failed: $reason" >&2
  if [[ "$ROLLBACK_SHA" =~ ^[0-9a-f]{40}$ ]] && git cat-file -e "$ROLLBACK_SHA^{commit}" 2>/dev/null; then
    echo "Rolling back to $ROLLBACK_SHA" >&2
    git reset --hard "$ROLLBACK_SHA"
    "${COMPOSE[@]}" build api worker
    "${COMPOSE[@]}" up -d --remove-orphans
  fi
  exit 1
}

"${COMPOSE[@]}" pull postgres searxng planner vision caddy
"${COMPOSE[@]}" build --pull api worker
"${COMPOSE[@]}" up -d --remove-orphans

for _ in $(seq 1 40); do
  if curl -fsS --max-time 5 http://127.0.0.1:8000/health >/dev/null; then
    break
  fi
  sleep 3
done
curl -fsS --max-time 5 http://127.0.0.1:8000/health >/dev/null || rollback "local API health check failed"

PUBLIC_BASE_URL="$(grep -E '^PUBLIC_BASE_URL=' .env | tail -1 | cut -d= -f2-)"
for _ in $(seq 1 60); do
  if curl -fsS --max-time 10 "$PUBLIC_BASE_URL/health" >/dev/null; then
    echo "Production deployment healthy: $PUBLIC_BASE_URL"
    exit 0
  fi
  sleep 5
done

rollback "public HTTPS health check failed"
