from __future__ import annotations

import types
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from openvegas.payments.service import BillingError, BillingService
from openvegas.payments.stripe_gateway import StripeGateway


class _DummyWallet:
    def __init__(self, balance: Decimal = Decimal("0")):
        self.calls = []
        self._balance = Decimal(str(balance))

    async def fund_from_card(self, *, account_id, amount_v, reference_id, tx=None):
        self.calls.append((account_id, amount_v, reference_id, tx))

    async def get_balance(self, account_id: str) -> Decimal:
        _ = account_id
        return self._balance


class _TxCtx:
    def __init__(self, tx):
        self.tx = tx

    async def __aenter__(self):
        return self.tx

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeDB:
    def __init__(self, tx=None):
        self.tx = tx or _FakeTx()

    def transaction(self):
        return _TxCtx(self.tx)

    async def fetchrow(self, query: str, *args):
        return await self.tx.fetchrow(query, *args)

    async def execute(self, query: str, *args):
        return await self.tx.execute(query, *args)


class _FakeTx:
    def __init__(self):
        self.fetchrow_calls = []
        self.execute_calls = []
        self.mode = {}

    async def fetchrow(self, query: str, *args):
        self.fetchrow_calls.append((query, args))
        if "SELECT payload_hash FROM stripe_webhook_events" in query:
            return self.mode.get("existing_event")
        if "SELECT *" in query and "WHERE stripe_checkout_session_id" in query:
            return self.mode.get("checkout_row")
        if "WHERE user_id = $1" in query and "status IN ('created', 'checkout_created')" in query:
            return self.mode.get("pending_row")
        if "UPDATE fiat_topups" in query and "RETURNING id, user_id, v_credit, status" in query:
            return self.mode.get("paid_update_row")
        if "SELECT org_id FROM org_sponsorships WHERE stripe_subscription_id" in query:
            return self.mode.get("org_from_subscription")
        if "SELECT id" in query and "WHERE stripe_payment_intent_id" in query:
            return self.mode.get("provider_conflict_row")
        return None

    async def execute(self, query: str, *args):
        self.execute_calls.append((query, args))
        return "OK"


def _svc(db=None, wallet=None, gateway=None):
    return BillingService(
        db or _FakeDB(),
        wallet or _DummyWallet(),
        stripe_gateway=gateway or types.SimpleNamespace(mode="stripe"),
    )


def test_canonical_payload_hash_normalizes_decimal_and_key_order():
    a = {"amount_usd": Decimal("10.00"), "currency": "usd"}
    b = {"currency": "usd", "amount_usd": Decimal("10")}
    assert BillingService.canonical_payload_hash(a) == BillingService.canonical_payload_hash(b)


def test_compute_has_active_subscription_with_period_end():
    future = int((datetime.now(timezone.utc) + timedelta(days=1)).timestamp())
    past = int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp())
    assert BillingService.compute_has_active_subscription({"status": "active", "current_period_end": future})
    assert not BillingService.compute_has_active_subscription({"status": "active", "current_period_end": past})
    assert not BillingService.compute_has_active_subscription({"status": "past_due", "current_period_end": future})


@pytest.mark.asyncio
async def test_resolve_org_id_prefers_subscription_metadata():
    svc = _svc()
    tx = _FakeTx()
    org_id = await svc.resolve_org_id_from_subscription(
        {"id": "sub_1", "metadata": {"org_id": "org_123"}},
        tx=tx,
    )
    assert org_id == "org_123"
    assert not tx.fetchrow_calls


@pytest.mark.asyncio
async def test_resolve_org_id_fallbacks_to_subscription_lookup():
    tx = _FakeTx()
    tx.mode["org_from_subscription"] = {"org_id": "org_fallback"}
    svc = _svc()
    org_id = await svc.resolve_org_id_from_subscription(
        {"id": "sub_2", "metadata": {}},
        tx=tx,
    )
    assert org_id == "org_fallback"


@pytest.mark.asyncio
async def test_handle_event_rejects_payload_hash_mismatch():
    tx = _FakeTx()
    tx.mode["existing_event"] = {"payload_hash": "different"}
    svc = _svc(db=_FakeDB(tx))

    event = {"id": "evt_1", "type": "checkout.session.completed", "data": {"object": {"id": "cs_1"}}}
    with pytest.raises(BillingError):
        await svc.handle_event(event)


@pytest.mark.asyncio
async def test_settle_topup_requires_paid_status():
    wallet = _DummyWallet()
    svc = _svc(wallet=wallet)
    tx = _FakeTx()
    res = await svc._settle_topup_from_checkout(
        tx=tx,
        session={"id": "cs_123", "payment_status": "unpaid"},
    )
    assert res["status"] == "not-paid"
    assert wallet.calls == []


@pytest.mark.asyncio
async def test_settle_topup_paid_credits_wallet():
    wallet = _DummyWallet()
    svc = _svc(wallet=wallet)
    tx = _FakeTx()
    tx.mode["checkout_row"] = {
        "id": "top_1",
        "user_id": "u1",
        "v_credit": "12.500000",
        "status": "checkout_created",
        "mode": "stripe",
        "expires_at": None,
    }
    tx.mode["paid_update_row"] = {"id": "top_1", "user_id": "u1", "v_credit": "12.500000", "status": "paid"}

    res = await svc._settle_topup_from_checkout(
        tx=tx,
        session={"id": "cs_paid", "payment_status": "paid", "payment_intent": "pi_1"},
    )
    assert res["status"] == "paid"
    assert wallet.calls[0][0] == "user:u1"
    assert wallet.calls[0][1] == Decimal("12.500000")
    assert wallet.calls[0][2] == "fiat_topup:top_1"


@pytest.mark.asyncio
async def test_settle_expired_simulated_topup_rejected():
    svc = _svc()
    tx = _FakeTx()
    with pytest.raises(BillingError, match="SIMULATED_TOPUP_EXPIRED_CANNOT_SETTLE"):
        await svc._settle_topup_paid(
            tx=tx,
            row={
                "id": "top_sim_exp",
                "user_id": "u1",
                "status": "expired",
                "mode": "simulated",
                "expires_at": datetime.now(timezone.utc) - timedelta(hours=1),
                "v_credit": "10.000000",
            },
            provider_ref="fake:top_sim_exp",
            settlement_surface="simulated",
            provider_paid_at=datetime.now(timezone.utc),
        )


@pytest.mark.asyncio
async def test_suggest_above_floor_returns_low_balance_false(monkeypatch):
    monkeypatch.setenv("V_PER_USD", "100")
    monkeypatch.setenv("TOPUP_LOW_BALANCE_FLOOR_USD", "5.00")
    wallet = _DummyWallet(balance=Decimal("900.000000"))
    svc = _svc(wallet=wallet)
    out = await svc.create_topup_suggestion(user_id="u1")
    assert out["low_balance"] is False
    assert out["topup_id"] is None
    assert out["checkout_url"] is None


@pytest.mark.asyncio
async def test_suggest_low_balance_reuses_existing_pending_topup(monkeypatch):
    monkeypatch.setenv("V_PER_USD", "100")
    monkeypatch.setenv("TOPUP_LOW_BALANCE_FLOOR_USD", "5.00")
    wallet = _DummyWallet(balance=Decimal("200.000000"))
    tx = _FakeTx()
    tx.mode["pending_row"] = {
        "id": "top_pending",
        "user_id": "u1",
        "amount_usd": "20.00",
        "v_credit": "2000.000000",
        "status": "checkout_created",
        "mode": "simulated",
        "stripe_checkout_session_id": "fake_cs_1",
        "stripe_checkout_url": "https://checkout.openvegas.local/topup/top_pending",
        "stripe_payment_intent_id": None,
        "updated_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=30),
    }

    svc = _svc(db=_FakeDB(tx=tx), wallet=wallet, gateway=types.SimpleNamespace(mode="simulated"))
    out = await svc.create_topup_suggestion(user_id="u1")
    assert out["low_balance"] is True
    assert out["topup_id"] == "top_pending"
    assert out["checkout_url"] == "https://checkout.openvegas.local/topup/top_pending"


def test_stripe_gateway_falls_back_to_options_idempotency(monkeypatch):
    class _FakeSessionAPI:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            if "idempotency_key" in kwargs:
                raise TypeError("unexpected keyword")
            self.kwargs = kwargs
            return {"id": "cs_1", "url": "https://checkout", "payment_intent": "pi_1"}

    session_api = _FakeSessionAPI()
    fake_stripe = types.SimpleNamespace(
        api_key="",
        checkout=types.SimpleNamespace(Session=session_api),
        Customer=types.SimpleNamespace(create=lambda **kwargs: {"id": "cus_1"}),
        billing_portal=types.SimpleNamespace(Session=types.SimpleNamespace(create=lambda **kwargs: {"url": "https://portal"})),
        Webhook=types.SimpleNamespace(construct_event=lambda **kwargs: {"id": "evt"}),
    )
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setenv("CHECKOUT_SUCCESS_URL", "http://localhost/success")
    monkeypatch.setenv("CHECKOUT_CANCEL_URL", "http://localhost/cancel")

    gw = StripeGateway(stripe_mod=fake_stripe)
    out = gw.create_topup_checkout(
        customer_id="cus_1",
        amount_usd=Decimal("5"),
        topup_id="topup_1",
    )
    assert out["id"] == "cs_1"
    assert session_api.kwargs["options"]["idempotency_key"] == "topup-checkout:topup_1"
    assert session_api.kwargs["client_reference_id"] == "topup_1"
