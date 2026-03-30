from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_avatar_manifest_exists_and_contains_defaults():
    text = _read("ui/assets/avatar-manifest.json")
    assert '"ov_dealer_female_tux_v1"' in text
    assert '"ov_user_01"' in text
    assert '"name": "Classic Player"' in text
    assert '"name": "Victoria - Classic Tuxedo"' in text


def test_profile_page_exists_and_uses_avatar_widget():
    text = _read("ui/profile.html")
    assert "mountDealerWidget" not in text
    assert '/ui/profile/preferences' in text
    assert "Your Avatar" in text
    assert "Color Theme" in text
    assert "Your Dealer" in text


def test_balance_subscription_pages_hide_dealer_widget():
    balance = _read("ui/balance.html")
    subscription = _read("ui/subscription.html")
    assert "dealerWidget" not in balance
    assert "mountDealerWidget" not in balance
    assert "dealerWidget" not in subscription
    assert "mountDealerWidget" not in subscription


def test_avatar_widget_has_deterministic_fallback_path():
    text = _read("ui/assets/avatar-widget.js")
    assert "avatar_asset_load_fail_total" in text
    assert "sprite_load_failed" in text


def test_main_includes_profile_page_and_avatar_assets_route_support():
    text = _read("server/main.py")
    assert '"profile": UI_DIR / "profile.html"' in text
    assert '"checkout-pending": UI_DIR / "checkout-pending.html"' in text
    assert '@app.get("/t/{topup_id}")' in text
    assert '@app.get("/r/{compact_topup_id}")' in text
    assert '@app.get("/ui/assets/{asset_path:path}")' in text
