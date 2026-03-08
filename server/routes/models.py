"""Model catalog routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from server.middleware.auth import get_current_user
from server.services.dependencies import get_catalog

router = APIRouter()


@router.get("/models")
async def list_models(
    provider: str | None = Query(None),
    user: dict = Depends(get_current_user),
):
    catalog = get_catalog()
    models = await catalog.list_models(provider=provider)
    return {"models": models}
