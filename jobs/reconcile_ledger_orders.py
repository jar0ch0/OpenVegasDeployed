"""Reconcile store orders against wallet ledger + grant issuance."""

from __future__ import annotations

import asyncio
import os

import asyncpg


QUERY = """
SELECT so.id,
       COALESCE(le.cnt, 0) AS redeem_entries,
       COALESCE(gr.cnt, 0) AS grant_rows
FROM store_orders so
LEFT JOIN (
  SELECT reference_id, COUNT(*) AS cnt
  FROM ledger_entries
  WHERE entry_type = 'redeem'
  GROUP BY reference_id
) le ON le.reference_id = 'store:' || so.id::text
LEFT JOIN (
  SELECT source_order_id, COUNT(*) AS cnt
  FROM inference_token_grants
  GROUP BY source_order_id
) gr ON gr.source_order_id = so.id
WHERE so.status = 'fulfilled'
  AND (COALESCE(le.cnt, 0) <> 1 OR COALESCE(gr.cnt, 0) = 0)
ORDER BY so.created_at DESC
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
        print("OK: fulfilled orders reconcile cleanly")
        return 0

    print(f"FAIL: found {len(rows)} fulfilled order mismatches")
    for row in rows:
        print(dict(row))
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
