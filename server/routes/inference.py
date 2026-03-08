"""Inference routes — AI gateway."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.middleware.auth import get_current_user
from server.services.dependencies import get_gateway, get_fraud_engine
from openvegas.gateway.catalog import ModelDisabled
from openvegas.gateway.inference import InferenceRequest
from openvegas.wallet.ledger import InsufficientBalance

router = APIRouter()


class AskRequest(BaseModel):
    prompt: str
    provider: str
    model: str


@router.post("/ask")
async def ask(
    req: AskRequest,
    user: dict = Depends(get_current_user),
):
    fraud = get_fraud_engine()
    try:
        await fraud.check_inference(user["user_id"])
    except Exception as e:
        raise HTTPException(429, str(e))

    gateway = get_gateway()
    try:
        result = await gateway.infer(InferenceRequest(
            account_id=f"user:{user['user_id']}",
            provider=req.provider,
            model=req.model,
            messages=[{"role": "user", "content": req.prompt}],
        ))
        return {
            "text": result.text,
            "v_cost": str(result.v_cost),
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        }
    except ModelDisabled as e:
        raise HTTPException(400, str(e))
    except InsufficientBalance as e:
        raise HTTPException(400, str(e))
