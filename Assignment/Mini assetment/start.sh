#!/usr/bin/env bash
set -euo pipefail

BACKEND_PORT="${BACKEND_PORT:-8001}"
APP_PORT="${PORT:-8501}"
export BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:${BACKEND_PORT}}"

cleanup() {
  trap - EXIT INT TERM
  kill 0 2>/dev/null || true
}
trap cleanup EXIT INT TERM

uvicorn app.main:app --host 127.0.0.1 --port "${BACKEND_PORT}" --workers 1 &

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

streamlit run frontend/app.py \
  --server.address 0.0.0.0 \
  --server.port "${APP_PORT}" \
  --server.headless true \
  --browser.gatherUsageStats false &

wait -n
