"""AI Inference Gateway — routes, meters, and bills AI usage."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from openvegas.gateway.catalog import ModelDisabled, ProviderCatalog
from openvegas.wallet.ledger import InsufficientBalance, WalletService

V_SCALE = Decimal("0.000001")


class Provider(Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"


@dataclass
class InferenceRequest:
    account_id: str   # full prefixed wallet ID: "user:<uuid>" or "agent:<uuid>"
    provider: str
    model: str
    messages: list[dict]
    max_tokens: int = 1024


@dataclass
class InferenceResult:
    text: str
    input_tokens: int
    output_tokens: int
    v_cost: Decimal = Decimal("0")
    actual_cost_usd: Decimal = Decimal("0")


class AIGateway:
    """Routes inference requests, meters usage, and settles charges with grant-first policy."""

    def __init__(self, db: Any, wallet: WalletService, catalog: ProviderCatalog):
        self.db = db
        self.wallet = wallet
        self.catalog = catalog

    async def infer(self, req: InferenceRequest) -> InferenceResult:
        model_config = await self.catalog.get_model(req.provider, req.model)
        if not model_config or not model_config["enabled"]:
            raise ModelDisabled(f"{req.model} is currently disabled")

        user_id = self._extract_user_id(req.account_id)
        request_id = f"infer:{uuid.uuid4().hex}"

        max_v_cost = self._estimate_max_cost(model_config, req.max_tokens)
        reserve_v = max_v_cost

        if user_id:
            estimated_grant_v = await self._estimate_grant_cover_v(
                user_id=user_id,
                provider=req.provider,
                model_id=req.model,
                max_tokens=req.max_tokens,
                max_v_cost=max_v_cost,
            )
            reserve_v = max((max_v_cost - estimated_grant_v), Decimal("0")).quantize(V_SCALE)

        balance = await self.wallet.get_balance(req.account_id)
        if balance < reserve_v:
            raise InsufficientBalance(f"Need {reserve_v} $V reserved, have {balance} $V")

        preauth_id = str(uuid.uuid4())
        reservation_ref = f"infer-preauth:{preauth_id}"

        async with self.db.transaction() as tx:
            await tx.execute(
                """
                INSERT INTO inference_preauthorizations
                  (id, account_id, user_id, request_id, provider, model_id, reserved_v, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, 'reserved')
                """,
                preauth_id,
                req.account_id,
                user_id,
                request_id,
                req.provider,
                req.model,
                reserve_v,
            )
            if reserve_v > 0:
                await self.wallet.reserve(
                    account_id=req.account_id,
                    amount=reserve_v,
                    reference_id=reservation_ref,
                    tx=tx,
                )

        try:
            result = await self._route_to_provider(req)
        except Exception:
            await self._void_preauth(
                preauth_id=preauth_id,
                reservation_ref=reservation_ref,
                account_id=req.account_id,
                reserved_v=reserve_v,
            )
            raise

        actual_v = self._calculate_v_cost(model_config, result.input_tokens, result.output_tokens)
        actual_usd = self._calculate_actual_usd(
            model_config, result.input_tokens, result.output_tokens
        )

        total_tokens = max(result.input_tokens + result.output_tokens, 0)
        usage_id = str(uuid.uuid4())

        grant_used_tokens = 0
        grant_used_v = Decimal("0")
        charge_v = actual_v

        async with self.db.transaction() as tx:
            if user_id and total_tokens > 0:
                grant_used_tokens = await self._consume_grants(
                    tx=tx,
                    user_id=user_id,
                    provider=req.provider,
                    model_id=req.model,
                    tokens_needed=total_tokens,
                    inference_usage_id=usage_id,
                    request_id=request_id,
                )
                grant_used_v = self._grant_coverage_v(actual_v, total_tokens, grant_used_tokens)
                charge_v = max((actual_v - grant_used_v), Decimal("0")).quantize(V_SCALE)

            await self._settle_preauth(
                tx=tx,
                preauth_id=preauth_id,
                reservation_ref=reservation_ref,
                account_id=req.account_id,
                reserved_v=reserve_v,
                settle_v=charge_v,
            )

            await tx.execute(
                """
                INSERT INTO inference_usage
                  (id, user_id, account_id, actor_type, provider, model_id,
                   input_tokens, output_tokens, v_cost, actual_cost_usd)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                usage_id,
                user_id,
                req.account_id,
                "agent" if req.account_id.startswith("agent:") else "human",
                req.provider,
                req.model,
                result.input_tokens,
                result.output_tokens,
                charge_v,
                actual_usd,
            )

        result.v_cost = charge_v
        result.actual_cost_usd = actual_usd
        return result

    async def _estimate_grant_cover_v(
        self,
        user_id: str,
        provider: str,
        model_id: str,
        max_tokens: int,
        max_v_cost: Decimal,
    ) -> Decimal:
        row = await self.db.fetchrow(
            """
            SELECT COALESCE(SUM(tokens_remaining), 0) AS remaining
            FROM inference_token_grants
            WHERE user_id = $1
              AND provider = $2
              AND model_id = $3
              AND tokens_remaining > 0
            """,
            user_id,
            provider,
            model_id,
        )
        remaining = int(row["remaining"]) if row else 0
        estimated_total = max_tokens * 3
        if estimated_total <= 0 or remaining <= 0:
            return Decimal("0")

        ratio = min(Decimal(remaining) / Decimal(estimated_total), Decimal("1"))
        return (max_v_cost * ratio).quantize(V_SCALE)

    async def _consume_grants(
        self,
        tx: Any,
        user_id: str,
        provider: str,
        model_id: str,
        tokens_needed: int,
        inference_usage_id: str,
        request_id: str,
    ) -> int:
        remaining = tokens_needed
        consumed = 0

        rows = await tx.fetch(
            """
            SELECT id, tokens_remaining
            FROM inference_token_grants
            WHERE user_id = $1
              AND provider = $2
              AND model_id = $3
              AND tokens_remaining > 0
            ORDER BY created_at ASC
            FOR UPDATE
            """,
            user_id,
            provider,
            model_id,
        )

        for row in rows:
            if remaining <= 0:
                break

            available = int(row["tokens_remaining"])
            use = min(available, remaining)
            updated = await tx.fetchrow(
                """
                UPDATE inference_token_grants
                SET tokens_remaining = tokens_remaining - $2, updated_at = now()
                WHERE id = $1 AND tokens_remaining >= $2
                RETURNING id
                """,
                row["id"],
                use,
            )
            if not updated:
                continue

            await tx.execute(
                """
                INSERT INTO inference_grant_usages
                  (grant_id, inference_usage_id, request_id, provider, model_id, tokens_used)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                row["id"],
                inference_usage_id,
                request_id,
                provider,
                model_id,
                use,
            )
            consumed += use
            remaining -= use

        return consumed

    async def _settle_preauth(
        self,
        tx: Any,
        preauth_id: str,
        reservation_ref: str,
        account_id: str,
        reserved_v: Decimal,
        settle_v: Decimal,
    ) -> None:
        reserved_v = Decimal(str(reserved_v)).quantize(V_SCALE)
        settle_v = Decimal(str(settle_v)).quantize(V_SCALE)

        if reserved_v > 0:
            settle_from_reserve = min(settle_v, reserved_v)
            await self.wallet.settle_reservation(
                account_id=account_id,
                reservation_ref=reservation_ref,
                settle_amount=settle_from_reserve,
                tx=tx,
            )
        else:
            settle_from_reserve = Decimal("0")

        extra = (settle_v - settle_from_reserve).quantize(V_SCALE)
        if extra > 0:
            await self.wallet.redeem(
                account_id=account_id,
                amount=extra,
                reference_id=f"{reservation_ref}:extra",
                tx=tx,
            )

        final_settled = (settle_from_reserve + max(extra, Decimal("0"))).quantize(V_SCALE)
        status = "settled" if final_settled > 0 else "refunded"
        await tx.execute(
            """
            UPDATE inference_preauthorizations
            SET settled_v = $2,
                status = $3,
                updated_at = now()
            WHERE id = $1
            """,
            preauth_id,
            final_settled,
            status,
        )

    async def _void_preauth(
        self,
        preauth_id: str,
        reservation_ref: str,
        account_id: str,
        reserved_v: Decimal,
    ) -> None:
        async with self.db.transaction() as tx:
            if reserved_v > 0:
                await self.wallet.settle_reservation(
                    account_id=account_id,
                    reservation_ref=reservation_ref,
                    settle_amount=Decimal("0"),
                    tx=tx,
                )
            await tx.execute(
                """
                UPDATE inference_preauthorizations
                SET settled_v = 0,
                    status = 'voided',
                    updated_at = now()
                WHERE id = $1
                """,
                preauth_id,
            )

    @staticmethod
    def _extract_user_id(account_id: str) -> str | None:
        if account_id.startswith("user:"):
            return account_id.split(":", 1)[1]
        return None

    @staticmethod
    def _grant_coverage_v(actual_v: Decimal, total_tokens: int, used_tokens: int) -> Decimal:
        if total_tokens <= 0 or used_tokens <= 0:
            return Decimal("0")
        ratio = min(Decimal(used_tokens) / Decimal(total_tokens), Decimal("1"))
        return (actual_v * ratio).quantize(V_SCALE)

    def _estimate_max_cost(self, mc: dict, max_tokens: int) -> Decimal:
        v_in = Decimal(str(mc["v_price_input_per_1m"]))
        v_out = Decimal(str(mc["v_price_output_per_1m"]))
        return (
            (Decimal(max_tokens) * 2 * v_in + Decimal(max_tokens) * v_out)
            / Decimal("1000000")
        ).quantize(V_SCALE)

    def _calculate_v_cost(self, mc: dict, input_tokens: int, output_tokens: int) -> Decimal:
        v_in = Decimal(str(mc["v_price_input_per_1m"]))
        v_out = Decimal(str(mc["v_price_output_per_1m"]))
        cost = (Decimal(input_tokens) * v_in + Decimal(output_tokens) * v_out) / Decimal("1000000")
        return cost.quantize(V_SCALE)

    def _calculate_actual_usd(self, mc: dict, input_tokens: int, output_tokens: int) -> Decimal:
        c_in = Decimal(str(mc["cost_input_per_1m"]))
        c_out = Decimal(str(mc["cost_output_per_1m"]))
        cost = (Decimal(input_tokens) * c_in + Decimal(output_tokens) * c_out) / Decimal("1000000")
        return cost.quantize(Decimal("0.000001"))

    async def _route_to_provider(self, req: InferenceRequest) -> InferenceResult:
        """Route to the appropriate provider SDK."""
        if req.provider == "anthropic":
            return await self._call_anthropic(req)
        if req.provider == "openai":
            return await self._call_openai(req)
        if req.provider == "gemini":
            return await self._call_gemini(req)
        raise ValueError(f"Unknown provider: {req.provider}")

    async def _call_anthropic(self, req: InferenceRequest) -> InferenceResult:
        import anthropic

        client = anthropic.AsyncAnthropic()
        msg = await client.messages.create(
            model=req.model,
            max_tokens=req.max_tokens,
            messages=req.messages,
        )
        return InferenceResult(
            text=msg.content[0].text,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
        )

    async def _call_openai(self, req: InferenceRequest) -> InferenceResult:
        import openai

        client = openai.AsyncOpenAI()
        resp = await client.chat.completions.create(
            model=req.model,
            max_tokens=req.max_tokens,
            messages=req.messages,
        )
        return InferenceResult(
            text=resp.choices[0].message.content or "",
            input_tokens=resp.usage.prompt_tokens,
            output_tokens=resp.usage.completion_tokens,
        )

    async def _call_gemini(self, req: InferenceRequest) -> InferenceResult:
        import google.generativeai as genai

        prompt = "\n".join(m.get("content", "") for m in req.messages)
        model = genai.GenerativeModel(req.model)
        resp = await model.generate_content_async(prompt)
        meta = resp.usage_metadata
        return InferenceResult(
            text=resp.text,
            input_tokens=meta.prompt_token_count if meta else 0,
            output_tokens=meta.candidates_token_count if meta else 0,
        )
