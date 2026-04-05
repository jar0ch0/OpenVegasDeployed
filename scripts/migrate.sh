#!/usr/bin/env bash
set -euo pipefail

echo "[migrate] Starting migration runner..."

# ── Pick the right connection string ────────
# Migrations run DDL (CREATE TABLE, ALTER TABLE) which can break on
# PgBouncer's transaction-pooling mode. Use the direct Supabase URL.
#
# DATABASE_DIRECT_URL → direct to Postgres (port 5432, no pooler)
# DATABASE_URL        → pooler URL (port 6543, for the running app)
#
# The migration script prefers DIRECT; falls back to DATABASE_URL
# with a loud warning so you know to fix it.

if [ -n "${DATABASE_DIRECT_URL:-}" ]; then
    MIGRATE_DB_URL="$DATABASE_DIRECT_URL"
    echo "[migrate] Using DATABASE_DIRECT_URL (direct connection — correct for DDL)"
elif [ -n "${DATABASE_URL:-}" ]; then
    MIGRATE_DB_URL="$DATABASE_URL"
    echo "[migrate] WARNING: DATABASE_DIRECT_URL is not set."
    echo "[migrate]   Falling back to DATABASE_URL — this may fail if it's a"
    echo "[migrate]   PgBouncer pooler URL. Set DATABASE_DIRECT_URL to the"
    echo "[migrate]   direct Supabase connection string (port 5432)."
else
    echo "[migrate] ERROR: Neither DATABASE_DIRECT_URL nor DATABASE_URL is set."
    exit 1
fi

# ── Migrations directory ────────────────────
MIGRATIONS_DIR="${MIGRATIONS_DIR:-supabase/migrations}"
SEED_FILE="${SEED_FILE:-supabase/seed.sql}"

if [ ! -d "$MIGRATIONS_DIR" ]; then
    echo "[migrate] WARNING: No migrations directory at ${MIGRATIONS_DIR}. Skipping."
    exit 0
fi

# ── Export for the heredoc ──────────────────
export MIGRATE_DB_URL MIGRATIONS_DIR SEED_FILE

# ── Run via Python (always available in this image) ─
python3 << 'PYTHON_MIGRATE'
import os, glob, sys

try:
    import psycopg2
except ImportError:
    print("[migrate] ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

db_url = os.environ["MIGRATE_DB_URL"]
migrations_dir = os.environ.get("MIGRATIONS_DIR", "supabase/migrations")
seed_file = os.environ.get("SEED_FILE", "supabase/seed.sql")

conn = psycopg2.connect(db_url)
conn.autocommit = True
cur = conn.cursor()

# ── Create tracking table if it doesn't exist ─
cur.execute("""
    CREATE TABLE IF NOT EXISTS schema_version (
        version   TEXT PRIMARY KEY,
        applied_at TIMESTAMPTZ DEFAULT now()
    );
""")

# ── Check if this is a fresh schema_version on an existing database ─
# If schema_version is empty but tables already exist (e.g. "profiles"),
# this database was set up before we added migration tracking.
# Mark all known migration files as already applied so we don't
# try to re-create existing tables.
cur.execute("SELECT count(*) FROM schema_version")
tracked_count = cur.fetchone()[0]

if tracked_count == 0:
    # Check if the database already has tables from previous setup
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_name = 'profiles'
        )
    """)
    db_already_populated = cur.fetchone()[0]

    if db_already_populated:
        print("[migrate] Detected existing database with no migration tracking.")
        print("[migrate] Marking all current migration files as already applied...")
        migration_files = sorted(glob.glob(os.path.join(migrations_dir, "*.sql")))
        for path in migration_files:
            version = os.path.basename(path)
            cur.execute(
                "INSERT INTO schema_version (version) VALUES (%s) ON CONFLICT DO NOTHING",
                (version,)
            )
        # Also mark seed as applied since the DB is already populated
        cur.execute(
            "INSERT INTO schema_version (version) VALUES ('__seed__') ON CONFLICT DO NOTHING"
        )
        count = len(migration_files)
        print(f"[migrate] Marked {count} migrations + seed as already applied.")
        print("[migrate] Future deploys will only run NEW migration files.")

        cur.execute("SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT 1")
        row = cur.fetchone()
        print(f"[migrate] Current schema version: {row[0] if row else '(none)'}")
        cur.close()
        conn.close()
        sys.exit(0)

# ── Normal migration path: apply any unapplied migrations ───────
migration_files = sorted(glob.glob(os.path.join(migrations_dir, "*.sql")))

if not migration_files:
    print(f"[migrate] No .sql files found in {migrations_dir}.")
else:
    applied = 0
    skipped = 0

    for path in migration_files:
        version = os.path.basename(path)

        cur.execute("SELECT 1 FROM schema_version WHERE version = %s", (version,))
        if cur.fetchone():
            skipped += 1
            continue

        print(f"[migrate] Applying: {version}")
        with open(path) as f:
            sql = f.read()
        try:
            cur.execute(sql)
        except Exception as e:
            print(f"[migrate] FAILED on {version}: {e}")
            sys.exit(1)

        cur.execute("INSERT INTO schema_version (version) VALUES (%s)", (version,))
        applied += 1

    print(f"[migrate] Migrations done. Applied: {applied}, Skipped: {skipped}")

# ── Run seed.sql if it exists and hasn't been applied ─
if os.path.isfile(seed_file):
    cur.execute("SELECT 1 FROM schema_version WHERE version = '__seed__'")
    if cur.fetchone():
        print("[migrate] Seed already applied, skipping.")
    else:
        print(f"[migrate] Applying seed: {seed_file}")
        with open(seed_file) as f:
            sql = f.read()
        try:
            cur.execute(sql)
        except Exception as e:
            print(f"[migrate] FAILED on seed: {e}")
            sys.exit(1)
        cur.execute("INSERT INTO schema_version (version) VALUES ('__seed__')")
        print("[migrate] Seed applied.")
else:
    print(f"[migrate] No seed file at {seed_file}, skipping.")

# ── Report current schema version ───────────
cur.execute("SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT 1")
row = cur.fetchone()
print(f"[migrate] Current schema version: {row[0] if row else '(none)'}")

cur.close()
conn.close()
PYTHON_MIGRATE