"""Expire old unconsumed mint challenges."""

from __future__ import annotations

import asyncio
import os

import asyncpg


async def main() -> int:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is required")

    conn = await asyncpg.connect(dsn)
    try:
        result = await conn.execute(
            "DELETE FROM mint_challenges WHERE consumed = FALSE AND expires_at < now() - interval '7 days'"
        )
    finally:
        await conn.close()

    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
