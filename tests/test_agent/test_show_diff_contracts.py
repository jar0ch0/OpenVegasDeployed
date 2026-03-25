from __future__ import annotations

from openvegas.ide.show_diff import build_show_diff_result
from openvegas.ide.show_diff import normalize_show_diff_result


def test_show_diff_accept_all(monkeypatch):
    monkeypatch.setenv("OPENVEGAS_SHOW_DIFF_DECISION", "accept_all")
    result = build_show_diff_result(
        path="a.py",
        current_contents="a\nb\n",
        new_contents="a\nc\n",
        allow_partial_accept=True,
    )
    assert result["hunks_total"] >= 1
    assert result["all_accepted"] is True
    assert result["timed_out"] is False
    assert all(d["decision"] == "accepted" for d in result["decisions"])


def test_show_diff_partial_accept(monkeypatch):
    monkeypatch.setenv("OPENVEGAS_SHOW_DIFF_DECISION", "partial")
    monkeypatch.setenv("OPENVEGAS_SHOW_DIFF_ACCEPT_HUNKS", "0")
    result = build_show_diff_result(
        path="a.py",
        current_contents="a\nb\nc\n",
        new_contents="a\nx\nc\ny\n",
        allow_partial_accept=True,
    )
    assert result["hunks_total"] >= 1
    assert result["timed_out"] is False
    assert any(d["decision"] == "accepted" for d in result["decisions"])


def test_show_diff_timeout_returns_rejected(monkeypatch):
    monkeypatch.setenv("OPENVEGAS_SHOW_DIFF_DECISION", "timeout")
    result = build_show_diff_result(
        path="a.py",
        current_contents="a\n",
        new_contents="b\n",
        allow_partial_accept=True,
    )
    assert result["timed_out"] is True
    assert all(d["decision"] == "rejected" for d in result["decisions"])
    assert result["all_accepted"] is False


def test_normalize_show_diff_result_fills_missing_indexes_and_defaults():
    raw = {
        "file_path": "a.py",
        "decisions": [{"hunk_index": 2, "decision": "accepted"}],
    }
    normalized = normalize_show_diff_result(raw)
    assert normalized["hunks_total"] == 3
    assert normalized["decisions"][0]["decision"] == "rejected"
    assert normalized["decisions"][1]["decision"] == "rejected"
    assert normalized["decisions"][2]["decision"] == "accepted"
