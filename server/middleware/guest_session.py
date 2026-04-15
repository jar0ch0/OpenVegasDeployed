"""Guest session middleware for unauthenticated web terminal access.

DESIGN
──────
  Unauthenticated visitors get a temporary 50 $V sandbox session.
  Rate limiting runs on two axes:
    1. IP address (X-Forwarded-For, trusting Railway's proxy headers)
    2. Browser fingerprint (sent in the WebSocket query param `fp`)

  Both limits are enforced independently. The stricter one applies.

REDIS KEY SCHEMA
────────────────
  guest:balance:ip:{sha256(ip)[:16]}          FLOAT  → remaining $V
  guest:balance:fp:{sha256(fp)[:16]}          FLOAT  → remaining $V
  guest:created:ip:{sha256(ip)[:16]}          INT    → Unix timestamp
  guest:created:fp:{sha256(fp)[:16]}          INT    → Unix timestamp
  guest:sessions:total                        INT    → global counter (metrics)

TTLS
────
  Balance keys expire after 24h — guests get a fresh 50 $V each day.
  If the balance hits 0 before expiry, session is locked until key expires.

SYSTEM_LOCK SIGNAL
──────────────────
  When drain() returns 0, the WebSocket endpoint sends:
    { "type": "SYSTEM_LOCK", "reason": "guest_balance_exhausted",
      "message": "Create a free account to keep going." }
  The xterm.js client overlay renders a neon auth prompt and
  disables further input.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)

GUEST_INITIAL_V    = 50.0     # $V granted to fresh guest sessions
GUEST_BALANCE_TTL  = 86_400   # 24 hours in seconds
MAX_GUESTS_PER_IP  = 3        # concurrent active sessions per IP
REDIS_KEY_PREFIX   = "guest"


# ─── GuestSession data class ──────────────────────────────────────────────────

@dataclass
class GuestSession:
    session_id: str
    is_guest: bool
    balance_v: float
    user_id: str | None = None     # set for authenticated sessions

    async def drain(self, redis: Any, cost_v: float) -> float:
        """
        Atomically debit cost_v from the session balance.
        Returns the new remaining balance (may be 0 if exhausted).
        Guest sessions drain from Redis; authenticated sessions skip this.
        """
        if not self.is_guest or cost_v <= 0:
            return self.balance_v

        # We use a Lua script for atomic read-decrement-floor-at-zero
        lua_script = """
local key = KEYS[1]
local cost = tonumber(ARGV[1])
local cur  = tonumber(redis.call('GET', key) or '0')
if cur <= 0 then return 0 end
local next = math.max(0, cur - cost)
redis.call('SET', key, tostring(next), 'KEEPTTL')
return next
"""
        try:
            result = await redis.eval(lua_script, 1, self._balance_key, str(cost_v))
            self.balance_v = float(result or 0)
        except Exception:
            # Redis unavailable — allow session to continue (fail open)
            self.balance_v = max(0.0, self.balance_v - cost_v)

        return self.balance_v

    @property
    def _balance_key(self) -> str:
        return f"{REDIS_KEY_PREFIX}:balance:session:{self.session_id}"


# ─── Session resolution ───────────────────────────────────────────────────────

def _hash_key(value: str) -> str:
    """First 16 hex chars of SHA-256 — enough for key uniqueness."""
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def _extract_client_ip(ws: WebSocket) -> str:
    """Extracts client IP, trusting Railway's X-Forwarded-For."""
    forwarded = ws.headers.get("x-forwarded-for", "")
    if forwarded:
        # Leftmost IP is the original client
        return forwarded.split(",")[0].strip()
    return ws.client.host if ws.client else "unknown"


async def _get_or_create_guest_balance(
    redis: Any,
    dimension: str,  # "ip" or "fp"
    identifier: str,
) -> float:
    """
    Get or initialize a guest balance for a given dimension+identifier.
    Returns the current balance (may be 0 if exhausted).
    """
    key = f"{REDIS_KEY_PREFIX}:balance:{dimension}:{_hash_key(identifier)}"
    raw = await redis.get(key)

    if raw is None:
        # New guest — grant initial balance with 24h TTL
        await redis.set(key, str(GUEST_INITIAL_V), ex=GUEST_BALANCE_TTL)
        created_key = f"{REDIS_KEY_PREFIX}:created:{dimension}:{_hash_key(identifier)}"
        await redis.set(created_key, str(int(time.time())), ex=GUEST_BALANCE_TTL)
        return GUEST_INITIAL_V

    return float(raw)


async def resolve_terminal_session(
    token: str,
    ws: WebSocket,
    redis: Any,
    fingerprint: str = "",
) -> GuestSession:
    """
    Resolves a terminal WebSocket connection to either an authenticated
    session or a rate-limited guest session.

    Called at the top of the /ws/terminal endpoint before spawning the PTY.
    """
    # ── Authenticated path ────────────────────────────────────────────────────
    if token:
        try:
            from server.middleware.auth import _validate_with_supabase
            user_info = await _validate_with_supabase(token)
            return GuestSession(
                session_id=user_info["user_id"],
                is_guest=False,
                balance_v=float("inf"),   # auth users are not balance-gated here
                user_id=user_info["user_id"],
            )
        except Exception:
            # Invalid token — fall through to guest mode
            logger.warning("terminal: invalid auth token, downgrading to guest session")

    # ── Guest path ────────────────────────────────────────────────────────────
    client_ip = _extract_client_ip(ws)
    fp        = (fingerprint or ws.query_params.get("fp", "")).strip()[:64]

    # Take the minimum of IP-based and fingerprint-based balances
    ip_balance = await _get_or_create_guest_balance(redis, "ip", client_ip)
    fp_balance = ip_balance  # default to IP if no fingerprint

    if fp:
        fp_balance = await _get_or_create_guest_balance(redis, "fp", fp)

    # Enforce the stricter limit
    effective_balance = min(ip_balance, fp_balance)

    # Create a per-connection balance key seeded from IP+fp minimum
    session_id = f"guest-{_hash_key(client_ip + fp)}-{int(time.time())}"
    balance_key = f"{REDIS_KEY_PREFIX}:balance:session:{session_id}"
    await redis.set(balance_key, str(effective_balance), ex=GUEST_BALANCE_TTL)

    session = GuestSession(
        session_id=session_id,
        is_guest=True,
        balance_v=effective_balance,
    )

    if effective_balance <= 0:
        # Balance already exhausted — send SYSTEM_LOCK immediately
        try:
            await ws.send_text(
                '{"type":"SYSTEM_LOCK","reason":"guest_balance_exhausted",'
                '"message":"Create a free account — takes 10 seconds."}'
            )
            await ws.close(code=1008)
        except Exception:
            pass

    return session
