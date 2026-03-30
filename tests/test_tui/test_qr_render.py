from __future__ import annotations

import pytest

from openvegas.tui.qr_render import qr_half_block, qr_width


def test_qr_render_width_positive():
    pytest.importorskip("qrcode")
    width = qr_width("https://example.com/topup/123")
    assert width > 0


def test_qr_half_block_emits_unicode_blocks():
    pytest.importorskip("qrcode")
    out = qr_half_block("https://example.com/topup/123")
    assert out
    assert any(ch in out for ch in ("█", "▀", "▄"))


def test_qr_render_raises_runtime_reason_when_dependency_unavailable(monkeypatch):
    monkeypatch.setattr(
        "openvegas.tui.qr_render.ensure_qrcode_available",
        lambda: (False, "qrcode missing in active runtime"),
    )
    with pytest.raises(RuntimeError, match="qrcode missing in active runtime"):
        qr_width("https://example.com/topup/123")
