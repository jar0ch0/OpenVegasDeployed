# OpenVegas

OpenVegas is a FastAPI backend plus browser UI for wagering `$V`, running games, and handling inference-credit flows. This repo also ships a PyInstaller-based CLI binary and an npm wrapper that downloads the correct binary from GitHub Releases.

## Architecture

- `server/` contains the FastAPI backend.
- `ui/` contains the static browser UI served by the backend under `/ui`.
- `openvegas/` contains the Python package and CLI.
- `npm-cli/` contains the npm bootstrap package that downloads prebuilt binaries.
- `supabase/migrations/` and `supabase/seed.sql` define the database schema bootstrap.

## Local Setup

```bash
cp .env.example .env
pip install -e ".[server,dev]"
uvicorn server.main:app --reload
```

Fill `.env` with real values before running. Commonly needed keys:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_JWT_SECRET`
- `DATABASE_URL`
- `DATABASE_DIRECT_URL` if you plan to run migrations locally
- `REDIS_URL` if you want Redis-backed features
- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_ORG_PRICE_ID`
- `OPENAI_API_KEY` and any other model-provider keys you use

Useful local URLs:

- API health: `http://127.0.0.1:8000/health`
- Readiness: `http://127.0.0.1:8000/health/ready`
- UI: `http://127.0.0.1:8000/ui`

## Local Production-Like Run

This repo includes a Docker setup that mirrors Railway closely:

```bash
cp env.production.example .env
docker compose up --build
```

The compose stack:

- builds the app from `Dockerfile`
- runs the same `bash scripts/start.sh` entrypoint used in Railway
- runs migrations on boot
- serves the FastAPI app on `$PORT`
- starts Redis locally, though the app can degrade gracefully if Redis is absent

## Railway Deployment

Railway deploys this repo using:

- [`railway.json`](./railway.json)
- [`Dockerfile`](./Dockerfile)
- [`scripts/start.sh`](./scripts/start.sh)
- [`scripts/migrate.sh`](./scripts/migrate.sh)

Runtime behavior:

- Railway builds the container from `Dockerfile`.
- The deploy starts with `bash scripts/start.sh`.
- `scripts/start.sh` runs `scripts/migrate.sh` first, then launches `uvicorn`.
- Railway healthchecks use `/health/live`.

### Required Railway Variables

Use [`env.production.example`](./env.production.example) as the baseline. In practice, these are the most important production variables:

- `OPENVEGAS_RUNTIME_ENV=production`
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_JWT_SECRET`
- `DATABASE_URL`
- `DATABASE_DIRECT_URL`
- `OPENVEGAS_COOKIE_SECURE=1`
- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_ORG_PRICE_ID`
- `APP_BASE_URL`
- `CHECKOUT_SUCCESS_URL`
- `CHECKOUT_CANCEL_URL`
- `ALLOWED_ORIGINS`
- `OPENAI_API_KEY` and any other provider keys you use

### Database URLs

Use different connection strings for runtime traffic vs. DDL:

- `DATABASE_URL`: pooled connection string for the running app
- `DATABASE_DIRECT_URL`: direct Postgres connection for migrations

`scripts/migrate.sh` prefers `DATABASE_DIRECT_URL`. If it is missing, it falls back to `DATABASE_URL` and warns because PgBouncer-style poolers can break DDL statements.

### Domains

Current intended host split:

- `https://openvegas.ai` is the public website domain
- `https://app.openvegas.ai` is the app/API domain

Current root-path behavior:

- `https://openvegas.ai/` redirects to `/ui`
- `https://app.openvegas.ai/` returns a small API status payload

This behavior lives in [`server/main.py`](./server/main.py).

Recommended related variables:

- `APP_BASE_URL=https://app.openvegas.ai`
- `ALLOWED_ORIGINS=https://app.openvegas.ai,https://openvegas.ai`
- `OPENVEGAS_AUTH_EMAIL_REDIRECT_URL=https://app.openvegas.ai/ui/login?...`

### Stripe and Webhooks

Stripe should point at the app/API domain, not the marketing domain.

- Webhook endpoint: `https://app.openvegas.ai/billing/webhook/stripe`
- Checkout success/cancel URLs should also use the app domain

## Supabase Schema

Schema files live in `supabase/migrations/` and the seed file lives at `supabase/seed.sql`.

The deployment path uses `scripts/migrate.sh`, which:

- creates a `schema_version` tracking table if needed
- backfills migration tracking for older databases that predate the migration ledger
- applies unapplied SQL files in sorted order
- applies `seed.sql` once

## CLI Binary and npm Package

OpenVegas ships a Python CLI plus a thin npm installer:

- Python package version lives in [`pyproject.toml`](./pyproject.toml) and [`openvegas/__init__.py`](./openvegas/__init__.py)
- npm wrapper version lives in [`npm-cli/package.json`](./npm-cli/package.json)
- npm install downloads a platform-specific binary from GitHub Releases

Important current behavior:

- Frozen builds default to `https://app.openvegas.ai` as `DEFAULT_BACKEND_URL`
- Frozen builds also bake in production Supabase URL and anon key defaults
- Users can still override these via env vars or local config

The npm bootstrap logic lives in:

- [`npm-cli/bin/openvegas.js`](./npm-cli/bin/openvegas.js)
- [`npm-cli/lib/download.js`](./npm-cli/lib/download.js)

## Cutting a Release

Binary releases are driven by git tags that start with `v`. The workflow lives in [`.github/workflows/release.yml`](./.github/workflows/release.yml).

Typical release flow:

1. Bump the Python package version in `pyproject.toml`.
2. Sync related version surfaces:
   `openvegas/__init__.py`, `server/main.py`, and `npm-cli/package.json`.
3. Optionally run:
   `bash scripts/sync-version.sh`
4. Commit the release.
5. Create and push a tag such as `v0.3.3`.

When the tag is pushed, GitHub Actions:

- builds binaries for `linux-x64`, `darwin-arm64`, and `win-x64`
- generates SHA256 checksum files
- publishes the binaries to the GitHub Release for that tag
- publishes the npm package from `npm-cli/` after the GitHub Release is published

npm publishing is handled by [`.github/workflows/npm-publish.yml`](./.github/workflows/npm-publish.yml) and requires a repository secret named `NPM_TOKEN`.

The workflow supports both:

- automatic publish on future GitHub Releases
- manual `workflow_dispatch` for already-cut tags such as `v0.3.3`

One-time npm setup:

- create the npm package under the account that should own `openvegas`
- create an npm access token with publish rights
- add it to GitHub repository secrets as `NPM_TOKEN`
- make sure the package name `openvegas` is available or already owned by your npm account

You can also build a binary locally with:

```bash
bash scripts/build-binary.sh linux-x64
```

## Recent Deployment Notes

Recent production-facing changes worth keeping in mind:

- Railway deployment files were added so the repo can build and boot directly on Railway.
- GitHub Releases now publish CLI binaries that the npm package downloads automatically.
- Frozen binaries now target `https://app.openvegas.ai` by default.
- Root-path routing is host-aware so the website domain redirects to `/ui` while the app domain stays API-shaped.
