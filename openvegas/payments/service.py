"""Billing service for Stripe-backed topups and org sponsorship subscriptions."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from openvegas.telemetry import emit_metric
from openvegas.wallet.ledger import WalletService
from .stripe_gateway import StripeGateway

V_SCALE = Decimal("0.000001")
USD_SCALE = Decimal("0.01")


class BillingError(Exception):
    pass


class IdempotencyConflict(BillingError):
    pass


class NotFoundError(BillingError):
    pass


class BillingService:
    def __init__(self, db: Any, wallet: WalletService, stripe_gateway: Any):
        self.db = db
        self.wallet = wallet
        self.stripe_gateway = stripe_gateway
        self.provider_mode = str(getattr(stripe_gateway, "mode", "stripe"))

    @staticmethod
    def canonical_payload_hash(payload: dict) -> str:
        def norm(v):
            if isinstance(v, Decimal):
                return format(v.normalize(), "f")
            if isinstance(v, dict):
                return {k: norm(v[k]) for k in sorted(v.keys())}
            if isinstance(v, list):
                return [norm(x) for x in v]
            return v

        canonical = json.dumps(norm(payload), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _money(value: Decimal | str | float) -> Decimal:
        return Decimal(str(value)).quantize(V_SCALE)

    @staticmethod
    def _usd(value: Decimal | str | float) -> Decimal:
        return Decimal(str(value)).quantize(USD_SCALE)

    @staticmethod
    def _row_get(row: Any, key: str, default: Any = None) -> Any:
        if row is None:
            return default
        try:
            if key in row:
                return row[key]
        except Exception:
            pass
        if isinstance(row, dict):
            return row.get(key, default)
        return default

    @staticmethod
    def _fmt_usd(value: Decimal | str | float | None) -> str | None:
        if value is None:
            return None
        return format(Decimal(str(value)).quantize(USD_SCALE), "f")

    @staticmethod
    def _fmt_v(value: Decimal | str | float | None) -> str | None:
        if value is None:
            return None
        return format(Decimal(str(value)).quantize(V_SCALE), "f")

    @staticmethod
    def _payment_methods_display() -> list[str]:
        return ["Card", "PayPal", "Apple Pay", "Alipay"]

    @staticmethod
    def _default_topup_usd() -> Decimal:
        return Decimal(os.getenv("TOPUP_SUGGEST_DEFAULT_USD", "20.00")).quantize(USD_SCALE)

    @staticmethod
    def _low_balance_floor_usd() -> Decimal:
        return Decimal(os.getenv("TOPUP_LOW_BALANCE_FLOOR_USD", "5.00")).quantize(USD_SCALE)

    @staticmethod
    def _v_per_usd() -> Decimal:
        return Decimal(os.getenv("V_PER_USD", "100")).quantize(V_SCALE)

    @staticmethod
    def _checkout_ttl_sec() -> int:
        return max(60, int(os.getenv("TOPUP_CHECKOUT_EXPIRY_SEC", "3600")))

    @staticmethod
    def _late_settlement_window_sec() -> int:
        return max(60, int(os.getenv("TOPUP_STRIPE_LATE_SETTLEMENT_WINDOW_SEC", "259200")))

    def _resolve_mode(self) -> str:
        mode = str(self.provider_mode or "stripe").lower().strip()
        return mode if mode in {"stripe", "simulated"} else "stripe"

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _is_pending_status(cls, status: str) -> bool:
        return str(status) in {"created", "checkout_created"}

    @classmethod
    def _is_expired(cls, row: Any, now: datetime | None = None) -> bool:
        status = str(cls._row_get(row, "status", ""))
        if not cls._is_pending_status(status):
            return False
        expires_at = cls._row_get(row, "expires_at")
        if not expires_at:
            return False
        ts = expires_at
        if getattr(ts, "tzinfo", None) is None:
            ts = ts.replace(tzinfo=timezone.utc)
        point = now or cls._utc_now()
        return ts <= point

    async def _mark_expired_if_needed(self, *, tx: Any, row: Any) -> Any:
        if not self._is_expired(row):
            return row
        topup_id = str(self._row_get(row, "id", ""))
        status_before = str(self._row_get(row, "status", ""))
        updated = await tx.fetchrow(
            """
            UPDATE fiat_topups
            SET status = 'expired',
                updated_at = now()
            WHERE id = $1
              AND status IN ('created', 'checkout_created')
            RETURNING *
            """,
            topup_id,
        )
        if updated:
            emit_metric(
                "topup_status_transition_total",
                {"from": status_before, "to": "expired", "mode": str(self._row_get(row, "mode", self._resolve_mode()))},
            )
            return updated
        latest = await tx.fetchrow("SELECT * FROM fiat_topups WHERE id = $1", topup_id)
        return latest or row

    async def _mark_manual_reconciliation_required(
        self,
        *,
        tx: Any,
        topup_id: str,
        mode: str,
        reason: str,
    ) -> None:
        row = await tx.fetchrow(
            """
            UPDATE fiat_topups
            SET status = 'manual_reconciliation_required',
                manual_reconciliation_required = TRUE,
                manual_reconciliation_reason = $2,
                manual_reconciliation_marked_at = now(),
                updated_at = now()
            WHERE id = $1
            RETURNING id
            """,
            topup_id,
            reason[:200],
        )
        if row:
            emit_metric(
                "topup_status_transition_total",
                {"from": "expired", "to": "manual_reconciliation_required", "mode": mode},
            )
            emit_metric("topup_late_settlement_manual_review_total", {"mode": mode})

    @staticmethod
    def _render_qr_svg(value: str) -> bytes:
        # Optional dependency: keep runtime resilient if qrcode is missing.
        try:
            import qrcode  # type: ignore
            import qrcode.image.svg  # type: ignore

            image = qrcode.make(value, image_factory=qrcode.image.svg.SvgPathImage)
            raw = image.to_string()
            if isinstance(raw, bytes):
                return raw
            return str(raw).encode("utf-8")
        except Exception:
            escaped = (
                str(value)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            svg = (
                "<svg xmlns='http://www.w3.org/2000/svg' width='600' height='120'>"
                "<rect width='100%' height='100%' fill='white'/>"
                "<text x='12' y='24' font-family='monospace' font-size='14' fill='black'>"
                "QR unavailable in this runtime; use checkout URL:"
                "</text>"
                f"<text x='12' y='56' font-family='monospace' font-size='13' fill='black'>{escaped}</text>"
                "</svg>"
            )
            return svg.encode("utf-8")

    @staticmethod
    def _provider_paid_at_from_event(event: dict, fallback: datetime) -> datetime:
        created = event.get("created")
        if created is None:
            return fallback
        try:
            return datetime.fromtimestamp(int(created), tz=timezone.utc)
        except Exception:
            return fallback

    @staticmethod
    def compute_has_active_subscription(subscription: dict) -> bool:
        status = str(subscription.get("status", "inactive"))
        status_ok = status in {"active", "trialing"}
        period_end = subscription.get("current_period_end")
        if not period_end:
            return status_ok
        return status_ok and datetime.fromtimestamp(int(period_end), tz=timezone.utc) > datetime.now(timezone.utc)

    async def resolve_org_id_from_subscription(self, subscription: dict, tx: Any) -> str:
        metadata = subscription.get("metadata") or {}
        org_id = metadata.get("org_id")
        if org_id:
            return str(org_id)

        # Fallback for older sessions lacking subscription_data.metadata.
        sub_id = subscription.get("id")
        if sub_id:
            row = await tx.fetchrow(
                "SELECT org_id FROM org_sponsorships WHERE stripe_subscription_id = $1",
                sub_id,
            )
            if row:
                return str(row["org_id"])

        raise BillingError("Missing org_id in subscription metadata")

    async def _ensure_user_customer(self, user_id: str) -> str:
        row = await self.db.fetchrow(
            """
            SELECT stripe_customer_id
            FROM fiat_topups
            WHERE user_id = $1
              AND stripe_customer_id IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 1
            """,
            user_id,
        )
        if row and row["stripe_customer_id"]:
            return str(row["stripe_customer_id"])

        user = await self.db.fetchrow(
            "SELECT email FROM auth.users WHERE id = $1",
            user_id,
        )
        email = str(user["email"]) if user and user.get("email") else None
        customer = self.stripe_gateway.create_customer(
            email=email,
            name=None,
            metadata={"user_id": str(user_id)},
        )
        return str(customer["id"])

    async def create_topup_checkout(self, *, user_id: str, amount_usd: Decimal, idempotency_key: str) -> dict:
        try:
            amount_usd = Decimal(str(amount_usd))
        except InvalidOperation as e:
            raise BillingError("Invalid amount") from e

        min_usd = Decimal(os.getenv("TOPUP_MIN_USD", "1"))
        max_usd = Decimal(os.getenv("TOPUP_MAX_USD", "500"))
        if amount_usd < min_usd or amount_usd > max_usd:
            raise BillingError(f"Amount must be between {min_usd} and {max_usd} USD")

        v_per_usd = Decimal(os.getenv("V_PER_USD", "100"))
        v_credit = (amount_usd * v_per_usd).quantize(V_SCALE)
        payload_hash = self.canonical_payload_hash(
            {"amount_usd": amount_usd, "currency": "usd"}
        )

        mode = self._resolve_mode()
        expires_at = self._utc_now() + timedelta(seconds=self._checkout_ttl_sec())
        resume_existing = False
        async with self.db.transaction() as tx:
            existing = await tx.fetchrow(
                """
                SELECT *
                FROM fiat_topups
                WHERE user_id = $1 AND idempotency_key = $2
                FOR UPDATE
                """,
                user_id,
                idempotency_key,
            )
            if existing:
                if existing["idempotency_payload_hash"] != payload_hash:
                    raise IdempotencyConflict("IDEMPOTENCY_PAYLOAD_CONFLICT")
                existing = await self._mark_expired_if_needed(tx=tx, row=existing)
                status = str(existing["status"])
                if status in {"checkout_created", "paid"} and self._row_get(existing, "stripe_checkout_session_id"):
                    return self._format_topup(existing)
                topup_id = str(existing["id"])
                resume_existing = True
            else:
                topup_id = str(uuid.uuid4())
                await tx.execute(
                    """
                    INSERT INTO fiat_topups
                      (id, user_id, amount_usd, v_credit, status, idempotency_key, idempotency_payload_hash, mode, expires_at)
                    VALUES ($1, $2, $3, $4, 'created', $5, $6, $7, $8)
                    """,
                    topup_id,
                    user_id,
                    amount_usd,
                    v_credit,
                    idempotency_key,
                    payload_hash,
                    mode,
                    expires_at,
                )

        if mode == "simulated":
            customer_id = f"sim_{user_id}"
        else:
            customer_id = await self._ensure_user_customer(user_id)

        try:
            session = self.stripe_gateway.create_topup_checkout(
                customer_id=customer_id,
                amount_usd=amount_usd,
                topup_id=topup_id,
            )
        except Exception as e:
            await self.db.execute(
                """
                UPDATE fiat_topups
                SET status = 'failed', failure_reason = $2, updated_at = now()
                WHERE id = $1 AND status = 'created'
                """,
                topup_id,
                str(e)[:500],
            )
            raise BillingError("Unable to create Stripe Checkout session") from e

        row = await self.db.fetchrow(
            """
            UPDATE fiat_topups
            SET status = 'checkout_created',
                stripe_customer_id = $2,
                stripe_checkout_session_id = $3,
                stripe_checkout_url = $4,
                mode = $5,
                expires_at = $6,
                updated_at = now()
            WHERE id = $1
              AND status IN ('created', 'failed', 'checkout_created')
            RETURNING *
            """,
            topup_id,
            customer_id,
            session["id"],
            session["url"],
            mode,
            expires_at,
        )
        if not row:
            if resume_existing:
                latest = await self.db.fetchrow("SELECT * FROM fiat_topups WHERE id = $1", topup_id)
                if latest:
                    return self._format_topup(latest)
            raise BillingError("Unable to persist checkout session")

        emit_metric("topup_checkout_created_total", {"mode": mode})
        return self._format_topup(row)

    async def _fetch_pending_topup(self, *, tx: Any, user_id: str, mode: str) -> Any | None:
        row = await tx.fetchrow(
            """
            SELECT *
            FROM fiat_topups
            WHERE user_id = $1
              AND mode = $2
              AND status IN ('created', 'checkout_created')
            ORDER BY created_at DESC
            LIMIT 1
            FOR UPDATE
            """,
            user_id,
            mode,
        )
        if not row:
            return None
        updated = await self._mark_expired_if_needed(tx=tx, row=row)
        if self._is_pending_status(str(self._row_get(updated, "status", ""))):
            return updated
        return None

    def _suggest_payload(
        self,
        *,
        low_balance: bool,
        balance_v: Decimal,
        balance_usd_equiv: Decimal,
        floor_usd: Decimal,
        mode: str,
        topup: dict | None,
        suggested_topup_usd: Decimal | None,
    ) -> dict:
        return {
            "low_balance": bool(low_balance),
            "balance_v": self._fmt_v(balance_v),
            "balance_usd_equiv": self._fmt_usd(balance_usd_equiv),
            "low_balance_floor_usd": self._fmt_usd(floor_usd),
            "suggested_topup_usd": self._fmt_usd(suggested_topup_usd) if low_balance else None,
            "topup_id": topup.get("topup_id") if topup else None,
            "status": topup.get("status") if topup else None,
            "mode": str(topup.get("mode")) if topup and topup.get("mode") else mode,
            "checkout_url": topup.get("checkout_url") if topup else None,
            "qr_value": topup.get("qr_value") if topup else None,
            "payment_methods_display": self._payment_methods_display(),
        }

    async def create_topup_suggestion(self, *, user_id: str, suggested_topup_usd: Decimal | None = None) -> dict:
        balance_v = await self.wallet.get_balance(f"user:{user_id}")
        floor_usd = self._low_balance_floor_usd()
        v_per_usd = self._v_per_usd()
        if v_per_usd <= 0:
            raise BillingError("Invalid V_PER_USD configuration")
        balance_usd = (Decimal(str(balance_v)) / v_per_usd).quantize(USD_SCALE)
        mode = self._resolve_mode()
        if balance_usd > floor_usd:
            emit_metric("topup_suggest_suppressed_total", {"reason": "above_floor"})
            return self._suggest_payload(
                low_balance=False,
                balance_v=Decimal(str(balance_v)),
                balance_usd_equiv=balance_usd,
                floor_usd=floor_usd,
                mode=mode,
                topup=None,
                suggested_topup_usd=None,
            )

        topup: dict | None = None
        async with self.db.transaction() as tx:
            pending = await self._fetch_pending_topup(tx=tx, user_id=user_id, mode=mode)
            if pending:
                emit_metric("topup_suggest_suppressed_total", {"reason": "already_pending_topup"})
                topup = self._format_topup(pending)

        if topup is None:
            amount = self._usd(suggested_topup_usd or self._default_topup_usd())
            try:
                topup = await self.create_topup_checkout(
                    user_id=user_id,
                    amount_usd=amount,
                    idempotency_key=f"suggest:{mode}:{uuid.uuid4().hex[:16]}",
                )
                emit_metric("topup_suggest_shown_total", {"mode": mode, "created": "1"})
            except Exception:
                emit_metric("topup_suggest_suppressed_total", {"reason": "provider_unavailable"})
                raise
        else:
            emit_metric("topup_suggest_shown_total", {"mode": mode, "created": "0"})

        return self._suggest_payload(
            low_balance=True,
            balance_v=Decimal(str(balance_v)),
            balance_usd_equiv=balance_usd,
            floor_usd=floor_usd,
            mode=mode,
            topup=topup,
            suggested_topup_usd=self._usd(suggested_topup_usd or self._default_topup_usd()),
        )

    async def get_topup_internal(self, *, topup_id: str) -> dict:
        row = await self.db.fetchrow(
            """
            SELECT *
            FROM fiat_topups
            WHERE id = $1
            """,
            topup_id,
        )
        if not row:
            raise NotFoundError("Top-up not found")
        return self._format_topup(row)

    async def get_topup_status(self, *, user_id: str, topup_id: str) -> dict:
        async with self.db.transaction() as tx:
            row = await tx.fetchrow(
                """
                SELECT *
                FROM fiat_topups
                WHERE id = $1 AND user_id = $2
                FOR UPDATE
                """,
                topup_id,
                user_id,
            )
            if not row:
                raise NotFoundError("Top-up not found")
            row = await self._mark_expired_if_needed(tx=tx, row=row)
            return self._format_topup(row)

    async def get_topup_qr_svg(self, *, user_id: str, topup_id: str) -> bytes:
        status = await self.get_topup_status(user_id=user_id, topup_id=topup_id)
        value = str(status.get("qr_value") or status.get("checkout_url") or "")
        if not value:
            raise BillingError("Checkout unavailable")
        emit_metric("topup_qr_generated_total", {"surface": "ui"})
        return self._render_qr_svg(value)

    async def create_org_subscription_checkout(self, *, org_id: str) -> dict:
        price_id = os.getenv("STRIPE_ORG_PRICE_ID", "").strip()
        if not price_id:
            raise BillingError("STRIPE_ORG_PRICE_ID is not configured")

        row = await self.db.fetchrow(
            """
            SELECT o.name, os.stripe_customer_id
            FROM org_sponsorships os
            JOIN organizations o ON o.id = os.org_id
            WHERE os.org_id = $1
            """,
            org_id,
        )
        if not row:
            raise NotFoundError("Org sponsorship not found")

        customer_id = row["stripe_customer_id"]
        if not customer_id:
            customer = self.stripe_gateway.create_customer(
                email=None,
                name=str(row["name"]),
                metadata={"org_id": str(org_id)},
            )
            customer_id = str(customer["id"])
            await self.db.execute(
                """
                UPDATE org_sponsorships
                SET stripe_customer_id = $2, stripe_price_id = $3, updated_at = now()
                WHERE org_id = $1
                """,
                org_id,
                customer_id,
                price_id,
            )

        checkout_attempt_id = str(uuid.uuid4())
        session = self.stripe_gateway.create_org_subscription_checkout(
            customer_id=str(customer_id),
            price_id=price_id,
            org_id=str(org_id),
            checkout_attempt_id=checkout_attempt_id,
        )
        await self.db.execute(
            """
            UPDATE org_sponsorships
            SET stripe_customer_id = $2,
                stripe_price_id = $3,
                updated_at = now()
            WHERE org_id = $1
            """,
            org_id,
            customer_id,
            price_id,
        )
        return {
            "org_id": str(org_id),
            "checkout_attempt_id": checkout_attempt_id,
            "checkout_session_id": str(session["id"]),
            "checkout_url": str(session["url"]),
        }

    async def get_org_subscription_status(self, *, org_id: str) -> dict:
        row = await self.db.fetchrow(
            """
            SELECT org_id, stripe_customer_id, stripe_subscription_id, stripe_price_id,
                   stripe_subscription_status, has_active_subscription, cancel_at_period_end,
                   current_period_end, updated_at
            FROM org_sponsorships
            WHERE org_id = $1
            """,
            org_id,
        )
        if not row:
            raise NotFoundError("Org sponsorship not found")
        return {
            "org_id": str(row["org_id"]),
            "stripe_customer_id": row["stripe_customer_id"],
            "stripe_subscription_id": row["stripe_subscription_id"],
            "stripe_price_id": row["stripe_price_id"],
            "stripe_subscription_status": row["stripe_subscription_status"] or "inactive",
            "has_active_subscription": bool(row["has_active_subscription"]),
            "cancel_at_period_end": bool(row["cancel_at_period_end"]),
            "current_period_end": row["current_period_end"].isoformat() if row["current_period_end"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    async def create_org_billing_portal(self, *, org_id: str, flow_type: str | None = None) -> dict:
        row = await self.db.fetchrow(
            """
            SELECT stripe_customer_id, stripe_subscription_id
            FROM org_sponsorships
            WHERE org_id = $1
            """,
            org_id,
        )
        if not row or not row["stripe_customer_id"]:
            raise BillingError("Org has no Stripe customer configured")

        url = self.stripe_gateway.create_billing_portal(
            customer_id=str(row["stripe_customer_id"]),
            flow_type=flow_type,
            subscription_id=str(row["stripe_subscription_id"]) if row["stripe_subscription_id"] else None,
        )
        return {"url": url}

    async def handle_webhook(self, *, raw_body: bytes, signature: str) -> dict:
        event = self.stripe_gateway.construct_event(raw_body, signature)
        return await self.handle_event(event)

    async def handle_event(self, event: dict) -> dict:
        event_id = str(event["id"])
        event_type = str(event["type"])
        payload_hash = hashlib.sha256(
            json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        obj = event["data"]["object"]

        async with self.db.transaction() as tx:
            existing = await tx.fetchrow(
                "SELECT payload_hash FROM stripe_webhook_events WHERE event_id = $1",
                event_id,
            )
            if existing:
                if existing["payload_hash"] != payload_hash:
                    raise BillingError(f"Webhook payload hash mismatch for event {event_id}")
                return {"status": "duplicate"}

            await tx.execute(
                """
                INSERT INTO stripe_webhook_events(event_id, event_type, payload_hash)
                VALUES ($1, $2, $3)
                """,
                event_id,
                event_type,
                payload_hash,
            )

            if event_type == "checkout.session.completed":
                return await self._handle_checkout_completed(
                    tx=tx,
                    session=obj,
                    event_created=self._provider_paid_at_from_event(event, fallback=self._utc_now()),
                )
            if event_type in {
                "customer.subscription.created",
                "customer.subscription.updated",
                "customer.subscription.deleted",
            }:
                return await self._handle_subscription_upsert(tx=tx, subscription=obj)
            if event_type == "invoice.paid":
                return await self._apply_org_budget_credit_once(tx=tx, invoice=obj)
            if event_type == "invoice.payment_failed":
                return await self._mark_org_subscription_past_due(tx=tx, invoice=obj)
            return {"status": "ignored"}

    async def _handle_checkout_completed(self, *, tx: Any, session: dict, event_created: datetime | None = None) -> dict:
        if session.get("mode") == "payment":
            return await self._settle_topup_from_checkout(tx=tx, session=session, provider_paid_at=event_created)
        # Subscription-mode checkout doesn't settle wallet value in this phase.
        return {"status": "ignored"}

    async def _settle_topup_from_checkout(self, *, tx: Any, session: dict, provider_paid_at: datetime | None = None) -> dict:
        if session.get("payment_status") != "paid":
            return {"status": "not-paid"}

        session_id = str(session["id"])
        row = await tx.fetchrow(
            """
            SELECT *
            FROM fiat_topups
            WHERE stripe_checkout_session_id = $1
            FOR UPDATE
            """,
            session_id,
        )
        if not row:
            return {"status": "already-settled-or-missing"}
        row = await self._mark_expired_if_needed(tx=tx, row=row)
        return await self._settle_topup_paid(
            tx=tx,
            row=row,
            provider_ref=session.get("payment_intent"),
            settlement_surface="stripe",
            provider_paid_at=provider_paid_at or self._utc_now(),
        )

    async def complete_fake_topup(self, *, topup_id: str) -> dict:
        async with self.db.transaction() as tx:
            row = await tx.fetchrow(
                """
                SELECT *
                FROM fiat_topups
                WHERE id = $1
                FOR UPDATE
                """,
                topup_id,
            )
            if not row:
                raise NotFoundError("Top-up not found")
            row = await self._mark_expired_if_needed(tx=tx, row=row)
            return await self._settle_topup_paid(
                tx=tx,
                row=row,
                provider_ref=f"fake:{topup_id}",
                settlement_surface="simulated",
                provider_paid_at=self._utc_now(),
            )

    async def _settle_topup_paid(
        self,
        *,
        tx: Any,
        row: Any,
        provider_ref: str | None,
        settlement_surface: str,
        provider_paid_at: datetime,
    ) -> dict:
        topup_id = str(self._row_get(row, "id", ""))
        user_id = str(self._row_get(row, "user_id", ""))
        status_before = str(self._row_get(row, "status", ""))
        mode = str(self._row_get(row, "mode", self._resolve_mode()))

        if status_before == "paid":
            emit_metric("topup_settlement_idempotent_replay_total", {"mode": mode})
            return {"status": "paid", "topup_id": topup_id, "idempotent": True}
        if status_before == "manual_reconciliation_required":
            return {
                "status": "manual_reconciliation_required",
                "topup_id": topup_id,
                "idempotent": True,
            }
        if status_before == "expired":
            if mode == "simulated":
                raise BillingError("SIMULATED_TOPUP_EXPIRED_CANNOT_SETTLE")
            if settlement_surface != "stripe":
                raise BillingError("Only Stripe provider settlement can reconcile expired top-ups")
            expires_at = self._row_get(row, "expires_at")
            cutoff = provider_paid_at
            if expires_at is not None:
                ts = expires_at
                if getattr(ts, "tzinfo", None) is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                cutoff = ts + timedelta(seconds=self._late_settlement_window_sec())
            if provider_paid_at > cutoff:
                await self._mark_manual_reconciliation_required(
                    tx=tx,
                    topup_id=topup_id,
                    mode=mode,
                    reason="STRIPE_LATE_SETTLEMENT_WINDOW_EXCEEDED",
                )
                raise BillingError("STRIPE_LATE_SETTLEMENT_REQUIRES_MANUAL_REVIEW")
        if status_before not in {"created", "checkout_created", "expired"}:
            raise BillingError(f"TOPUP_STATUS_NOT_SETTLEABLE:{status_before}")

        if provider_ref:
            conflict = await tx.fetchrow(
                """
                SELECT id
                FROM fiat_topups
                WHERE stripe_payment_intent_id = $1
                  AND id <> $2
                LIMIT 1
                """,
                str(provider_ref),
                topup_id,
            )
            if conflict:
                raise BillingError("PROVIDER_REFERENCE_CONFLICT")

        updated = await tx.fetchrow(
            """
            UPDATE fiat_topups
            SET status = 'paid',
                stripe_payment_intent_id = COALESCE($2, stripe_payment_intent_id),
                manual_reconciliation_required = FALSE,
                manual_reconciliation_reason = NULL,
                manual_reconciliation_marked_at = NULL,
                updated_at = now()
            WHERE id = $1
            RETURNING id, user_id, v_credit, status
            """,
            topup_id,
            str(provider_ref) if provider_ref else None,
        )
        if not updated:
            raise BillingError("Unable to settle top-up")

        await self.wallet.fund_from_card(
            account_id=f"user:{user_id}",
            amount_v=Decimal(str(self._row_get(updated, "v_credit", "0"))),
            reference_id=f"fiat_topup:{topup_id}",
            tx=tx,
        )
        emit_metric("topup_status_transition_total", {"from": status_before, "to": "paid", "mode": mode})
        emit_metric("topup_webhook_settled_total", {"mode": mode, "status": "paid"})
        return {"status": "paid", "topup_id": topup_id, "idempotent": False}

    async def _handle_subscription_upsert(self, *, tx: Any, subscription: dict) -> dict:
        org_id = await self.resolve_org_id_from_subscription(subscription, tx=tx)
        await self.sync_org_sponsorship_from_subscription(
            tx=tx,
            org_id=org_id,
            subscription=subscription,
        )
        return {"status": "synced", "org_id": org_id}

    async def sync_org_sponsorship_from_subscription(
        self,
        *,
        tx: Any,
        org_id: str,
        subscription: dict,
    ) -> None:
        items = (subscription.get("items") or {}).get("data") or []
        item0 = items[0] if items else {}
        price = item0.get("price") if isinstance(item0, dict) else {}
        price_id = price.get("id") if isinstance(price, dict) else None
        period_end = subscription.get("current_period_end")

        row = await tx.fetchrow(
            """
            UPDATE org_sponsorships
            SET stripe_subscription_id = $2,
                stripe_customer_id = COALESCE($3, stripe_customer_id),
                stripe_subscription_status = $4,
                has_active_subscription = $5,
                stripe_price_id = COALESCE($6, stripe_price_id),
                cancel_at_period_end = $7,
                current_period_end = CASE WHEN $8::bigint IS NULL THEN NULL ELSE to_timestamp($8::bigint) END,
                updated_at = now()
            WHERE org_id = $1
            RETURNING org_id
            """,
            org_id,
            subscription.get("id"),
            subscription.get("customer"),
            subscription.get("status", "inactive"),
            self.compute_has_active_subscription(subscription),
            price_id,
            bool(subscription.get("cancel_at_period_end", False)),
            int(period_end) if period_end else None,
        )
        if not row:
            raise NotFoundError("Org sponsorship not found for subscription sync")

    async def _apply_org_budget_credit_once(self, *, tx: Any, invoice: dict) -> dict:
        subscription_id = invoice.get("subscription")
        invoice_id = invoice.get("id")
        if not subscription_id or not invoice_id:
            return {"status": "ignored"}

        org = await tx.fetchrow(
            "SELECT org_id FROM org_sponsorships WHERE stripe_subscription_id = $1",
            subscription_id,
        )
        if not org:
            return {"status": "org-not-found"}

        amount_paid = (Decimal(str(invoice.get("amount_paid", 0))) / Decimal("100")).quantize(
            Decimal("0.0001")
        )
        await tx.execute(
            """
            INSERT INTO org_budget_ledger (org_id, source, delta_usd, reference_id)
            VALUES ($1, 'stripe_subscription', $2, $3)
            ON CONFLICT DO NOTHING
            """,
            org["org_id"],
            amount_paid,
            f"stripe_invoice:{invoice_id}",
        )
        return {"status": "credited"}

    async def _mark_org_subscription_past_due(self, *, tx: Any, invoice: dict) -> dict:
        subscription_id = invoice.get("subscription")
        if not subscription_id:
            return {"status": "ignored"}
        await tx.execute(
            """
            UPDATE org_sponsorships
            SET stripe_subscription_status = 'past_due',
                has_active_subscription = FALSE,
                updated_at = now()
            WHERE stripe_subscription_id = $1
            """,
            subscription_id,
        )
        return {"status": "past_due"}

    @staticmethod
    def _format_topup(row: Any) -> dict:
        checkout_url = BillingService._row_get(row, "stripe_checkout_url")
        mode = str(BillingService._row_get(row, "mode", "stripe"))
        status = str(BillingService._row_get(row, "status", "created"))
        return {
            "topup_id": str(BillingService._row_get(row, "id", "")),
            "status": status,
            "mode": mode,
            "amount_usd": BillingService._fmt_usd(BillingService._row_get(row, "amount_usd")),
            "v_credit": BillingService._fmt_v(BillingService._row_get(row, "v_credit")),
            "checkout_session_id": BillingService._row_get(row, "stripe_checkout_session_id"),
            "checkout_url": checkout_url,
            "qr_value": checkout_url,
            "payment_intent_id": BillingService._row_get(row, "stripe_payment_intent_id"),
            "failure_reason": BillingService._row_get(row, "failure_reason"),
            "expires_at": (
                BillingService._row_get(row, "expires_at").isoformat()
                if BillingService._row_get(row, "expires_at")
                else None
            ),
            "manual_reconciliation_required": bool(
                BillingService._row_get(row, "manual_reconciliation_required", False)
                or status == "manual_reconciliation_required"
            ),
            "manual_reconciliation_reason": BillingService._row_get(row, "manual_reconciliation_reason"),
            "updated_at": (
                BillingService._row_get(row, "updated_at").isoformat()
                if BillingService._row_get(row, "updated_at")
                else None
            ),
        }
