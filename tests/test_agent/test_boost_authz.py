from __future__ import annotations

import pytest

from openvegas.agent.boost import BoostService


class _FakeDB:
    async def fetchrow(self, query: str, *args):
        return None


class _FakeWallet:
    async def ensure_account(self, account_id: str):
        return None

    async def mint(self, **kwargs):
        return None


@pytest.mark.asyncio
async def test_submit_and_score_rejects_foreign_challenge():
    svc = BoostService(_FakeDB(), _FakeWallet())

    with pytest.raises(ValueError, match="does not belong"):
        await svc.submit_and_score(
            challenge_id="challenge-x",
            artifact_text="print('hi')",
            agent_account_id="agent-a",
            org_id="org-a",
        )
