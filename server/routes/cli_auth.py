"""CLI OAuth handshake routes.

Enables zero-friction `openvegas login` by bridging Supabase OAuth
back to the CLI's local server on port 8989.

FLOW
────
  1. CLI opens: GET /ui/auth/cli/start?state=<nonce>
     → Server stores nonce in Redis (TTL 120s), redirects to Supabase OAuth
  2. Supabase completes, returns to: GET /ui/auth/cli/callback#access_token=...
     → Browser JS at the login page posts tokens to: POST /ui/auth/cli/exchange
  3. Server validates tokens, checks Redis nonce, issues signed redirect to:
     http://localhost:8989/callback?token=<JWT>&refresh=<token>&state=<nonce>
  4. CLI's local server captures it, saves to ~/.openvegas/config.json

SECURITY
────────
  - State nonce is stored in Redis with 120s TTL; used exactly once
  - Only redirects to 127.0.0.1:8989 (never any other host)
  - Validates Supabase access_token before issuing the redirect
  - HTTPS-only for the backend leg (Railway terminates TLS)
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from server.services.dependencies import current_flags, get_redis, request_with_http_client

router = APIRouter()

CLI_CALLBACK_HOST = "http://127.0.0.1:8989"
STATE_NONCE_TTL   = 120          # seconds
REDIS_NONCE_PREFIX = "cli_login_nonce:"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _supabase_cfg() -> tuple[str, str]:
    url  = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    anon = os.getenv("SUPABASE_ANON_KEY", "").strip()
    if not url or not anon:
        raise HTTPException(500, "Supabase is not configured")
    return url, anon


async def _validate_supabase_token(access_token: str) -> dict[str, Any]:
    """Validate an access_token against Supabase /auth/v1/user."""
    url, anon = _supabase_cfg()
    try:
        resp = await request_with_http_client(
            "GET",
            f"{url}/auth/v1/user",
            headers={"Authorization": f"Bearer {access_token}", "apikey": anon},
            timeout=10,
        )
    except Exception as exc:
        raise HTTPException(503, "Auth provider unreachable") from exc

    if resp.status_code != 200:
        raise HTTPException(401, "Invalid or expired access token")

    payload = resp.json()
    user_id = payload.get("id")
    if not user_id:
        raise HTTPException(401, "Token payload missing user_id")

    return {"user_id": user_id, "email": payload.get("email", "")}


# ─── Step 1: CLI starts the login — returns the Supabase OAuth URL ─────────────

@router.get("/ui/auth/cli/start")
async def cli_login_start(state: str, request: Request):
    """
    Called by the browser (opened by the CLI).
    Stores the nonce in Redis, then redirects to the Supabase OAuth page.
    The Supabase redirect_to points back to our login page which will
    POST the tokens to /ui/auth/cli/exchange.
    """
    if not state or len(state) < 16 or len(state) > 128:
        raise HTTPException(400, "Invalid state parameter")

    redis = get_redis()
    nonce_key = REDIS_NONCE_PREFIX + hashlib.sha256(state.encode()).hexdigest()
    await redis.setex(nonce_key, STATE_NONCE_TTL, "1")

    # Redirect to our login page; JavaScript there handles the Supabase flow
    # and will POST tokens to /ui/auth/cli/exchange once OAuth completes.
    params = urlencode({"mode": "cli", "state": state})
    return RedirectResponse(
        url=f"/ui/login?{params}",
        status_code=302,
    )


# ─── Step 2: Browser POSTs tokens after Supabase OAuth completes ──────────────

class CliExchangeRequest(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: int | None = None
    state: str


@router.post("/ui/auth/cli/exchange")
async def cli_token_exchange(payload: CliExchangeRequest, request: Request):
    """
    Called by the browser's login page JavaScript after Supabase
    returns the access_token in the URL fragment.

    Validates the token, consumes the Redis nonce, then returns
    the redirect URL that the browser should navigate to — which
    is intercepted by the CLI's local server.
    """
    if not payload.state or len(payload.state) < 16:
        raise HTTPException(400, "Invalid state")

    redis = get_redis()
    nonce_key = REDIS_NONCE_PREFIX + hashlib.sha256(payload.state.encode()).hexdigest()

    # Consume nonce atomically — use it exactly once
    stored = await redis.getdel(nonce_key)
    if not stored:
        raise HTTPException(400, "State expired or already used. Run `openvegas login` again.")

    # Validate the token with Supabase before forwarding
    user = await _validate_supabase_token(payload.access_token)

    expires_at = payload.expires_at or (int(time.time()) + 3600)

    # Build the redirect back to the CLI's local server
    callback_params = urlencode({
        "token":      payload.access_token,
        "refresh":    payload.refresh_token,
        "expires_at": str(expires_at),
        "user_id":    user["user_id"],
        "state":      payload.state,
    })
    redirect_url = f"{CLI_CALLBACK_HOST}/callback?{callback_params}"

    return {"redirect_url": redirect_url}


# ─── Step 3: Direct redirect variant (for simpler flows without JS exchange) ──

@router.get("/ui/auth/cli/callback")
async def cli_direct_callback(
    access_token: str = "",
    refresh_token: str = "",
    expires_at: int = 0,
    state: str = "",
    error: str = "",
    request: Request = None,  # type: ignore[assignment]
):
    """
    Direct GET redirect from Supabase (used when redirect_to points here).
    Less common — most flows use the JS exchange route above.
    """
    if error:
        params = urlencode({"error": error, "state": state})
        return RedirectResponse(url=f"{CLI_CALLBACK_HOST}/callback?{params}", status_code=302)

    if not access_token or not refresh_token:
        raise HTTPException(400, "Missing token in callback")

    if state:
        redis = get_redis()
        nonce_key = REDIS_NONCE_PREFIX + hashlib.sha256(state.encode()).hexdigest()
        stored = await redis.getdel(nonce_key)
        if not stored:
            raise HTTPException(400, "State expired or already used")

    user = await _validate_supabase_token(access_token)
    ts = expires_at or (int(time.time()) + 3600)

    callback_params = urlencode({
        "token":      access_token,
        "refresh":    refresh_token,
        "expires_at": str(ts),
        "user_id":    user["user_id"],
        "state":      state,
    })
    return RedirectResponse(
        url=f"{CLI_CALLBACK_HOST}/callback?{callback_params}",
        status_code=302,
    )
