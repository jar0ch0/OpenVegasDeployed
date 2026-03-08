"""Agent runtime routes (sessions, infer, budget, and boost)."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from openvegas.gateway.inference import InferenceRequest
from openvegas.wallet.ledger import InsufficientBalance
from server.middleware.auth import require_scope
from server.services.dependencies import (
    get_agent_service,
    get_boost_service,
    get_catalog,
    get_gateway,
)

router = APIRouter(prefix="/v1/agent")


class StartSessionRequest(BaseModel):
    envelope_v: Decimal


class InferRequest(BaseModel):
    session_id: str
    prompt: str
    provider: str
    model: str
    max_tokens: int = 1024


class BoostChallengeRequest(BaseModel):
    session_id: str


class BoostSubmitRequest(BaseModel):
    challenge_id: str
    artifact_text: str


@router.post("/sessions/start")
async def start_session(req: StartSessionRequest, agent: dict = Depends(require_scope("infer"))):
    svc = get_agent_service()
    try:
        return await svc.start_session(
            agent_account_id=agent["agent_account_id"],
            org_id=agent["org_id"],
            envelope_v=Decimal(str(req.envelope_v)),
        )
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/budget")
async def budget(
    session_id: str = Query(...),
    agent: dict = Depends(require_scope("budget.read")),
):
    svc = get_agent_service()
    data = await svc.get_budget(session_id, agent_account_id=agent["agent_account_id"])
    if data.get("error"):
        raise HTTPException(404, data["error"])
    return data


@router.post("/infer")
async def infer(req: InferRequest, agent: dict = Depends(require_scope("infer"))):
    agent_svc = get_agent_service()
    catalog = get_catalog()
    gateway = get_gateway()

    mc = await catalog.get_pricing(req.provider, req.model)
    estimate = gateway._estimate_max_cost(mc, req.max_tokens)
    allowed = await agent_svc.check_session_budget(
        session_id=req.session_id,
        amount_v=estimate,
        agent_account_id=agent["agent_account_id"],
    )
    if not allowed:
        raise HTTPException(400, "Insufficient or inactive session budget")

    try:
        result = await gateway.infer(
            InferenceRequest(
                account_id=f"agent:{agent['agent_account_id']}",
                provider=req.provider,
                model=req.model,
                messages=[{"role": "user", "content": req.prompt}],
                max_tokens=req.max_tokens,
            )
        )
    except InsufficientBalance as e:
        raise HTTPException(400, str(e))

    await agent_svc.record_spend(
        session_id=req.session_id,
        amount_v=result.v_cost,
        agent_account_id=agent["agent_account_id"],
    )

    return {
        "text": result.text,
        "v_cost": str(result.v_cost),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }


@router.post("/boost/challenge")
async def boost_challenge(
    req: BoostChallengeRequest,
    agent: dict = Depends(require_scope("boost")),
):
    svc = get_boost_service()
    try:
        return await svc.create_challenge(
            org_id=agent["org_id"],
            session_id=req.session_id,
        )
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/boost/submit")
async def boost_submit(
    req: BoostSubmitRequest,
    agent: dict = Depends(require_scope("boost")),
):
    svc = get_boost_service()
    try:
        return await svc.submit_and_score(
            challenge_id=req.challenge_id,
            artifact_text=req.artifact_text,
            agent_account_id=agent["agent_account_id"],
            org_id=agent["org_id"],
        )
    except Exception as e:
        raise HTTPException(400, str(e))
