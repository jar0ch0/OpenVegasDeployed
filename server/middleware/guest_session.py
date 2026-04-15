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
        Atomically debit cost_v from ALL THREE balance keys:
          - per-session key  (guest:balance:session:{id})
          - per-IP key       (guest:balance:ip:{hash})
          - per-fingerprint key (guest:balance:fp:{hash}, if present)

        All three are decremented to the same new floor so that reconnecting
        a WebSocket does not grant a fresh 50 $V — the axis keys reflect the
        true remaining budget and are re-read at each new session creation.

        Returns the new effective remaining balance (may be 0 if exhausted).
        Authenticated sessions skip this path entirely.
        """
        if not self.is_guest or cost_v <= 0:
            return self.balance_v

        # Three-key atomic Lua drain.
        # KEYS: [session_key, ip_key, fp_key_or_empty_string]
        # ARGV: [cost_v_as_string]
        lua_script = """
local session_key = KEYS[1]
local ip_key      = KEYS[2]
local fp_key      = KEYS[3]
local cost        = tonumber(ARGV[1])

-- Read all three current balances (default to 0 when key is absent)
local cur_s = tonumber(redis.call('GET', session_key) or '0')
local cur_i = tonumber(redis.call('GET', ip_key)      or '0')
-- fp_key may be an empty string (no fingerprint provided) — skip in that case
local cur_f = cur_i
if fp_key ~= '' then
    cur_f = tonumber(redis.call('GET', fp_key) or '0')
end

-- Enforce the minimum across all three axes
local effective = math.min(cur_s, cur_i, cur_f)
if effective <= 0 then return 0 end

local next_val = math.max(0, effective - cost)

-- Write the same new value to all three keys, preserving their existing TTLs
redis.call('SET', session_key, tostring(next_val), 'KEEPTTL')
redis.call('SET', ip_key,      tostring(next_val), 'KEEPTTL')
if fp_key ~= '' then
    redis.call('SET', fp_key,  tostring(next_val), 'KEEPTTL')
end

return next_val
"""
        try:
            result = await redis.eval(
                lua_script,
                3,                         # number of KEYS
                self._session_balance_key,
                self._ip_balance_key,
                self._fp_balance_key or "",
                str(cost_v),               # ARGV[1]
            )
            self.balance_v = float(result or 0)
        except Exception:
            # Redis unavailable — fail closed: refuse spend rather than allow free usage
            self.balance_v = 0.0

        return self.balance_v

    @property
    def _session_balance_key(self) -> str:
        return f"{REDIS_KEY_PREFIX}:balance:session:{self.session_id}"

    # These are set by resolve_terminal_session after the session object is created
    _ip_balance_key: str = ""
    _fp_balance_key: str = ""

    # Keep the old property name as an alias so callers outside this file still work
    @property
    def _balance_key(self) -> str:
        return self._session_balance_key


# ─── Session resolution ───────────────────────────────────────────────────────

def _hash_key(value: str) -> str:
    """First 16 hex chars of SHA-256 — enough for key uniqueness."""
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def _extract_client_ip(ws: WebSocket) -> str:
    """Extracts client IP from Railway's X-Forwarded-For header.

    Railway's load balancer *appends* the real client IP as the rightmost
    value.  Taking the leftmost value (the old behaviour) allows trivial
    spoofing via a forged header.  We take the rightmost non-empty value
    so that only Railway's append is trusted.
    """
    forwarded = ws.headers.get("x-forwarded-for", "")
    if forwarded:
        # Rightmost entry is appended by Railway's load balancer — trusted.
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]
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

    # Build the stable per-axis Redis key names (we need them both for
    # initialization AND to pass into drain() so it can decrement all three)
    ip_key = f"{REDIS_KEY_PREFIX}:balance:ip:{_hash_key(client_ip)}"
    fp_key = f"{REDIS_KEY_PREFIX}:balance:fp:{_hash_key(fp)}" if fp else ""

    ip_balance = await _get_or_create_guest_balance(redis, "ip", client_ip)
    fp_balance = ip_balance  # default to IP axis when no fingerprint provided

    if fp:
        fp_balance = await _get_or_create_guest_balance(redis, "fp", fp)

    # Enforce the stricter limit across both axes
    effective_balance = min(ip_balance, fp_balance)

    # Per-connection key seeded from IP+fp so two simultaneous tabs share state
    session_id  = f"guest-{_hash_key(client_ip + fp)}-{int(time.time())}"
    session_key = f"{REDIS_KEY_PREFIX}:balance:session:{session_id}"
    await redis.set(session_key, str(effective_balance), ex=GUEST_BALANCE_TTL)

    session = GuestSession(
        session_id=session_id,
        is_guest=True,
        balance_v=effective_balance,
    )
    # Wire axis key names so drain() can decrement all three atomically
    session._ip_balance_key = ip_key
    session._fp_balance_key = fp_key

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
