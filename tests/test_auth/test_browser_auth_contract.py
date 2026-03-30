from __future__ import annotations

from pathlib import Path


def _page_auth_source() -> str:
    path = Path("ui/assets/page-auth.js")
    return path.read_text(encoding="utf-8")


def test_browser_auth_is_memory_only_and_not_localstorage():
    src = _page_auth_source()
    assert "localStorage" not in src
    assert "let accessToken = \"\";" in src
    assert "let accessExpUnix = 0;" in src


def test_bootstrap_refresh_timeout_budget_is_frozen():
    src = _page_auth_source()
    assert 'refreshAccessToken("bootstrap", { timeoutMs: 2500 })' in src
    assert "AbortController" in src
    assert "setTimeout(() => ctrl.abort(), timeoutMs)" in src


def test_browser_refresh_flow_supports_proactive_and_retry_paths():
    src = _page_auth_source()
    assert 'await refreshAccessToken("proactive")' in src
    assert 'await refreshAccessToken("retry_401")' in src
    assert '"X-OpenVegas-Refresh-Trigger": trigger' in src
    assert 'credentials: "include"' in src


def test_browser_auth_state_transitions_are_serialized():
    src = _page_auth_source()
    assert "let authState = \"signed_out\";" in src
    assert "let authStateVersion = 0;" in src
    assert "function setAuthState(next)" in src
    assert "authStateVersion += 1;" in src


def test_browser_auth_probe_runs_wallet_bootstrap_once():
    src = _page_auth_source()
    assert "let walletBootstrapDone = false;" in src
    assert "async function ensureWalletBootstrap()" in src
    assert 'await ensureWalletBootstrap();' in src
    assert 'apiFetch("/wallet/bootstrap"' in src
