"""Audit store idempotency key collisions."""

from __future__ import annotations

import asyncio
import os

import asyncpg


QUERY = """
SELECT user_id, idempotency_key,
       COUNT(*) AS rows,
       COUNT(DISTINCT idempotency_payload_hash) AS payload_variants
FROM store_orders
GROUP BY user_id, idempotency_key
HAVING COUNT(*) > 1 OR COUNT(DISTINCT idempotency_payload_hash) > 1
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
        print("OK: no idempotency collisions")
        return 0

    print(f"WARN: found {len(rows)} idempotency collisions")
    for row in rows:
        print(dict(row))
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
