"""Cleanup retention for horse quote pricing artifacts."""

from __future__ import annotations

import asyncio
import os

import asyncpg


async def main() -> int:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is required")

    quote_days = max(1, int(os.getenv("OPENVEGAS_HORSE_QUOTE_RETENTION_DAYS", "7")))
    idem_days = max(1, int(os.getenv("OPENVEGAS_HORSE_IDEMPOTENCY_RETENTION_DAYS", "14")))

    conn = await asyncpg.connect(dsn)
    try:
        deleted_expired = await conn.execute(
            f"""
            DELETE FROM horse_quotes
            WHERE consumed_at IS NULL
              AND expires_at < now() - interval '{quote_days} days'
            """
        )
        deleted_consumed = await conn.execute(
            f"""
            DELETE FROM horse_quotes
            WHERE consumed_at IS NOT NULL
              AND consumed_at < now() - interval '{quote_days} days'
            """
        )
        deleted_idem = await conn.execute(
            f"""
            DELETE FROM horse_quote_idempotency
            WHERE created_at < now() - interval '{idem_days} days'
            """
        )
    finally:
        await conn.close()

    print(deleted_expired)
    print(deleted_consumed)
    print(deleted_idem)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
