# ──────────────────────────────────────────────
#  OpenVegas — Production Dockerfile
# ──────────────────────────────────────────────
#  Builds a single deployable image that runs the
#  FastAPI backend + serves the static /ui.
# ──────────────────────────────────────────────

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System libraries needed by psycopg2-binary, cryptography, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Install Python deps (layer-cached) ──────
# Copy only what pip needs first so source changes don't bust the cache.
COPY pyproject.toml README.md ./
COPY openvegas/ openvegas/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[server]"

# ── Copy the rest of the application ────────
COPY server/                server/
COPY ui/                    ui/
COPY supabase/migrations/   supabase/migrations/
COPY supabase/seed.sql      supabase/seed.sql
COPY scripts/               scripts/
COPY jobs/                  jobs/
COPY .env.example           .env.example

RUN chmod +x scripts/*.sh

# Railway injects $PORT at runtime; default to 8000 locally
ENV PORT=8000
EXPOSE ${PORT}

# Liveness check — hits the lightweight /health/live endpoint.
# Does NOT check Redis (it's optional) or DB (that's /health/ready).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health/live || exit 1

CMD ["bash", "scripts/start.sh"]
