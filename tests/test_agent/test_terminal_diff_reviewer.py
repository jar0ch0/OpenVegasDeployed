from __future__ import annotations

from openvegas.ide.show_diff import normalize_show_diff_result
from openvegas.tui.diff_reviewer import (
    filter_patch_by_accepted_hunks,
    is_valid_filtered_patch,
    parse_unified_patch,
    review_patch_terminal,
)


_MULTI_FILE_PATCH = """diff --git a/a.txt b/a.txt
--- a/a.txt
+++ b/a.txt
@@ -1,1 +1,1 @@
-old-a
+new-a
diff --git a/b.txt b/b.txt
--- a/b.txt
+++ b/b.txt
@@ -1,1 +1,1 @@
-old-b
+new-b
"""


def test_parse_unified_patch_assigns_deterministic_hunk_indexes():
    parsed = parse_unified_patch(_MULTI_FILE_PATCH)
    assert parsed.parse_error is None
    assert parsed.hunks_total == 2
    assert [h.hunk_index for h in parsed.hunks] == [0, 1]
    assert parsed.target_files == ("a.txt", "b.txt")


def test_terminal_review_non_tty_fails_closed(monkeypatch):
    class _NoTTY:
        def isatty(self) -> bool:
            return False

    monkeypatch.delenv("OPENVEGAS_TERMINAL_DIFF_DECISION", raising=False)
    monkeypatch.setattr("openvegas.tui.diff_reviewer.sys.stdin", _NoTTY())
    monkeypatch.setattr("openvegas.tui.diff_reviewer.sys.stdout", _NoTTY())
    result = review_patch_terminal(path="a.txt", patch_text=_MULTI_FILE_PATCH)
    assert result["hunks_total"] == 2
    assert result["timed_out"] is False
    assert all(d["decision"] == "rejected" for d in result["decisions"])


def test_terminal_review_accept_reject_and_partial_env_paths(monkeypatch):
    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_DECISION", "accept_all")
    accepted = review_patch_terminal(path="a.txt", patch_text=_MULTI_FILE_PATCH)
    assert accepted["all_accepted"] is True
    assert all(d["decision"] == "accepted" for d in accepted["decisions"])

    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_DECISION", "reject_all")
    rejected = review_patch_terminal(path="a.txt", patch_text=_MULTI_FILE_PATCH)
    assert rejected["all_accepted"] is False
    assert all(d["decision"] == "rejected" for d in rejected["decisions"])

    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_DECISION", "partial")
    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_ACCEPT_HUNKS", "1")
    partial = review_patch_terminal(path="a.txt", patch_text=_MULTI_FILE_PATCH)
    assert partial["all_accepted"] is False
    assert partial["decisions"][0]["decision"] == "rejected"
    assert partial["decisions"][1]["decision"] == "accepted"


def test_terminal_review_timeout_maps_to_reject_all(monkeypatch):
    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_DECISION", "timeout")
    result = review_patch_terminal(path="a.txt", patch_text=_MULTI_FILE_PATCH)
    assert result["timed_out"] is True
    assert result["all_accepted"] is False
    assert all(d["decision"] == "rejected" for d in result["decisions"])


def test_terminal_review_large_diff_guard(monkeypatch):
    monkeypatch.setenv("OPENVEGAS_TERMINAL_DIFF_MAX_HUNKS", "1")
    monkeypatch.delenv("OPENVEGAS_TERMINAL_DIFF_DECISION", raising=False)
    result = review_patch_terminal(path="a.txt", patch_text=_MULTI_FILE_PATCH)
    assert result["all_accepted"] is False
    assert result.get("error") == "large_diff"


def test_normalization_drift_protection_between_ide_and_terminal_payloads():
    ide_payload = {
        "file_path": "a.txt",
        "hunks_total": 2,
        "decisions": [
            {"hunk_index": 0, "decision": "accepted"},
            {"hunk_index": 1, "decision": "rejected"},
        ],
        "all_accepted": False,
        "timed_out": False,
    }
    terminal_payload = {
        "file_path": "a.txt",
        "decisions": [
            {"hunk_index": 1, "decision": "rejected"},
            {"hunk_index": 0, "decision": "accepted"},
        ],
        "timed_out": False,
    }
    assert normalize_show_diff_result(ide_payload) == normalize_show_diff_result(terminal_payload)


def test_filtered_multifile_patch_drops_fully_rejected_files_and_preserves_headers():
    filtered_text, filtered_parsed = filter_patch_by_accepted_hunks(_MULTI_FILE_PATCH, {1})
    assert filtered_text is not None
    assert filtered_parsed is not None
    assert is_valid_filtered_patch(filtered_parsed) is True
    assert "--- a/a.txt" not in filtered_text
    assert "+++ b/b.txt" in filtered_text
    assert "old-b" in filtered_text and "new-b" in filtered_text
    assert filtered_parsed.target_files == ("b.txt",)


def test_filtered_patch_invalid_when_hunk_ranges_inconsistent():
    malformed = """--- a/a.txt
+++ b/a.txt
@@ -1,2 +1,1 @@
-line1
+line1
"""
    parsed = parse_unified_patch(malformed)
    assert is_valid_filtered_patch(parsed) is False
