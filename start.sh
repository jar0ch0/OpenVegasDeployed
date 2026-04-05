#!/usr/bin/env bash
set -euo pipefail

echo "========================================="
echo "  OpenVegas — Production Start"
echo "========================================="

# Railway/Render inject $PORT; fall back to 8000 for local runs.
PORT="${PORT:-8000}"

# ── Run release-phase migrations ────────────
# Uses DATABASE_DIRECT_URL for DDL operations (bypasses PgBouncer).
# Falls back to DATABASE_URL if DIRECT is not set, with a warning.
echo "[startup] Running migrations..."
bash scripts/migrate.sh

# ── Launch the FastAPI server ───────────────
echo "[startup] Starting uvicorn on 0.0.0.0:${PORT}"
exec uvicorn server.main:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --proxy-headers \
    --forwarded-allow-ips='*' \
    --timeout-keep-alive 65 \
    --log-level info
