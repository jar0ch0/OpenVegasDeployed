from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from openvegas.payments.service import BillingService


class _DummyWallet:
    def __init__(self):
        self.fund_calls: list[dict[str, object]] = []

    async def fund_from_card(self, **kwargs):
        self.fund_calls.append(dict(kwargs))


class _TxCtx:
    def __init__(self, tx: "_FakeTx"):
        self.tx = tx

    async def __aenter__(self):
        return self.tx

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeDB:
    def __init__(self, tx: "_FakeTx"):
        self.tx = tx

    def transaction(self):
        return _TxCtx(self.tx)


class _FakeTx:
    def __init__(self):
        self.paid_users: set[str] = set()
        self.active_row: dict[str, object] | None = None
        self.latest_row: dict[str, object] | None = None
        self.idem_store: dict[tuple[str, str], dict[str, object]] = {}
        self.accounting_events: list[dict[str, object]] = []

    async def fetchrow(self, query: str, *args):
        q = " ".join(query.split())
        if "FROM continuation_claim_idempotency" in q:
            user_id, idem = str(args[0]), str(args[1])
            row = self.idem_store.get((user_id, idem))
            if not row:
                return None
            return {"payload_hash": row["payload_hash"], "response_json": row["response_json"]}

        if "FROM user_continuation_credit" in q and "status = 'active'" in q:
            return self.active_row

        if "FROM user_continuation_credit" in q and "ORDER BY issued_at DESC" in q:
            return self.latest_row

        if "FROM fiat_topups" in q and "status = 'paid'" in q:
            user_id = str(args[0])
            return {"one": 1} if user_id in self.paid_users else None

        if "INSERT INTO user_continuation_credit" in q:
            user_id, principal_v, cooldown_until = str(args[0]), Decimal(str(args[1])), args[2]
            row = {
                "id": "cont_1",
                "user_id": user_id,
                "principal_v": principal_v,
                "outstanding_v": principal_v,
                "status": "active",
                "cooldown_until": cooldown_until,
            }
            self.active_row = row.copy()
            self.latest_row = row.copy()
            return row

        return None

    async def execute(self, query: str, *args):
        q = " ".join(query.split())
        if "INSERT INTO continuation_claim_idempotency" in q:
            user_id, idem, payload_hash, response_json = str(args[0]), str(args[1]), str(args[2]), args[3]
            # response_json arrives as JSON text in service.
            import json as _json

            parsed = _json.loads(response_json)
            self.idem_store[(user_id, idem)] = {
                "payload_hash": payload_hash,
                "response_json": parsed,
            }
            return "OK"

        if "UPDATE user_continuation_credit SET outstanding_v = 0, status = 'repaid'" in q:
            if self.active_row:
                self.active_row["outstanding_v"] = Decimal("0")
                self.active_row["status"] = "repaid"
                self.active_row["repaid_at"] = datetime.now(timezone.utc)
                self.latest_row = self.active_row.copy()
            return "OK"

        if "UPDATE user_continuation_credit SET outstanding_v = $2" in q:
            if self.active_row:
                self.active_row["outstanding_v"] = Decimal(str(args[1]))
                self.latest_row = self.active_row.copy()
            return "OK"

        if "UPDATE user_continuation_credit SET outstanding_v = 0, status = 'cancelled'" in q:
            continuation_id = str(args[0])
            if self.active_row and str(self.active_row.get("id")) == continuation_id:
                self.active_row["outstanding_v"] = Decimal("0")
                self.active_row["status"] = "cancelled"
                self.active_row["repaid_at"] = None
                self.latest_row = self.active_row.copy()
                self.active_row = None
            return "OK"

        if "INSERT INTO continuation_accounting_events" in q:
            if "'principal_repaid'" in q:
                continuation_id, user_id, amount_v, reason = args
                event_type = "principal_repaid"
                actor = "system"
            else:
                continuation_id, user_id, amount_v, reason, actor = args
                event_type = "principal_written_off"
            self.accounting_events.append(
                {
                    "continuation_id": str(continuation_id),
                    "user_id": str(user_id),
                    "event_type": event_type,
                    "amount_v": Decimal(str(amount_v)),
                    "reason": str(reason),
                    "actor": str(actor),
                }
            )
            return "OK"

        return "OK"


def _svc(tx: _FakeTx) -> BillingService:
    return BillingService(_FakeDB(tx), _DummyWallet(), stripe_gateway=type("_G", (), {"mode": "stripe"})())


@pytest.mark.asyncio
async def test_continuation_denied_without_paid_history():
    tx = _FakeTx()
    svc = _svc(tx)

    out = await svc.get_continuation_status(user_id="u1")

    assert out["eligible"] is False
    assert out["deny_reason"] == "no_paid_history"
    assert out["outstanding_principal_v"] == "0.000000"
    assert out["cooldown_until"] is None


@pytest.mark.asyncio
async def test_continuation_status_eligible_returns_deny_reason_null():
    tx = _FakeTx()
    tx.paid_users.add("u1")
    svc = _svc(tx)

    out = await svc.get_continuation_status(user_id="u1")

    assert out["eligible"] is True
    assert out["deny_reason"] is None
    assert out["outstanding_principal_v"] == "0.000000"


@pytest.mark.asyncio
async def test_continuation_claim_already_active_returns_deterministic_shape():
    tx = _FakeTx()
    tx.active_row = {
        "id": "cont_1",
        "principal_v": Decimal("50"),
        "outstanding_v": Decimal("42.5"),
        "status": "active",
        "cooldown_until": datetime.now(timezone.utc) + timedelta(days=7),
    }
    tx.latest_row = tx.active_row.copy()
    svc = _svc(tx)

    out = await svc.claim_continuation(user_id="u1", idempotency_key="idem-a")

    assert out["status"] == "already_active"
    assert out["principal_v"] == "50.000000"
    assert out["outstanding_principal_v"] == "42.500000"


@pytest.mark.asyncio
async def test_continuation_claim_denied_returns_deterministic_shape():
    tx = _FakeTx()
    svc = _svc(tx)

    out = await svc.claim_continuation(user_id="u1", idempotency_key="idem-b")

    assert out == {
        "status": "denied",
        "deny_reason": "no_paid_history",
        "outstanding_principal_v": "0.000000",
        "cooldown_until": None,
    }


@pytest.mark.asyncio
async def test_continuation_claim_idempotency_key_replay_returns_same_payload():
    tx = _FakeTx()
    svc = _svc(tx)

    first = await svc.claim_continuation(user_id="u1", idempotency_key="idem-c")
    tx.paid_users.add("u1")
    second = await svc.claim_continuation(user_id="u1", idempotency_key="idem-c")

    assert first == second


@pytest.mark.asyncio
async def test_repayment_allows_zero_net_credit():
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

    repaid, net = await svc._apply_continuation_repayment(
        tx=tx,
        user_id="u1",
        gross_v=Decimal("2000"),
        source_reference="fiat_topup:t1",
    )

    assert repaid == Decimal("2000.000000")
    assert net == Decimal("0.000000")


@pytest.mark.asyncio
async def test_checkout_preview_fields_present_and_correct():
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

    out = await svc.preview_topup_checkout(user_id="u1", amount_usd=Decimal("20.00"))

    assert out["amount_usd"] == "20.00"
    assert out["v_credit_gross"] == "2000.000000"
    assert out["outstanding_principal_v"] == "2500.000000"
    assert out["repay_v"] == "2000.000000"
    assert out["net_credit_v"] == "0.000000"
    assert out["preview_is_estimate"] is True
    assert out["preview_generated_at"]
    assert out["preview_basis_outstanding_principal_v"] == "2500.000000"


@pytest.mark.asyncio
async def test_checkout_preview_is_non_binding_and_settlement_applies_current_outstanding_idempotently():
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

    preview = await svc.preview_topup_checkout(user_id="u1", amount_usd=Decimal("20.00"))
    tx.active_row["outstanding_v"] = Decimal("500")

    repaid, net = await svc._apply_continuation_repayment(
        tx=tx,
        user_id="u1",
        gross_v=Decimal("2000"),
        source_reference="fiat_topup:t2",
    )

    assert preview["repay_v"] == "2000.000000"
    assert repaid == Decimal("500.000000")
    assert net == Decimal("1500.000000")


@pytest.mark.asyncio
async def test_multiple_partial_repayments_emit_principal_repaid_events_with_correct_total():
    tx = _FakeTx()
    tx.active_row = {
        "id": "cont_1",
        "principal_v": Decimal("50"),
        "outstanding_v": Decimal("300"),
        "status": "active",
        "cooldown_until": datetime.now(timezone.utc) + timedelta(days=7),
    }
    tx.latest_row = tx.active_row.copy()
    svc = _svc(tx)

    await svc._apply_continuation_repayment(tx=tx, user_id="u1", gross_v=Decimal("100"), source_reference="fiat_topup:a")
    await svc._apply_continuation_repayment(tx=tx, user_id="u1", gross_v=Decimal("50"), source_reference="fiat_topup:b")
    await svc._apply_continuation_repayment(tx=tx, user_id="u1", gross_v=Decimal("150"), source_reference="fiat_topup:c")

    repaid_events = [e for e in tx.accounting_events if e["event_type"] == "principal_repaid"]
    assert len(repaid_events) == 3
    total = sum((e["amount_v"] for e in repaid_events), start=Decimal("0"))
    assert total == Decimal("300.000000")


@pytest.mark.asyncio
async def test_continuation_cancel_with_outstanding_writes_off_in_same_transaction():
    tx = _FakeTx()
    tx.active_row = {
        "id": "cont_1",
        "principal_v": Decimal("50"),
        "outstanding_v": Decimal("25"),
        "status": "active",
        "cooldown_until": datetime.now(timezone.utc) + timedelta(days=7),
    }
    tx.latest_row = tx.active_row.copy()
    svc = _svc(tx)

    out = await svc.cancel_active_continuation(user_id="u1", reason="fraud")

    assert out["status"] == "cancelled"
    assert out["written_off_v"] == "25.000000"
    assert any(e["event_type"] == "principal_written_off" for e in tx.accounting_events)


@pytest.mark.asyncio
async def test_continuation_writeoff_event_emitted_with_reason():
    tx = _FakeTx()
    tx.active_row = {
        "id": "cont_1",
        "principal_v": Decimal("50"),
        "outstanding_v": Decimal("10"),
        "status": "active",
        "cooldown_until": datetime.now(timezone.utc) + timedelta(days=7),
    }
    tx.latest_row = tx.active_row.copy()
    svc = _svc(tx)

    await svc.cancel_active_continuation(user_id="u1", reason="risk_void", actor="admin")

    writeoffs = [e for e in tx.accounting_events if e["event_type"] == "principal_written_off"]
    assert len(writeoffs) == 1
    assert writeoffs[0]["reason"] == "risk_void"
    assert writeoffs[0]["actor"] == "admin"
