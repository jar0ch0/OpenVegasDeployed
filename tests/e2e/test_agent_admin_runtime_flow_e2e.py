from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from server.main import app
from server.middleware import auth as auth_middleware
from server.routes import agent as agent_routes
from server.routes import casino as casino_routes


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _FakeAgentService:
    def __init__(self):
        self.accounts: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}
        self.tokens: dict[str, dict] = {}

    async def create_account(self, org_id: str, name: str) -> dict:
        aid = str(uuid4())
        self.accounts[aid] = {
            "agent_account_id": aid,
            "org_id": org_id,
            "name": name,
            "status": "active",
            "created_at": _now(),
        }
        return {"agent_account_id": aid, "org_id": org_id, "name": name}

    async def issue_token(
        self,
        agent_account_id: str,
        scopes: list[str],
        ttl_minutes: int = 60,
        created_by_user_id: str | None = None,
    ) -> str:
        _ = created_by_user_id
        tok = f"ov_agent_{uuid4().hex}"
        acct = self.accounts[agent_account_id]
        self.tokens[tok] = {
            "agent_account_id": agent_account_id,
            "org_id": acct["org_id"],
            "scopes": list(scopes),
            "expires_at": _now() + timedelta(minutes=int(ttl_minutes)),
        }
        return tok

    async def start_session(
        self,
        agent_account_id: str,
        org_id: str,
        envelope_v: Decimal,
        ttl_seconds: int | None = None,
    ) -> dict:
        sid = str(uuid4())
        ttl = int(ttl_seconds or 1800)
        session = {
            "session_id": sid,
            "agent_account_id": agent_account_id,
            "org_id": org_id,
            "envelope_v": Decimal(str(envelope_v)),
            "spent_v": Decimal("0"),
            "reserved_v": Decimal("0"),
            "refunded_v": Decimal("0"),
            "status": "active",
            "started_at": _now(),
            "ended_at": None,
            "expires_at": _now() + timedelta(seconds=ttl),
        }
        self.sessions[sid] = session
        return {
            "session_id": sid,
            "envelope_v": str(session["envelope_v"]),
            "spent_v": "0",
            "remaining_v": str(session["envelope_v"]),
            "status": "active",
            "expires_at": session["expires_at"].isoformat(),
        }

    async def check_session_budget(
        self,
        session_id: str,
        amount_v: Decimal,
        agent_account_id: str | None = None,
    ) -> bool:
        s = self.sessions.get(session_id)
        if not s or s["status"] != "active":
            return False
        if agent_account_id and s["agent_account_id"] != agent_account_id:
            return False
        remaining = s["envelope_v"] - s["spent_v"] - s["reserved_v"] + s["refunded_v"]
        return remaining >= Decimal(str(amount_v))

    async def record_spend(
        self,
        session_id: str,
        amount_v: Decimal,
        agent_account_id: str | None = None,
    ):
        s = self.sessions.get(session_id)
        if not s:
            raise ValueError("session not found")
        if agent_account_id and s["agent_account_id"] != agent_account_id:
            raise ValueError("session does not belong to this agent")
        s["spent_v"] += Decimal(str(amount_v))

    async def get_budget(self, session_id: str, agent_account_id: str | None = None) -> dict:
        s = self.sessions.get(session_id)
        if not s:
            return {"error": "Session not found"}
        if agent_account_id and s["agent_account_id"] != agent_account_id:
            return {"error": "Session not found"}
        remaining = s["envelope_v"] - s["spent_v"] - s["reserved_v"] + s["refunded_v"]
        return {
            "session_id": session_id,
            "envelope_v": str(s["envelope_v"]),
            "spent_v": str(s["spent_v"]),
            "remaining_v": str(remaining),
            "status": s["status"],
        }

    async def list_accounts(self, *, org_id: str) -> list[dict]:
        rows = [a for a in self.accounts.values() if a["org_id"] == org_id]
        return [
            {
                "agent_account_id": a["agent_account_id"],
                "org_id": a["org_id"],
                "name": a["name"],
                "status": a["status"],
                "created_at": a["created_at"].isoformat(),
            }
            for a in rows
        ]


class _FakeOrgService:
    def __init__(self):
        self.policy = {
            "org_id": "org-1",
            "allowed_providers": ["openai"],
            "allowed_models": ["gpt-4o-mini"],
            "user_daily_cap_usd": Decimal("50.00"),
            "byok_fallback_enabled": False,
            "boost_enabled": True,
            "casino_enabled": True,
            "casino_agent_max_loss_v": Decimal("20.000000"),
            "casino_round_max_wager_v": Decimal("5.000000"),
            "casino_round_cooldown_ms": 500,
            "agent_default_envelope_v": Decimal("10.000000"),
            "agent_max_envelope_v": Decimal("100.000000"),
            "agent_session_ttl_sec": 1800,
            "agent_infer_enabled": True,
        }

    async def get_policy(self, org_id: str) -> dict | None:
        if org_id != "org-1":
            return None
        return dict(self.policy)

    async def set_policy(self, org_id: str, **fields) -> dict:
        if org_id != "org-1":
            return {"updated": False}
        self.policy.update(fields)
        return {"updated": True}

    async def check_policy(self, org_id: str, provider: str, model: str) -> bool:
        if org_id != "org-1":
            return False
        if provider not in self.policy.get("allowed_providers", []):
            return False
        models = self.policy.get("allowed_models", [])
        if models and model not in models:
            return False
        return True


class _FakeCatalog:
    async def get_pricing(self, provider: str, model: str) -> dict:
        _ = provider, model
        return {"v_price_input_per_1m": Decimal("1"), "v_price_output_per_1m": Decimal("1")}


class _FakeGateway:
    def _estimate_max_cost(self, model_config: dict, max_tokens: int) -> Decimal:
        _ = model_config, max_tokens
        return Decimal("1.000000")

    async def infer(self, _req) -> SimpleNamespace:
        return SimpleNamespace(
            text="ok",
            v_cost=Decimal("0.500000"),
            input_tokens=12,
            output_tokens=8,
        )


class _FakeCasinoService:
    def __init__(self, agent_svc: _FakeAgentService):
        self.agent_svc = agent_svc
        self.sessions: dict[str, dict] = {}
        self.rounds: dict[str, dict] = {}
        self.payouts: list[dict] = []

    async def start_session(
        self,
        org_id: str,
        agent_account_id: str,
        agent_session_id: str,
        max_loss_v: Decimal,
        max_rounds: int = 100,
    ) -> dict:
        sid = str(uuid4())
        self.sessions[sid] = {
            "id": sid,
            "org_id": org_id,
            "agent_account_id": agent_account_id,
            "agent_session_id": agent_session_id,
            "max_loss_v": Decimal(str(max_loss_v)),
            "max_rounds": int(max_rounds),
            "rounds_played": 0,
            "net_pnl_v": Decimal("0"),
            "status": "active",
            "started_at": _now(),
            "ended_at": None,
        }
        return {"casino_session_id": sid, "max_loss_v": str(max_loss_v), "max_rounds": int(max_rounds), "status": "active"}

    async def start_round(self, session_id: str, game_code: str, wager_v: Decimal, agent_account_id: str) -> dict:
        sess = self.sessions.get(session_id)
        if not sess or sess["agent_account_id"] != agent_account_id:
            raise ValueError("session not found")
        rid = str(uuid4())
        self.rounds[rid] = {
            "id": rid,
            "session_id": session_id,
            "game_code": game_code,
            "wager_v": Decimal(str(wager_v)),
            "status": "active",
        }
        sess["rounds_played"] += 1
        return {"round_id": rid, "state": {"phase": "ready"}, "valid_actions": ["stand"]}

    async def apply_action(self, round_id: str, action: str, payload: dict, idempotency_key: str, agent_account_id: str) -> dict:
        _ = payload, idempotency_key, agent_account_id
        row = self.rounds.get(round_id)
        if not row:
            raise ValueError("round not found")
        row["last_action"] = action
        return {"state": {"phase": "done"}, "valid_actions": []}

    async def resolve_round(self, round_id: str, agent_account_id: str) -> dict:
        row = self.rounds.get(round_id)
        if not row:
            raise ValueError("round not found")
        sess = self.sessions[row["session_id"]]
        if sess["agent_account_id"] != agent_account_id:
            raise ValueError("round not found")
        wager = Decimal(str(row["wager_v"]))
        payout = (wager * Decimal("2")).quantize(Decimal("0.01"))
        net = payout - wager
        sess["net_pnl_v"] += net
        row["status"] = "resolved"
        payload = {
            "round_id": round_id,
            "session_id": row["session_id"],
            "agent_account_id": agent_account_id,
            "agent_name": "bot-a",
            "wager_v": wager,
            "payout_v": payout,
            "net_v": net,
            "created_at": _now(),
        }
        self.payouts.append(payload)
        return {"round_id": round_id, "payout_v": str(payout), "net_v": str(net)}

    async def get_session(self, session_id: str, agent_account_id: str) -> dict:
        row = self.sessions.get(session_id)
        if not row or row["agent_account_id"] != agent_account_id:
            raise ValueError("session not found")
        return {
            "casino_session_id": row["id"],
            "status": row["status"],
            "rounds_played": row["rounds_played"],
            "net_pnl_v": str(row["net_pnl_v"]),
        }


class _FakeDB:
    def __init__(self, agent_svc: _FakeAgentService, casino_svc: _FakeCasinoService):
        self.agent_svc = agent_svc
        self.casino_svc = casino_svc
        self.org_members = {("org-1", "u-admin"): "owner"}

    async def fetchrow(self, query: str, *args):
        q = " ".join(query.strip().split()).lower()
        if "from org_members" in q:
            org_id, user_id = str(args[0]), str(args[1])
            role = self.org_members.get((org_id, user_id))
            if not role:
                return None
            return {"role": role}
        if "from agent_accounts" in q and "where id = $1 and org_id = $2" in q:
            aid, org_id = str(args[0]), str(args[1])
            acct = self.agent_svc.accounts.get(aid)
            if not acct or acct["org_id"] != org_id:
                return None
            return {"id": aid}
        raise RuntimeError(f"unexpected fetchrow query: {query}")

    async def fetch(self, query: str, *args):
        q = " ".join(query.strip().split()).lower()
        if "from agent_sessions s" in q:
            org_id = str(args[0])
            out = []
            for s in self.agent_svc.sessions.values():
                if s["org_id"] != org_id:
                    continue
                acct = self.agent_svc.accounts.get(s["agent_account_id"], {})
                out.append(
                    {
                        "id": s["session_id"],
                        "agent_account_id": s["agent_account_id"],
                        "agent_name": acct.get("name", "unknown"),
                        "envelope_v": s["envelope_v"],
                        "spent_v": s["spent_v"],
                        "status": s["status"],
                        "started_at": s["started_at"],
                        "ended_at": s["ended_at"],
                    }
                )
            return out
        if "from casino_sessions cs" in q:
            org_id = str(args[0])
            out = []
            for s in self.casino_svc.sessions.values():
                if s["org_id"] != org_id:
                    continue
                acct = self.agent_svc.accounts.get(s["agent_account_id"], {})
                out.append(
                    {
                        "id": s["id"],
                        "agent_account_id": s["agent_account_id"],
                        "agent_name": acct.get("name", "unknown"),
                        "status": s["status"],
                        "rounds_played": s["rounds_played"],
                        "net_pnl_v": s["net_pnl_v"],
                        "started_at": s["started_at"],
                        "ended_at": s["ended_at"],
                    }
                )
            return out
        if "from casino_payouts cp" in q:
            org_id = str(args[0])
            out = []
            for p in self.casino_svc.payouts:
                sess = self.casino_svc.sessions.get(p["session_id"])
                if not sess or sess["org_id"] != org_id:
                    continue
                out.append(
                    {
                        "round_id": p["round_id"],
                        "session_id": p["session_id"],
                        "agent_account_id": p["agent_account_id"],
                        "agent_name": p["agent_name"],
                        "wager_v": p["wager_v"],
                        "payout_v": p["payout_v"],
                        "net_v": p["net_v"],
                        "created_at": p["created_at"],
                    }
                )
            return out
        raise RuntimeError(f"unexpected fetch query: {query}")


def _override_user():
    return {"user_id": "u-admin", "role": "authenticated"}


def test_agent_admin_to_runtime_casino_e2e(monkeypatch):
    fake_agent = _FakeAgentService()
    fake_org = _FakeOrgService()
    fake_catalog = _FakeCatalog()
    fake_gateway = _FakeGateway()
    fake_casino = _FakeCasinoService(fake_agent)
    fake_db = _FakeDB(fake_agent, fake_casino)

    async def _current_agent(request: Request):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing token")
        token = auth.removeprefix("Bearer ").strip()
        item = fake_agent.tokens.get(token)
        if not item:
            raise HTTPException(status_code=401, detail="invalid token")
        if item["expires_at"] <= _now():
            raise HTTPException(status_code=401, detail="expired token")
        return {
            "agent_account_id": item["agent_account_id"],
            "org_id": item["org_id"],
            "agent_name": "bot-a",
            "scopes": item["scopes"],
            "account_type": "agent",
        }

    monkeypatch.setattr(agent_routes, "get_agent_service", lambda: fake_agent)
    monkeypatch.setattr(agent_routes, "get_org_service", lambda: fake_org)
    monkeypatch.setattr(agent_routes, "get_catalog", lambda: fake_catalog)
    monkeypatch.setattr(agent_routes, "get_gateway", lambda: fake_gateway)
    monkeypatch.setattr(agent_routes, "get_db", lambda: fake_db)
    monkeypatch.setattr(casino_routes, "get_casino_service", lambda: fake_casino)

    app.dependency_overrides[auth_middleware.get_current_user] = _override_user
    app.dependency_overrides[auth_middleware.get_current_agent] = _current_agent

    try:
        client = TestClient(app)

        # Admin provisioning
        created = client.post("/v1/agent/admin/orgs/org-1/accounts", json={"name": "bot-a"})
        assert created.status_code == 200
        agent_account_id = created.json()["agent_account_id"]

        token_resp = client.post(
            f"/v1/agent/admin/orgs/org-1/accounts/{agent_account_id}/tokens",
            json={"scopes": ["infer", "budget.read", "casino.play"], "ttl_minutes": 120},
        )
        assert token_resp.status_code == 200
        token = token_resp.json()["token"]
        assert token.startswith("ov_agent_")

        # Policy update/read
        upd = client.patch(
            "/v1/agent/admin/orgs/org-1/policies",
            json={"agent_default_envelope_v": "12.500000", "agent_max_envelope_v": "120.000000"},
        )
        assert upd.status_code == 200
        got = client.get("/v1/agent/admin/orgs/org-1/policies")
        assert got.status_code == 200
        assert got.json()["policy"]["agent_default_envelope_v"] == "12.500000"

        ah = {"Authorization": f"Bearer {token}"}

        # Runtime spend path
        sess = client.post("/v1/agent/sessions/start", json={"envelope_v": "15.000000"}, headers=ah)
        assert sess.status_code == 200
        session_id = sess.json()["session_id"]

        infer = client.post(
            "/v1/agent/infer",
            json={
                "session_id": session_id,
                "prompt": "hello",
                "provider": "openai",
                "model": "gpt-4o-mini",
                "max_tokens": 128,
            },
            headers=ah,
        )
        assert infer.status_code == 200
        assert infer.json()["v_cost"] == "0.500000"

        budget = client.get("/v1/agent/budget", params={"session_id": session_id}, headers=ah)
        assert budget.status_code == 200
        assert Decimal(budget.json()["spent_v"]) == Decimal("0.500000")

        # Casino path + settlement
        cs = client.post(
            "/v1/agent/casino/sessions/start",
            json={"agent_session_id": session_id, "max_loss_v": 5},
            headers=ah,
        )
        assert cs.status_code == 200
        casino_session_id = cs.json()["casino_session_id"]

        rnd = client.post(
            "/v1/agent/casino/rounds/start",
            json={"casino_session_id": casino_session_id, "game_code": "blackjack", "wager_v": 1.5},
            headers=ah,
        )
        assert rnd.status_code == 200
        round_id = rnd.json()["round_id"]

        res = client.post(f"/v1/agent/casino/rounds/{round_id}/resolve", json={}, headers=ah)
        assert res.status_code == 200
        assert Decimal(res.json()["net_v"]) > Decimal("0")

        # Audit view includes runtime + casino settlement evidence.
        audit = client.get("/v1/agent/admin/orgs/org-1/audit?limit=50")
        assert audit.status_code == 200
        payload = audit.json()
        assert payload["counts"]["agent_sessions"] >= 1
        assert payload["counts"]["casino_sessions"] >= 1
        assert payload["counts"]["casino_payouts"] >= 1
    finally:
        app.dependency_overrides.clear()
