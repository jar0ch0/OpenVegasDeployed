from __future__ import annotations

from openvegas.telemetry import (
    _reset_emit_once_cache_for_tests,
    emit_once_process,
    get_metrics_snapshot,
    reset_metrics,
)


def test_emit_once_process_can_be_isolated_per_test():
    reset_metrics()
    emit_once_process("auth_cookie_name_mode_total", {"cookie_name": "ov_refresh_token"})
    emit_once_process("auth_cookie_name_mode_total", {"cookie_name": "ov_refresh_token"})
    key = "auth_cookie_name_mode_total|cookie_name=ov_refresh_token"
    assert get_metrics_snapshot().get(key, 0) == 1

    _reset_emit_once_cache_for_tests()
    emit_once_process("auth_cookie_name_mode_total", {"cookie_name": "ov_refresh_token"})
    assert get_metrics_snapshot().get(key, 0) == 2
