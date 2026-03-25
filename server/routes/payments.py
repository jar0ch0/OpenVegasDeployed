"""Billing routes — card topups, org subscription checkout, and Stripe webhooks."""

from __future__ import annotations

import os
import uuid
from decimal import Decimal, InvalidOperation
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from openvegas.payments.service import BillingError, IdempotencyConflict, NotFoundError
from server.middleware.auth import get_current_user
from server.services.dependencies import get_billing_service, get_db

router = APIRouter(prefix="/billing")


class TopupCheckoutRequest(BaseModel):
    amount_usd: str
    idempotency_key: str | None = None


class PortalSessionRequest(BaseModel):
    flow_type: Literal["subscription_cancel", "payment_method_update"] | None = None


class TopupSuggestRequest(BaseModel):
    suggested_topup_usd: str | None = None


class FakeCompleteRequest(BaseModel):
    topup_id: str


async def require_org_admin(org_id: str, user_id: str) -> None:
    db = get_db()
    row = await db.fetchrow(
        """
        SELECT role
        FROM org_members
        WHERE org_id = $1
          AND user_id = $2
          AND status = 'active'
        """,
        org_id,
        user_id,
    )
    if not row or str(row["role"]) not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Org owner/admin access required")


@router.post("/topups/checkout")
async def create_topup_checkout(req: TopupCheckoutRequest, user: dict = Depends(get_current_user)):
    svc = get_billing_service()
    key = req.idempotency_key or f"cli-{uuid.uuid4().hex[:12]}"
    try:
        amount = Decimal(req.amount_usd)
    except (InvalidOperation, TypeError):
        raise HTTPException(status_code=400, detail="Invalid amount_usd")

    try:
        return await svc.create_topup_checkout(
            user_id=user["user_id"],
            amount_usd=amount,
            idempotency_key=key,
        )
    except IdempotencyConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    except BillingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/topups/suggest")
async def suggest_topup(req: TopupSuggestRequest | None = None, user: dict = Depends(get_current_user)):
    svc = get_billing_service()
    try:
        suggested: Decimal | None = None
        if req and req.suggested_topup_usd is not None:
            try:
                suggested = Decimal(req.suggested_topup_usd)
            except (InvalidOperation, TypeError):
                raise HTTPException(status_code=400, detail="Invalid suggested_topup_usd")
        return await svc.create_topup_suggestion(
            user_id=user["user_id"],
            suggested_topup_usd=suggested,
        )
    except BillingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/topups/{topup_id}")
async def get_topup_status(topup_id: str, user: dict = Depends(get_current_user)):
    svc = get_billing_service()
    try:
        return await svc.get_topup_status(user_id=user["user_id"], topup_id=topup_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/topups/{topup_id}/qr.svg")
async def get_topup_qr_svg(topup_id: str, user: dict = Depends(get_current_user)):
    svc = get_billing_service()
    try:
        payload = await svc.get_topup_qr_svg(user_id=user["user_id"], topup_id=topup_id)
        return Response(
            content=payload,
            media_type="image/svg+xml",
            headers={"Cache-Control": "private, no-store"},
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except BillingError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/topups/{topup_id}/verify")
async def verify_topup_status(topup_id: str, user: dict = Depends(get_current_user)):
    """Informational endpoint only; never settles funds."""
    return await get_topup_status(topup_id, user)


@router.post("/webhook/fake/complete")
async def fake_complete(req: FakeCompleteRequest, request: Request):
    if os.getenv("OPENVEGAS_BILLING_FAKE_WEBHOOK_ENABLED", "0") != "1":
        raise HTTPException(status_code=404, detail="Not found")
    if os.getenv("OPENVEGAS_BILLING_PROVIDER", "hybrid").strip().lower() == "stripe":
        raise HTTPException(status_code=403, detail="Fake completion disabled in stripe mode")

    expected_secret = os.getenv("OPENVEGAS_FAKE_WEBHOOK_SECRET", "").strip()
    if expected_secret:
        actual_secret = request.headers.get("X-OpenVegas-Fake-Webhook-Secret", "").strip()
        if actual_secret != expected_secret:
            raise HTTPException(status_code=403, detail="Invalid fake webhook secret")

    svc = get_billing_service()
    try:
        topup = await svc.get_topup_internal(topup_id=req.topup_id)
        topup_mode = ""
        if isinstance(topup, dict):
            topup_mode = str(topup.get("mode") or "")
        else:
            topup_mode = str(getattr(topup, "mode", "") or "")
        if topup_mode != "simulated":
            raise HTTPException(status_code=409, detail="Top-up is not simulated")
        return await svc.complete_fake_topup(topup_id=req.topup_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except BillingError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/orgs/{org_id}/subscription/checkout")
async def create_org_subscription_checkout(org_id: str, user: dict = Depends(get_current_user)):
    await require_org_admin(org_id, user["user_id"])
    svc = get_billing_service()
    try:
        return await svc.create_org_subscription_checkout(org_id=org_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except BillingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/orgs/{org_id}/subscription/status")
async def get_org_subscription_status(org_id: str, user: dict = Depends(get_current_user)):
    await require_org_admin(org_id, user["user_id"])
    svc = get_billing_service()
    try:
        return await svc.get_org_subscription_status(org_id=org_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/orgs/{org_id}/portal-session")
async def create_org_portal_session(
    org_id: str,
    req: PortalSessionRequest | None = None,
    user: dict = Depends(get_current_user),
):
    await require_org_admin(org_id, user["user_id"])
    svc = get_billing_service()
    try:
        return await svc.create_org_billing_portal(
            org_id=org_id,
            flow_type=(req.flow_type if req else None),
        )
    except BillingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    sig = request.headers.get("stripe-signature", "")
    raw = await request.body()
    svc = get_billing_service()
    try:
        return await svc.handle_webhook(raw_body=raw, signature=sig)
    except Exception as e:
        # Avoid leaking internal details to webhook caller
        raise HTTPException(status_code=400, detail=f"Webhook error: {e}")
