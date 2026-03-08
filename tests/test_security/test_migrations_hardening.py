from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def test_agent_balance_hardening_migration_exists_and_enforces_agent_nonnegative():
    sql = _read("supabase/migrations/011_agent_balance_hardening.sql")
    assert "ck_wallet_nonnegative_user_agent" in sql
    assert "account_id NOT LIKE 'agent:%'" in sql


def test_rls_hardening_migration_exists_and_hardens_sensitive_tables():
    sql = _read("supabase/migrations/012_rls_hardening.sql")
    assert "ALTER TABLE store_orders ENABLE ROW LEVEL SECURITY;" in sql
    assert "ALTER TABLE agent_tokens ENABLE ROW LEVEL SECURITY;" in sql
    assert "REVOKE ALL ON TABLE agent_tokens FROM anon, authenticated;" in sql


def test_startup_schema_requires_security_migrations():
    deps = _read("server/services/dependencies.py")
    assert 'require_migration_min(db, "011_agent_balance_hardening")' in deps
    assert 'require_migration_min(db, "012_rls_hardening")' in deps
