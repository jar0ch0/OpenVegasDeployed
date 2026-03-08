"""Tests for theme system and ASCII-safe mode."""

import os
from openvegas.tui.theme import (
    ascii_safe_mode, THEMES, BORDER_ASCII, BORDER_HEAVY, BORDER_LIGHT,
    get_theme,
)


def test_ascii_safe_env_override(monkeypatch):
    monkeypatch.setenv("OPENVEGAS_ASCII", "1")
    assert ascii_safe_mode() is True


def test_ascii_safe_default_with_utf_lang(monkeypatch):
    monkeypatch.setenv("OPENVEGAS_ASCII", "0")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert ascii_safe_mode() is False


def test_retro_ascii_uses_pure_ascii_borders():
    theme = THEMES["retro_ascii"]
    b = theme["card_border"]
    # All border chars must be pure ASCII (ord < 128)
    for key, char in b.items():
        assert ord(char) < 128, f"Non-ASCII border char '{char}' in retro_ascii theme"


def test_border_ascii_is_pure_ascii():
    for key, char in BORDER_ASCII.items():
        assert ord(char) < 128, f"BORDER_ASCII has non-ASCII char '{char}'"


def test_all_themes_exist():
    assert "retro_ascii" in THEMES
    assert "classic_casino" in THEMES
    assert "neon_arcade" in THEMES


def test_get_theme_ascii_safe(monkeypatch):
    monkeypatch.setenv("OPENVEGAS_ASCII", "1")
    theme = get_theme()
    assert theme["card_border"] is BORDER_ASCII


def test_theme_has_required_keys():
    for name, theme in THEMES.items():
        for key in ["horse_glyph", "trail", "empty", "finish", "cursor", "card_border"]:
            assert key in theme, f"Theme '{name}' missing key '{key}'"
