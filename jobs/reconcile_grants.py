"""Check grant invariants and usage consistency."""

from __future__ import annotations

import asyncio
import os

import asyncpg


QUERY = """
SELECT id, user_id, provider, model_id, tokens_total, tokens_remaining
FROM inference_token_grants
WHERE tokens_total < 0
   OR tokens_remaining < 0
   OR tokens_remaining > tokens_total
"""


async def main() -> int:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is required")

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(QUERY)
    finally:
        await conn.close()

    if not rows:
        print("OK: grant invariants hold")
        return 0

    print(f"FAIL: found {len(rows)} invalid grant rows")
    for row in rows:
        print(dict(row))
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
