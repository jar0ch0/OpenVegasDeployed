"""Store service — transactional purchases and inference grant issuance."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from openvegas.store.catalog import STORE_CATALOG
from openvegas.wallet.ledger import WalletService


class StoreError(Exception):
    pass


class IdempotencyConflict(StoreError):
    pass


class IllegalTransition(StoreError):
    pass


@dataclass
class StoreOrderResult:
    order_id: str
    status: str
    state: str
    item_id: str
    cost_v: Decimal
    grants: list[dict]


class StoreService:
    def __init__(self, db: Any, wallet: WalletService):
        self.db = db
        self.wallet = wallet

    @staticmethod
    def canonical_payload_hash(payload: dict) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _provider_for_model(model_id: str) -> str:
        model = model_id.lower()
        if model.startswith("gpt-") or "openai" in model:
            return "openai"
        if model.startswith("claude-"):
            return "anthropic"
        if model.startswith("gemini-"):
            return "gemini"
        raise StoreError(f"Cannot infer provider for model '{model_id}'")

    async def list_catalog(self) -> dict:
        return STORE_CATALOG

    async def list_grants(self, user_id: str) -> list[dict]:
        rows = await self.db.fetch(
            """
            SELECT id, source_order_id, provider, model_id, tokens_total, tokens_remaining,
                   expires_at, created_at
            FROM inference_token_grants
            WHERE user_id = $1
            ORDER BY created_at DESC
            """,
            user_id,
        )
        return [dict(r) for r in rows]

    async def _transition_order(
        self,
        tx: Any,
        order_id: str,
        from_status: str,
        to_status: str,
        reason: str | None = None,
    ) -> None:
        row = await tx.fetchrow(
            """
            UPDATE store_orders
            SET status = $3,
                failure_reason = COALESCE($4, failure_reason),
                updated_at = now()
            WHERE id = $1 AND status = $2
            RETURNING id
            """,
            order_id,
            from_status,
            to_status,
            reason,
        )
        if not row:
            raise IllegalTransition(f"Illegal transition {from_status}->{to_status} for {order_id}")

    async def _get_or_lock_order(
        self,
        tx: Any,
        user_id: str,
        idempotency_key: str,
        payload_hash: str,
    ) -> dict | None:
        row = await tx.fetchrow(
            "SELECT * FROM store_orders WHERE user_id = $1 AND idempotency_key = $2 FOR UPDATE",
            user_id,
            idempotency_key,
        )
        if not row:
            return None

        if row["idempotency_payload_hash"] != payload_hash:
            raise IdempotencyConflict("IDEMPOTENCY_PAYLOAD_CONFLICT")

        status = str(row["status"])
        if status in {"created", "settled"}:
            return {"state": "pending", "order": dict(row)}
        return {"state": "completed", "order": dict(row)}

    async def buy(self, user_id: str, item_id: str, idempotency_key: str) -> StoreOrderResult:
        if item_id not in STORE_CATALOG:
            raise StoreError(f"Unknown store item '{item_id}'")

        item = STORE_CATALOG[item_id]
        cost_v = Decimal(str(item["cost_v"]))
        payload_hash = self.canonical_payload_hash({"item_id": item_id})

        async with self.db.transaction() as tx:
            existing = await self._get_or_lock_order(tx, user_id, idempotency_key, payload_hash)
            if existing:
                order = existing["order"]
                grants = await self._fetch_grants_for_order(tx, str(order["id"]))
                return StoreOrderResult(
                    order_id=str(order["id"]),
                    status=str(order["status"]),
                    state=existing["state"],
                    item_id=order["item_id"],
                    cost_v=Decimal(str(order["cost_v"])),
                    grants=grants,
                )

            order_id = str(uuid.uuid4())
            await tx.execute(
                """
                INSERT INTO store_orders (id, user_id, item_id, cost_v, status, idempotency_key, idempotency_payload_hash)
                VALUES ($1, $2, $3, $4, 'created', $5, $6)
                """,
                order_id,
                user_id,
                item_id,
                cost_v,
                idempotency_key,
                payload_hash,
            )

            await self.wallet.redeem(
                account_id=f"user:{user_id}",
                amount=cost_v,
                reference_id=f"store:{order_id}",
                tx=tx,
            )
            await self._transition_order(tx, order_id, "created", "settled")

            grants = []
            if item.get("type") == "ai_pack":
                models = list(item.get("models", []))
                if not models:
                    raise StoreError(f"Store item '{item_id}' is missing model mapping")

                total_tokens = int(item.get("tokens", 0))
                base = total_tokens // len(models)
                remainder = total_tokens % len(models)
                for idx, model_id in enumerate(models):
                    tokens = base + (1 if idx < remainder else 0)
                    provider = self._provider_for_model(model_id)
                    await tx.execute(
                        """
                        INSERT INTO inference_token_grants
                          (user_id, source_order_id, provider, model_id, tokens_total, tokens_remaining)
                        VALUES ($1, $2, $3, $4, $5, $5)
                        ON CONFLICT (source_order_id, provider, model_id)
                        DO NOTHING
                        """,
                        user_id,
                        order_id,
                        provider,
                        model_id,
                        tokens,
                    )

                grants = await self._fetch_grants_for_order(tx, order_id)

            await self._transition_order(tx, order_id, "settled", "fulfilled")

        return StoreOrderResult(
            order_id=order_id,
            status="fulfilled",
            state="completed",
            item_id=item_id,
            cost_v=cost_v,
            grants=grants,
        )

    async def _fetch_grants_for_order(self, conn: Any, order_id: str) -> list[dict]:
        rows = await conn.fetch(
            """
            SELECT id, provider, model_id, tokens_total, tokens_remaining, expires_at, created_at
            FROM inference_token_grants
            WHERE source_order_id = $1
            ORDER BY created_at ASC
            """,
            order_id,
        )
        return [dict(r) for r in rows]
