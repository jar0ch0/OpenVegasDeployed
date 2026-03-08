"""Provider catalog — reads from Supabase provider_catalog table."""

from __future__ import annotations

from decimal import Decimal
from typing import Any


class ModelDisabled(Exception):
    pass


class ProviderCatalog:
    """Interface to the provider_catalog Supabase table.
    Disabling a model blocks routing instantly without a deploy."""

    def __init__(self, db: Any):
        self.db = db

    async def get_model(self, provider: str, model_id: str) -> dict | None:
        row = await self.db.fetchrow(
            "SELECT * FROM provider_catalog WHERE provider = $1 AND model_id = $2",
            provider, model_id,
        )
        return dict(row) if row else None

    async def get_pricing(self, provider: str, model_id: str) -> dict:
        row = await self.get_model(provider, model_id)
        if not row:
            raise ValueError(f"Unknown model: {provider}/{model_id}")
        return row

    async def list_models(
        self, provider: str = None, enabled_only: bool = True
    ) -> list[dict]:
        query = "SELECT * FROM provider_catalog WHERE 1=1"
        params: list = []
        if provider:
            params.append(provider)
            query += f" AND provider = ${len(params)}"
        if enabled_only:
            query += " AND enabled = TRUE"
        query += " ORDER BY provider, model_id"
        rows = await self.db.fetch(query, *params)
        return [dict(r) for r in rows]

    async def toggle_model(self, provider: str, model_id: str, enabled: bool):
        await self.db.execute(
            "UPDATE provider_catalog SET enabled = $1, updated_at = now() "
            "WHERE provider = $2 AND model_id = $3",
            enabled, provider, model_id,
        )

    async def log_usage(
        self, account_id: str, user_id: str | None, provider: str, model_id: str,
        input_tokens: int, output_tokens: int,
        v_cost: Decimal, actual_cost: Decimal, *, tx=None,
    ):
        actor_type = "agent" if account_id.startswith("agent:") else "human"
        conn = tx or self.db
        await conn.execute(
            "INSERT INTO inference_usage "
            "(user_id, account_id, actor_type, provider, model_id, input_tokens, output_tokens, v_cost, actual_cost_usd) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
            user_id, account_id, actor_type, provider, model_id, input_tokens, output_tokens,
            v_cost, actual_cost,
        )
