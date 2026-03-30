from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4
import inspect
from typing import get_type_hints

from fastapi.testclient import TestClient
import pytest

from openvegas.payments.service import BillingService
from server.main import app
from server.middleware import auth as auth_middleware
from server.routes import payments as payment_routes


def _override_user():
    return {"user_id": "85add5d1-aaad-4caa-8422-8cd41ff400f7", "role": "authenticated"}


@dataclass
class _Topup:
    topup_id: str
    user_id: str
    status: str
    mode: str
    amount_usd: str
    v_credit: str
    checkout_url: str | None
    qr_value: str | None
    expires_at: datetime


class _FakeBillingService:
    def __init__(self):
        self.topups: dict[str, _Topup] = {}
        self.wallet_credit_calls = 0
        self.force_above_floor = False

    def _make_topup(self, *, user_id: str) -> _Topup:
        topup_id = str(uuid4())
        checkout = f"https://checkout.openvegas.local/topup/{topup_id}"
        topup = _Topup(
            topup_id=topup_id,
            user_id=user_id,
            status="checkout_created",
            mode="simulated",
            amount_usd="20.00",
            v_credit="2000.000000",
            checkout_url=checkout,
            qr_value=checkout,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        self.topups[topup_id] = topup
        return topup

    def _format(self, t: _Topup) -> dict[str, Any]:
        return {
            "topup_id": t.topup_id,
            "status": t.status,
            "mode": t.mode,
            "amount_usd": t.amount_usd,
            "v_credit": t.v_credit,
            "checkout_url": t.checkout_url,
            "qr_value": t.qr_value,
            "failure_reason": None,
        }

    async def create_topup_suggestion(
        self,
        *,
        user_id: str,
        suggested_topup_usd: Decimal | None = None,
    ) -> dict:
        if self.force_above_floor:
            return {
                "low_balance": False,
                "balance_v": "900.000000",
                "balance_usd_equiv": "9.00",
                "low_balance_floor_usd": "5.00",
                "suggested_topup_usd": None,
                "topup_id": None,
                "status": None,
                "mode": "simulated",
                "checkout_url": None,
                "qr_value": None,
                "payment_methods_display": ["Card", "PayPal", "Apple Pay", "Alipay"],
            }
        _ = suggested_topup_usd
        now = datetime.now(timezone.utc)
        for existing in self.topups.values():
            if (
                existing.user_id == user_id
                and existing.mode == "simulated"
                and existing.status in {"created", "checkout_created"}
                and existing.expires_at > now
            ):
                return {
                    "low_balance": True,
                    "balance_v": "200.000000",
                    "balance_usd_equiv": "2.00",
                    "low_balance_floor_usd": "5.00",
                    "suggested_topup_usd": "20.00",
                    "topup_id": existing.topup_id,
                    "status": existing.status,
                    "mode": existing.mode,
                    "checkout_url": existing.checkout_url,
                    "qr_value": existing.qr_value,
                    "payment_methods_display": ["Card", "PayPal", "Apple Pay", "Alipay"],
                }

        t = self._make_topup(user_id=user_id)
        return {
            "low_balance": True,
            "balance_v": "200.000000",
            "balance_usd_equiv": "2.00",
            "low_balance_floor_usd": "5.00",
            "suggested_topup_usd": "20.00",
            "topup_id": t.topup_id,
            "status": t.status,
            "mode": t.mode,
            "checkout_url": t.checkout_url,
            "qr_value": t.qr_value,
            "payment_methods_display": ["Card", "PayPal", "Apple Pay", "Alipay"],
        }

    async def get_topup_status(self, *, user_id: str, topup_id: str) -> dict[str, Any]:
        t = self.topups.get(topup_id)
        if not t or t.user_id != user_id:
            raise payment_routes.NotFoundError("Top-up not found")
        now = datetime.now(timezone.utc)
        if t.status in {"created", "checkout_created"} and t.expires_at <= now:
            t.status = "expired"
        return self._format(t)

    async def get_topup_qr_svg(self, *, user_id: str, topup_id: str) -> bytes:
        t = self.topups.get(topup_id)
        if not t or t.user_id != user_id:
            raise payment_routes.NotFoundError("Top-up not found")
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100'>"
            "<rect width='100' height='100' fill='white'/>"
            f"<text x='4' y='14'>{t.qr_value}</text>"
            "</svg>"
        )
        return svg.encode("utf-8")

    async def get_topup_internal(self, *, topup_id: str) -> dict:
        t = self.topups.get(topup_id)
        if not t:
            raise payment_routes.NotFoundError("Top-up not found")
        return self._format(t)

    async def list_topup_history(self, *, user_id: str, limit: int = 50) -> dict:
        rows = [
            t for t in self.topups.values()
            if t.user_id == user_id
        ]
        rows.sort(key=lambda x: x.expires_at, reverse=True)
        rows = rows[: max(1, min(int(limit), 200))]
        return {
            "entries": [
                {
                    "topup_id": t.topup_id,
                    "time": t.expires_at.isoformat(),
                    "type": "top_up",
                    "amount_usd": t.amount_usd,
                    "amount_v": t.v_credit,
                    "amount_v_2dp": "2000.00",
                    "status": t.status,
                    "mode": t.mode,
                }
                for t in rows
            ],
            "conversion": {"v_per_usd": "100.000000", "usd_per_v": "0.01"},
        }

    async def complete_fake_topup(self, *, topup_id: str) -> dict:
        t = self.topups.get(topup_id)
        if not t:
            raise payment_routes.NotFoundError("Top-up not found")
        if t.status == "paid":
            return {"status": "paid", "topup_id": topup_id, "idempotent": True}
        if t.status == "expired":
            raise payment_routes.BillingError("SIMULATED_TOPUP_EXPIRED_CANNOT_SETTLE")
        t.status = "paid"
        self.wallet_credit_calls += 1
        return {"status": "paid", "topup_id": topup_id, "idempotent": False}


def test_topup_suggestion_workflow_e2e(monkeypatch):
    fake = _FakeBillingService()
    monkeypatch.setattr(payment_routes, "get_billing_service", lambda: fake)
    app.dependency_overrides[auth_middleware.get_current_user] = _override_user
    monkeypatch.setenv("OPENVEGAS_BILLING_FAKE_WEBHOOK_ENABLED", "1")
    monkeypatch.setenv("OPENVEGAS_BILLING_PROVIDER", "simulated")
    try:
        client = TestClient(app)

        suggest = client.post("/billing/topups/suggest", json={"suggested_topup_usd": "20.00"})
        assert suggest.status_code == 200
        payload = suggest.json()
        assert payload["low_balance"] is True
        topup_id = payload["topup_id"]
        assert topup_id

        status = client.get(f"/billing/topups/{topup_id}")
        assert status.status_code == 200
        assert status.json()["topup_id"] == topup_id

        qr = client.get(f"/billing/topups/{topup_id}/qr.svg")
        assert qr.status_code == 200
        assert qr.headers.get("cache-control") == "private, no-store"
        assert "<svg" in qr.text
        assert f"/topup/{topup_id}" in qr.text

        # Pending top-up is reused.
        suggest_reuse = client.post("/billing/topups/suggest", json={"suggested_topup_usd": "20.00"})
        assert suggest_reuse.status_code == 200
        assert suggest_reuse.json()["topup_id"] == topup_id

        settle = client.post("/billing/webhook/fake/complete", json={"topup_id": topup_id})
        assert settle.status_code == 200
        assert settle.json()["status"] == "paid"
        assert fake.wallet_credit_calls == 1

        # Replay is idempotent and does not double-credit.
        settle_replay = client.post("/billing/webhook/fake/complete", json={"topup_id": topup_id})
        assert settle_replay.status_code == 200
        assert settle_replay.json()["idempotent"] is True
        assert fake.wallet_credit_calls == 1

        # Expired pending top-up is not reused.
        old = fake._make_topup(user_id=_override_user()["user_id"])
        old.status = "checkout_created"
        old.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        suggest_after_expire = client.post("/billing/topups/suggest", json={"suggested_topup_usd": "20.00"})
        assert suggest_after_expire.status_code == 200
        assert suggest_after_expire.json()["topup_id"] != old.topup_id

        # Fake completion rejects expired simulated top-up.
        expired = fake._make_topup(user_id=_override_user()["user_id"])
        expired.status = "expired"
        settle_expired = client.post("/billing/webhook/fake/complete", json={"topup_id": expired.topup_id})
        assert settle_expired.status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_topup_status_and_qr_require_owner(monkeypatch):
    fake = _FakeBillingService()
    monkeypatch.setattr(payment_routes, "get_billing_service", lambda: fake)

    owner = {"user_id": "owner-user", "role": "authenticated"}
    other = {"user_id": "other-user", "role": "authenticated"}
    active_user = {"user": owner}

    def _current_user():
        return active_user["user"]

    app.dependency_overrides[auth_middleware.get_current_user] = _current_user
    try:
        top = fake._make_topup(user_id=owner["user_id"])
        client = TestClient(app)

        ok_status = client.get(f"/billing/topups/{top.topup_id}")
        assert ok_status.status_code == 200
        ok_qr = client.get(f"/billing/topups/{top.topup_id}/qr.svg")
        assert ok_qr.status_code == 200

        active_user["user"] = other
        denied_status = client.get(f"/billing/topups/{top.topup_id}")
        assert denied_status.status_code == 404
        denied_qr = client.get(f"/billing/topups/{top.topup_id}/qr.svg")
        assert denied_qr.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_topup_suggest_above_floor_returns_noop_shape_and_creates_no_row(monkeypatch):
    fake = _FakeBillingService()
    fake.force_above_floor = True
    monkeypatch.setattr(payment_routes, "get_billing_service", lambda: fake)
    app.dependency_overrides[auth_middleware.get_current_user] = _override_user
    try:
        client = TestClient(app)
        out = client.post("/billing/topups/suggest", json={"suggested_topup_usd": "20.00"})
        assert out.status_code == 200
        payload = out.json()
        assert payload["low_balance"] is False
        assert payload["topup_id"] is None
        assert payload["checkout_url"] is None
        assert payload["qr_value"] is None
        assert len(fake.topups) == 0
    finally:
        app.dependency_overrides.clear()


def test_topup_history_list_shape_and_owner_scope(monkeypatch):
    fake = _FakeBillingService()
    monkeypatch.setattr(payment_routes, "get_billing_service", lambda: fake)

    owner = {"user_id": "owner-user", "role": "authenticated"}
    active_user = {"user": owner}

    def _current_user():
        return active_user["user"]

    app.dependency_overrides[auth_middleware.get_current_user] = _current_user
    try:
        fake._make_topup(user_id=owner["user_id"])
        fake._make_topup(user_id="other-user")
        client = TestClient(app)
        out = client.get("/billing/topups?limit=50")
        assert out.status_code == 200
        payload = out.json()
        assert "entries" in payload
        assert "conversion" in payload
        assert payload["conversion"]["v_per_usd"] == "100.000000"
        assert len(payload["entries"]) == 1
        assert payload["entries"][0]["type"] == "top_up"
        assert payload["entries"][0]["amount_usd"] == "20.00"
        assert payload["entries"][0]["amount_v_2dp"] == "2000.00"
    finally:
        app.dependency_overrides.clear()


def test_fake_service_signatures_match_production_contract():
    assert inspect.signature(_FakeBillingService.create_topup_suggestion) == inspect.signature(
        BillingService.create_topup_suggestion
    )
    assert inspect.signature(_FakeBillingService.get_topup_internal) == inspect.signature(
        BillingService.get_topup_internal
    )
    assert inspect.signature(_FakeBillingService.complete_fake_topup) == inspect.signature(
        BillingService.complete_fake_topup
    )
    assert inspect.signature(_FakeBillingService.list_topup_history) == inspect.signature(
        BillingService.list_topup_history
    )


@pytest.mark.asyncio
async def test_fake_service_get_topup_internal_return_shape_matches_production():
    fake = _FakeBillingService()
    top = fake._make_topup(user_id="user-shape")
    fake_obj = await fake.get_topup_internal(topup_id=top.topup_id)
    assert isinstance(fake_obj, dict)
    assert "mode" in fake_obj

    prod_hints = get_type_hints(BillingService.get_topup_internal)
    assert prod_hints.get("return") is dict
