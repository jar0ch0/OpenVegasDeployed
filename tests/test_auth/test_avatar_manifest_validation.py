from __future__ import annotations

from server.routes import profile_preferences


def test_allowed_ids_defaults_when_manifest_invalid(monkeypatch):
    monkeypatch.setattr(profile_preferences, "_load_manifest", lambda: {"users": "bad", "dealer": "bad"})
    dealer_ids, avatar_ids, palette_map = profile_preferences._allowed_ids()
    assert "ov_dealer_female_tux_v1" in dealer_ids
    assert "ov_user_01" in avatar_ids
    assert "default" in palette_map["ov_user_01"]


def test_allowed_ids_manifest_parsed(monkeypatch):
    monkeypatch.setattr(
        profile_preferences,
        "_load_manifest",
        lambda: {
            "dealer": [{"id": "ov_dealer_female_tux_v1"}, {"id": "ov_dealer_alt"}],
            "users": [{"id": "ov_user_01", "palettes": ["default", "warm"]}],
        },
    )
    dealer_ids, avatar_ids, palette_map = profile_preferences._allowed_ids()
    assert "ov_dealer_alt" in dealer_ids
    assert "ov_user_01" in avatar_ids
    assert "warm" in palette_map["ov_user_01"]
