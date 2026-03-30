"""Lightweight in-process telemetry helpers.

This keeps metric emission dependency-free while giving tests and local runs a
deterministic counter surface.
"""

from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import DefaultDict


_LOCK = Lock()
_COUNTERS: DefaultDict[str, int] = defaultdict(int)
_EMITTED_ONCE_KEYS: set[str] = set()


def _key(name: str, tags: dict[str, object] | None = None) -> str:
    if not tags:
        return name
    tag_text = ",".join(f"{k}={tags[k]}" for k in sorted(tags))
    return f"{name}|{tag_text}"


def emit_metric(name: str, tags: dict[str, object] | None = None, value: int = 1) -> None:
    """Increment a counter-style metric."""
    metric_key = _key(str(name), tags)
    with _LOCK:
        _COUNTERS[metric_key] += int(value)


def emit_once_process(name: str, tags: dict[str, object] | None = None, value: int = 1) -> None:
    """Emit a metric once per-process for a stable name+tag key."""
    metric_key = _key(str(name), tags)
    with _LOCK:
        if metric_key in _EMITTED_ONCE_KEYS:
            return
        _EMITTED_ONCE_KEYS.add(metric_key)
        _COUNTERS[metric_key] += int(value)


def get_metrics_snapshot() -> dict[str, int]:
    with _LOCK:
        return dict(_COUNTERS)


def get_dashboard_slices() -> dict[str, object]:
    """Return pre-aggregated slices for runtime reliability dashboards."""
    with _LOCK:
        snapshot = dict(_COUNTERS)

    def _parse_tags(metric_key: str) -> tuple[str, dict[str, str]]:
        if "|" not in metric_key:
            return metric_key, {}
        name, raw_tags = metric_key.split("|", 1)
        tags: dict[str, str] = {}
        for token in raw_tags.split(","):
            if "=" not in token:
                continue
            k, v = token.split("=", 1)
            tags[k] = v
        return name, tags

    retry_by_status: dict[str, int] = defaultdict(int)
    finalize_reason_dist: dict[str, int] = defaultdict(int)
    same_intent_fail_total = 0
    topup_suggest_suppressed: dict[str, int] = defaultdict(int)
    topup_transitions: dict[str, int] = defaultdict(int)
    topup_checkout_created: dict[str, int] = defaultdict(int)

    for metric_key, count in snapshot.items():
        name, tags = _parse_tags(metric_key)
        if name == "tool_apply_patch_same_intent_fail_total":
            same_intent_fail_total += int(count)
        elif name == "tool_apply_patch_retry_total":
            retry_by_status[str(tags.get("status", "unknown"))] += int(count)
        elif name == "tool_loop_finalize_reason":
            finalize_reason_dist[str(tags.get("reason", "unknown"))] += int(count)
        elif name == "topup_suggest_suppressed_total":
            topup_suggest_suppressed[str(tags.get("reason", "unknown"))] += int(count)
        elif name == "topup_status_transition_total":
            edge = f"{tags.get('from', 'unknown')}->{tags.get('to', 'unknown')}|{tags.get('mode', 'unknown')}"
            topup_transitions[edge] += int(count)
        elif name == "topup_checkout_created_total":
            topup_checkout_created[str(tags.get("mode", "unknown"))] += int(count)

    return {
        "tool_apply_patch_same_intent_fail_total": int(same_intent_fail_total),
        "tool_apply_patch_retry_total_by_status": dict(sorted(retry_by_status.items())),
        "tool_loop_finalize_reason_distribution": dict(sorted(finalize_reason_dist.items())),
        "topup_suggest_suppressed_total_by_reason": dict(sorted(topup_suggest_suppressed.items())),
        "topup_status_transition_total": dict(sorted(topup_transitions.items())),
        "topup_checkout_created_total_by_mode": dict(sorted(topup_checkout_created.items())),
    }


def reset_metrics() -> None:
    with _LOCK:
        _COUNTERS.clear()
        _EMITTED_ONCE_KEYS.clear()


def _reset_emit_once_cache_for_tests() -> None:
    """Test-only helper to keep emit-once assertions order independent."""
    with _LOCK:
        _EMITTED_ONCE_KEYS.clear()
