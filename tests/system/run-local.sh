#!/usr/bin/env bash
set -euo pipefail

# This is intentionally opt-in. It creates and destroys only the named
# `polycolab-integration` volume declared in compose.yaml.
root_dir="$(cd "$(dirname "$0")/../.." && pwd)"
compose_file="$root_dir/tests/system/compose.yaml"
database_url="postgresql+psycopg://polycolab_integration:polycolab_integration@127.0.0.1:${POLYCOLAB_INTEGRATION_POSTGRES_PORT:-55432}/polycolab_integration"
api_url="${POLYCOLAB_INTEGRATION_API_URL:-http://127.0.0.1:18000}"
provider_url="${POLYCOLAB_INTEGRATION_PROVIDER_URL:-http://127.0.0.1:18080}"
web_url="${POLYCOLAB_INTEGRATION_WEB_URL:-http://127.0.0.1:13000}"
api_pid=""
provider_pid=""
worker_pid=""
web_pid=""

# Anonymous checks navigate directly to FastAPI, which serves the built bundle.
# Build before creating disposable services so those checks cannot use stale assets.
pnpm --dir "$root_dir" --filter @polycolab/web run build

cleanup() {
  for pid in "$web_pid" "$worker_pid" "$api_pid" "$provider_pid"; do
    if [[ -n "$pid" ]]; then kill "$pid" 2>/dev/null || true; fi
  done
  for pid in "$web_pid" "$worker_pid" "$api_pid" "$provider_pid"; do
    if [[ -n "$pid" ]]; then wait "$pid" 2>/dev/null || true; fi
  done
  docker compose -f "$compose_file" down -v --remove-orphans || true
}
trap cleanup EXIT INT TERM

docker compose -f "$compose_file" up -d --wait
DATABASE_URL="$database_url" uv --directory "$root_dir/src/backend" run alembic upgrade head

uv --directory "$root_dir/src/backend" run python "$root_dir/tests/system/fake_openai.py" --port 18080 & provider_pid=$!
PYTHONPATH="$root_dir/src/backend" uv --directory "$root_dir/src/backend" run python "$root_dir/tests/system/serve_api.py" --database-url "$database_url" --provider-url "$provider_url" --port 18000 --web-origin "$web_url" --registration-mode "${POLYCOLAB_INTEGRATION_REGISTRATION_MODE:-closed}" & api_pid=$!
APP_ENV=local RUNTIME_INTERNAL_API_URL="$api_url" RUNTIME_WORKER_ID=integration-worker uv --directory "$root_dir/src/backend" run python -m polycolab.builtin_worker & worker_pid=$!
(
  cd "$root_dir/src/web"
  export POLYCOLAB_API_PROXY_TARGET="$api_url" VITE_API_BASE_URL="$api_url"
  exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 13000 --strictPort
) & web_pid=$!

for _ in $(seq 1 60); do
  if curl --fail --silent "$api_url/health/live" >/dev/null && curl --fail --silent "$web_url/" >/dev/null; then break; fi
  sleep 1
done
curl --fail --silent "$api_url/health/live" >/dev/null
curl --fail --silent "$web_url/" >/dev/null
POLYCOLAB_INTEGRATION_API_URL="$api_url" POLYCOLAB_INTEGRATION_PROVIDER_URL="$provider_url" POLYCOLAB_INTEGRATION_WEB_URL="$web_url" pnpm --filter @polycolab/web exec playwright test --config "$root_dir/tests/system/playwright.config.ts" "$@"
