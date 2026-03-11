"""Local config management (~/.openvegas/)."""

import json
import os
from pathlib import Path
from dataclasses import dataclass, field

CONFIG_DIR = Path.home() / ".openvegas"
CONFIG_FILE = CONFIG_DIR / "config.json"
LEGACY_DEFAULT_BACKEND_URL = "https://api.openvegas.gg"
DEFAULT_BACKEND_URL = os.getenv("OPENVEGAS_BACKEND_URL", "http://127.0.0.1:8000")

DEFAULT_CONFIG = {
    "session": {},
    "providers": {},
    "default_provider": "openai",
    "default_model_by_provider": {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-sonnet-4-20250514",
        "gemini": "gemini-2.0-flash",
    },
    "theme": "default",
    "animation": True,
    "backend_url": DEFAULT_BACKEND_URL,
    "supabase_url": "",
    "supabase_anon_key": "",
}


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    ensure_config_dir()
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            stored = json.loads(f.read())
        # Smooth local migration: old production default -> current local default.
        if stored.get("backend_url") == LEGACY_DEFAULT_BACKEND_URL:
            stored["backend_url"] = DEFAULT_BACKEND_URL
        # Merge with defaults for any missing keys
        merged = {**DEFAULT_CONFIG, **stored}
        return merged
    return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    ensure_config_dir()
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def get_provider_key(provider: str) -> str | None:
    config = load_config()
    return config.get("providers", {}).get(provider, {}).get("api_key")


def set_provider_key(provider: str, api_key: str) -> None:
    config = load_config()
    if "providers" not in config:
        config["providers"] = {}
    config["providers"][provider] = {"api_key": api_key}
    save_config(config)


def get_session() -> dict:
    config = load_config()
    return config.get("session", {})


def save_session(access_token: str, refresh_token: str) -> None:
    config = load_config()
    config["session"] = {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }
    save_config(config)


def clear_session() -> None:
    config = load_config()
    config["session"] = {}
    save_config(config)


def get_default_provider() -> str:
    config = load_config()
    return config.get("default_provider", "openai")


def get_default_model(provider: str) -> str:
    config = load_config()
    models = config.get("default_model_by_provider", {})
    return models.get(provider, "gpt-4o-mini")


def get_bearer_token() -> str | None:
    session = get_session()
    return session.get("access_token")


def get_backend_url() -> str:
    config = load_config()
    return config.get("backend_url", DEFAULT_BACKEND_URL)
