from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from openvegas.payments.service import BillingService
from server.routes import wallet as wallet_routes
from tests.test_billing.test_continuation_service import _FakeTx, _svc
from tests.test_billing.test_billing_service import _DummyWallet, _FakeDB
from tests.test_wallet.test_bootstrap_balance_contract import _FakeDB as _WalletDB, _FakeWallet


@pytest.mark.asyncio
async def test_new_user_bootstrap_then_warning_path(monkeypatch: pytest.MonkeyPatch):
    db = _WalletDB()
    wallet = _FakeWallet()
    monkeypatch.setenv("STARTER_GRANT_V", "150")
    monkeypatch.setenv("V_PER_USD", "100")
    monkeypatch.setenv("TOPUP_LOW_BALANCE_FLOOR_USD", "5")
    monkeypatch.setenv("TOPUP_CRITICAL_BALANCE_FLOOR_V", "90")
    monkeypatch.setattr(wallet_routes, "get_db", lambda: db)
    monkeypatch.setattr(wallet_routes, "get_wallet", lambda: wallet)

    boot = await wallet_routes.wallet_bootstrap(user={"user_id": "u-e2e"})
    bal = await wallet_routes.get_balance(user={"user_id": "u-e2e"})

    assert boot["starter_grant_applied"] is True
    assert bal["starter_grant_received"] is True
    assert bal["balance_state"] == "warning"


@pytest.mark.asyncio
async def test_paid_user_continuation_claim_then_auto_repay_on_next_topup():
    tx = _FakeTx()
    tx.paid_users.add("u1")
    svc = _svc(tx)

    claim = await svc.claim_continuation(user_id="u1", idempotency_key="e2e-claim")
    repaid, net = await svc._apply_continuation_repayment(
        tx=tx,
        user_id="u1",
        gross_v=Decimal("20"),
        source_reference="fiat_topup:e2e-1",
    )

    assert claim["status"] == "granted"
    assert repaid == Decimal("20.000000")
    assert net == Decimal("0.000000")
    assert tx.active_row is not None
    assert Decimal(str(tx.active_row["outstanding_v"])) == Decimal("30.000000")


@pytest.mark.asyncio
async def test_webhook_replay_does_not_duplicate_repayment_or_credit():
    wallet = _DummyWallet()
    svc = BillingService(_FakeDB(), wallet, stripe_gateway=type("_G", (), {"mode": "stripe"})())
    tx = _FakeTx()

    first = await svc._settle_topup_paid(
        tx=tx,
        row={
            "id": "top-paid-1",
            "user_id": "u1",
            "status": "paid",
            "mode": "stripe",
            "expires_at": datetime.now(timezone.utc),
            "v_credit": "10.000000",
        },
        provider_ref="pi_1",
        settlement_surface="stripe",
        provider_paid_at=datetime.now(timezone.utc),
    )
    second = await svc._settle_topup_paid(
        tx=tx,
        row={
            "id": "top-paid-1",
            "user_id": "u1",
            "status": "paid",
            "mode": "stripe",
            "expires_at": datetime.now(timezone.utc),
            "v_credit": "10.000000",
        },
        provider_ref="pi_1",
        settlement_surface="stripe",
        provider_paid_at=datetime.now(timezone.utc),
    )

    assert first["idempotent"] is True
    assert second["idempotent"] is True
    assert wallet.calls == []


@pytest.mark.asyncio
async def test_checkout_preview_staleness_notice_and_settlement_delta_explained():
    tx = _FakeTx()
    tx.active_row = {
        "id": "cont_1",
        "principal_v": Decimal("50"),
        "outstanding_v": Decimal("2500"),
        "status": "active",
        "cooldown_until": datetime.now(timezone.utc) + timedelta(days=7),
    }
    tx.latest_row = tx.active_row.copy()
    svc = _svc(tx)

    preview = await svc.preview_topup_checkout(user_id="u1", amount_usd=Decimal("20"))
    tx.active_row["outstanding_v"] = Decimal("500")
    repaid, net = await svc._apply_continuation_repayment(
        tx=tx,
        user_id="u1",
        gross_v=Decimal("2000"),
        source_reference="fiat_topup:e2e-2",
    )

    payments_html = Path("ui/payments.html").read_text(encoding="utf-8")
    balance_html = Path("ui/balance.html").read_text(encoding="utf-8")

    assert preview["preview_is_estimate"] is True
    assert repaid == Decimal("500.000000")
    assert net == Decimal("1500.000000")
    assert "Final repayment is computed at settlement" in payments_html
    assert "Final repayment is computed at settlement" in balance_html
