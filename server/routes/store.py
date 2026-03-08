"""Store routes — catalog, purchase settlement, and grant inspection."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.middleware.auth import get_current_user
from server.services.dependencies import get_store_service
from openvegas.store.service import IdempotencyConflict, StoreError
from openvegas.wallet.ledger import InsufficientBalance

router = APIRouter(prefix="/store")


class StoreBuyRequest(BaseModel):
    item_id: str
    idempotency_key: str | None = None


@router.get("/list")
async def list_store(user: dict = Depends(get_current_user)):
    del user
    svc = get_store_service()
    return {"items": await svc.list_catalog()}


@router.post("/buy")
async def buy_item(req: StoreBuyRequest, user: dict = Depends(get_current_user)):
    svc = get_store_service()
    key = req.idempotency_key or f"cli-{uuid.uuid4().hex[:12]}"

    try:
        res = await svc.buy(user_id=user["user_id"], item_id=req.item_id, idempotency_key=key)
        return {
            "order_id": res.order_id,
            "status": res.status,
            "state": res.state,
            "item_id": res.item_id,
            "cost_v": str(res.cost_v),
            "grants": res.grants,
            "idempotency_key": key,
        }
    except IdempotencyConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    except InsufficientBalance as e:
        raise HTTPException(status_code=400, detail=str(e))
    except StoreError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/grants")
async def list_grants(user: dict = Depends(get_current_user)):
    svc = get_store_service()
    grants = await svc.list_grants(user["user_id"])
    return {"grants": grants}
