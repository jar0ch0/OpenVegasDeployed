from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read_migration() -> str:
    return (ROOT / "supabase/migrations/032_wallet_bootstrap_and_continuation.sql").read_text()


def test_single_active_continuation_enforced_by_index():
    sql = _read_migration()
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_continuation_active" in sql
    assert "WHERE status = 'active'" in sql


def test_continuation_repaid_status_requires_repaid_at_constraint():
    sql = _read_migration()
    assert "(status = 'repaid' AND outstanding_v = 0 AND repaid_at IS NOT NULL)" in sql
    assert "(status = 'active' AND outstanding_v > 0 AND repaid_at IS NULL)" in sql
