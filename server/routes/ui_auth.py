"""UI auth routes for browser credential login."""

from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class UiLoginRequest(BaseModel):
    email: str
    password: str


@router.post("/ui/auth/login")
async def ui_login(payload: UiLoginRequest):
    email = payload.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Invalid email")

    supabase_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    supabase_anon = os.getenv("SUPABASE_ANON_KEY", "").strip()
    if not supabase_url or not supabase_anon:
        raise HTTPException(status_code=500, detail="Supabase auth is not configured")

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            res = await client.post(
                f"{supabase_url}/auth/v1/token?grant_type=password",
                headers={
                    "apikey": supabase_anon,
                    "Content-Type": "application/json",
                },
                json={"email": email, "password": payload.password},
            )
    except Exception:
        raise HTTPException(status_code=503, detail="Unable to reach auth provider")

    body = res.json() if res.content else {}
    if res.status_code in (400, 401):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if res.status_code >= 400:
        msg = body.get("msg") or body.get("error_description") or "Auth login failed"
        raise HTTPException(status_code=502, detail=str(msg))

    access_token = body.get("access_token")
    refresh_token = body.get("refresh_token")
    user = body.get("user") or {}
    if not access_token:
        raise HTTPException(status_code=502, detail="Auth provider returned no access token")

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user_id": user.get("id"),
        "email": user.get("email"),
    }
