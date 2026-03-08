"""Expire stale agent/casino sessions."""

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
        agent = await conn.execute(
            """
            UPDATE agent_sessions
            SET status = 'closed', ended_at = now()
            WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at < now()
            """
        )
        casino = await conn.execute(
            """
            UPDATE casino_sessions
            SET status = 'closed', ended_at = now()
            WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at < now()
            """
        )
    finally:
        await conn.close()

    print(f"agent_sessions: {agent}")
    print(f"casino_sessions: {casino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
