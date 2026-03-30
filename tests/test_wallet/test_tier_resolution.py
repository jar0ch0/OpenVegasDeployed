from __future__ import annotations

import pytest

from server.routes.wallet import _resolve_user_tier


class _FakeDB:
    def __init__(self, *, personal: bool, team: bool):
        self.personal = personal
        self.team = team

    async def fetchrow(self, query: str, user_id: str):
        _ = user_id
        if "FROM user_subscriptions" in query:
            return {"has_personal": self.personal}
        if "FROM org_members m" in query:
            return {"has_team": self.team}
        raise AssertionError("Unexpected query")


@pytest.mark.asyncio
async def test_tier_subscribed_when_personal_subscription_active():
    db = _FakeDB(personal=True, team=True)
    tier = await _resolve_user_tier(db, "u1")
    assert tier == "subscribed"


@pytest.mark.asyncio
async def test_tier_team_when_no_personal_subscription_but_org_active():
    db = _FakeDB(personal=False, team=True)
    tier = await _resolve_user_tier(db, "u1")
    assert tier == "team"


@pytest.mark.asyncio
async def test_tier_free_when_no_personal_or_org_active():
    db = _FakeDB(personal=False, team=False)
    tier = await _resolve_user_tier(db, "u1")
    assert tier == "free"
