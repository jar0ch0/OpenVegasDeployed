from __future__ import annotations

import pytest

from server.services.dependencies import init_runtime_deps


@pytest.mark.asyncio
async def test_init_runtime_deps_requires_supabase_jwt_secret_in_runtime(monkeypatch):
    monkeypatch.setenv("OPENVEGAS_TEST_MODE", "0")
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="SUPABASE_JWT_SECRET"):
        await init_runtime_deps()
