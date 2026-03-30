from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from server.routes import wallet as wallet_routes


class _TxCtx:
    def __init__(self, db: "_FakeDB"):
        self.db = db

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, query: str, *args):
        q = " ".join(query.split())
        self.db.execute_calls.append((q, args))
        if "INSERT INTO user_starter_grants" in q:
            user_id = str(args[0])
            self.db.starter_grants[user_id] = {
                "granted_amount_v": Decimal(str(args[1])),
                "grant_version": str(args[2]),
            }
        return "OK"

    async def fetchrow(self, query: str, *args):
        q = " ".join(query.split())
        if "FROM user_starter_grants" in q:
            user_id = str(args[0])
            row = self.db.starter_grants.get(user_id)
            if not row:
                return None
            return {"user_id": user_id, **row}
        return await self.db.fetchrow(query, *args)


class _FakeDB:
    def __init__(self):
        self.starter_grants: dict[str, dict[str, object]] = {}
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []

    def transaction(self):
        return _TxCtx(self)

    async def fetchrow(self, query: str, *args):
        q = " ".join(query.split())
        if "FROM user_subscriptions" in q:
            return {"has_personal": False}
        if "FROM org_members m" in q:
            return {"has_team": False}
        if "FROM user_starter_grants" in q:
            user_id = str(args[0])
            row = self.starter_grants.get(user_id)
            if not row:
                return None
            return {"user_id": user_id, **row}
        return None


class _FakeWallet:
    def __init__(self):
        self.balances: dict[str, Decimal] = {}
        self.fund_calls: list[tuple[str, Decimal, str, str]] = []

    async def get_balance(self, account_id: str) -> Decimal:
        return self.balances.get(account_id, Decimal("0"))

    async def fund_from_card(
        self,
        *,
        account_id: str,
        amount_v: Decimal,
        reference_id: str,
        entry_type: str = "fiat_topup",
        debit_account: str = "fiat_reserve",
        tx=None,
    ):
        _ = (debit_account, tx)
        self.fund_calls.append((account_id, Decimal(str(amount_v)), reference_id, entry_type))
        self.balances[account_id] = self.balances.get(account_id, Decimal("0")) + Decimal(str(amount_v))


@pytest.mark.asyncio
async def test_bootstrap_grant_idempotent_once(monkeypatch: pytest.MonkeyPatch):
    db = _FakeDB()
    wallet = _FakeWallet()
    monkeypatch.setenv("STARTER_GRANT_V", "150")
    monkeypatch.setenv("V_PER_USD", "100")
    monkeypatch.setenv("TOPUP_LOW_BALANCE_FLOOR_USD", "5")
    monkeypatch.setenv("TOPUP_CRITICAL_BALANCE_FLOOR_V", "90")
    monkeypatch.setattr(wallet_routes, "get_db", lambda: db)
    monkeypatch.setattr(wallet_routes, "get_wallet", lambda: wallet)

    first = await wallet_routes.wallet_bootstrap(user={"user_id": "u1"})
    second = await wallet_routes.wallet_bootstrap(user={"user_id": "u1"})

    assert first["starter_grant_applied"] is True
    assert second["starter_grant_applied"] is False
    assert first["balance"] == "150.000000"
    assert second["balance"] == "150.000000"
    assert len(wallet.fund_calls) == 1


@pytest.mark.asyncio
async def test_post_wallet_bootstrap_applies_once(monkeypatch: pytest.MonkeyPatch):
    db = _FakeDB()
    wallet = _FakeWallet()
    monkeypatch.setenv("STARTER_GRANT_V", "150")
    monkeypatch.setenv("V_PER_USD", "100")
    monkeypatch.setenv("TOPUP_LOW_BALANCE_FLOOR_USD", "5")
    monkeypatch.setenv("TOPUP_CRITICAL_BALANCE_FLOOR_V", "90")
    monkeypatch.setattr(wallet_routes, "get_db", lambda: db)
    monkeypatch.setattr(wallet_routes, "get_wallet", lambda: wallet)

    first = await wallet_routes.wallet_bootstrap(user={"user_id": "u1"})
    second = await wallet_routes.wallet_bootstrap(user={"user_id": "u1"})

    assert first["starter_grant_applied"] is True
    assert second["starter_grant_applied"] is False
    assert wallet.balances["user:u1"] == Decimal("150")


@pytest.mark.asyncio
async def test_get_balance_starter_grant_received_always_boolean(monkeypatch: pytest.MonkeyPatch):
    db = _FakeDB()
    wallet = _FakeWallet()
    monkeypatch.setenv("V_PER_USD", "100")
    monkeypatch.setenv("TOPUP_LOW_BALANCE_FLOOR_USD", "5")
    monkeypatch.setenv("TOPUP_CRITICAL_BALANCE_FLOOR_V", "90")
    monkeypatch.setattr(wallet_routes, "get_db", lambda: db)
    monkeypatch.setattr(wallet_routes, "get_wallet", lambda: wallet)

    out_before = await wallet_routes.get_balance(user={"user_id": "u1"})
    assert isinstance(out_before["starter_grant_received"], bool)
    assert out_before["starter_grant_received"] is False

    db.starter_grants["u1"] = {"granted_amount_v": Decimal("150"), "grant_version": "v1"}
    out_after = await wallet_routes.get_balance(user={"user_id": "u1"})
    assert isinstance(out_after["starter_grant_received"], bool)
    assert out_after["starter_grant_received"] is True


@pytest.mark.asyncio
async def test_get_balance_has_no_side_effects(monkeypatch: pytest.MonkeyPatch):
    db = _FakeDB()

    class _ReadOnlyWallet(_FakeWallet):
        async def fund_from_card(self, **kwargs):  # pragma: no cover - safety guard
            raise AssertionError("get_balance must not fund wallet")

    wallet = _ReadOnlyWallet()
    monkeypatch.setenv("V_PER_USD", "100")
    monkeypatch.setenv("TOPUP_LOW_BALANCE_FLOOR_USD", "5")
    monkeypatch.setenv("TOPUP_CRITICAL_BALANCE_FLOOR_V", "90")
    monkeypatch.setattr(wallet_routes, "get_db", lambda: db)
    monkeypatch.setattr(wallet_routes, "get_wallet", lambda: wallet)

    before_exec = len(db.execute_calls)
    out = await wallet_routes.get_balance(user={"user_id": "u1"})
    after_exec = len(db.execute_calls)

    assert out["balance"] == "0.000000"
    assert before_exec == after_exec


def test_balance_state_warning_vs_critical_asymmetric(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("V_PER_USD", "100")
    monkeypatch.setenv("TOPUP_LOW_BALANCE_FLOOR_USD", "5")
    monkeypatch.setenv("TOPUP_CRITICAL_BALANCE_FLOOR_V", "90")

    assert wallet_routes._balance_state(Decimal("600"), Decimal("100")) == "ok"
    assert wallet_routes._balance_state(Decimal("500"), Decimal("100")) == "warning"
    assert wallet_routes._balance_state(Decimal("90"), Decimal("100")) == "critical"


@pytest.mark.asyncio
async def test_bootstrap_multi_tab_repeat_calls_safe(monkeypatch: pytest.MonkeyPatch):
    db = _FakeDB()
    wallet = _FakeWallet()
    monkeypatch.setenv("STARTER_GRANT_V", "150")
    monkeypatch.setenv("V_PER_USD", "100")
    monkeypatch.setenv("TOPUP_LOW_BALANCE_FLOOR_USD", "5")
    monkeypatch.setenv("TOPUP_CRITICAL_BALANCE_FLOOR_V", "90")
    monkeypatch.setattr(wallet_routes, "get_db", lambda: db)
    monkeypatch.setattr(wallet_routes, "get_wallet", lambda: wallet)

    results = await asyncio.gather(
        wallet_routes.wallet_bootstrap(user={"user_id": "u1"}),
        wallet_routes.wallet_bootstrap(user={"user_id": "u1"}),
    )

    applied_count = sum(1 for r in results if r["starter_grant_applied"])
    assert applied_count == 1
    assert wallet.balances["user:u1"] == Decimal("150")
