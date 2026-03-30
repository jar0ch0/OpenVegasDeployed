from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from server.middleware.auth import get_current_user
from server.routes import profile_preferences


class _FakeDB:
    def __init__(self):
        self.rows: dict[str, dict[str, str]] = {}

    async def execute(self, query: str, *args):
        q = " ".join(query.split())
        if "INSERT INTO profiles" in q:
            user_id = str(args[0])
            self.rows.setdefault(
                user_id,
                {
                    "avatar_id": str(args[3]),
                    "avatar_palette": str(args[4]),
                    "dealer_skin_id": str(args[5]),
                    "theme": str(args[6]),
                },
            )
        return "OK"

    async def fetchrow(self, query: str, *args):
        q = " ".join(query.split())
        if "SELECT avatar_id, avatar_palette, dealer_skin_id, theme FROM profiles" in q:
            return self.rows.get(str(args[0]))
        if "UPDATE profiles" in q:
            user_id = str(args[0])
            row = self.rows.get(user_id)
            if not row:
                return None
            row["avatar_id"] = str(args[1])
            row["avatar_palette"] = str(args[2])
            row["dealer_skin_id"] = str(args[3])
            row["theme"] = str(args[4])
            return dict(row)
        raise AssertionError(f"Unexpected query: {q}")


def _client_for(
    monkeypatch: pytest.MonkeyPatch,
    *,
    db: _FakeDB | None = None,
    override_auth: bool = True,
) -> tuple[TestClient, _FakeDB]:
    fake_db = db or _FakeDB()
    monkeypatch.setattr(profile_preferences, "get_db", lambda: fake_db)
    monkeypatch.setattr(
        profile_preferences,
        "_load_manifest",
        lambda: {
            "dealer": [{"id": "ov_dealer_female_tux_v1"}],
            "users": [
                {"id": "ov_user_01", "palettes": ["default", "warm", "cool"]},
                {"id": "ov_user_02", "palettes": ["default"]},
            ],
        },
    )

    app = FastAPI()
    app.include_router(profile_preferences.router)
    if override_auth:
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u-1"}
    return TestClient(app), fake_db


def test_preferences_route_requires_auth(monkeypatch: pytest.MonkeyPatch):
    client, _ = _client_for(monkeypatch, override_auth=False)
    resp = client.get("/ui/profile/preferences")
    assert resp.status_code == 401


def test_get_preferences_bootstraps_defaults(monkeypatch: pytest.MonkeyPatch):
    client, _ = _client_for(monkeypatch)
    resp = client.get("/ui/profile/preferences")
    assert resp.status_code == 200
    body = resp.json()
    assert body["avatar_id"] == "ov_user_01"
    assert body["avatar_palette"] == "default"
    assert body["dealer_skin_id"] == "ov_dealer_female_tux_v1"
    assert body["theme"] == "light"


def test_patch_preferences_validates_whitelist_and_persists(monkeypatch: pytest.MonkeyPatch):
    client, db = _client_for(monkeypatch)
    _ = client.get("/ui/profile/preferences")

    resp = client.patch(
        "/ui/profile/preferences",
        json={
            "avatar_id": "ov_user_01",
            "avatar_palette": "warm",
            "dealer_skin_id": "ov_dealer_female_tux_v1",
            "theme": "dark",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["avatar_palette"] == "warm"
    assert body["theme"] == "dark"
    assert db.rows["u-1"]["avatar_palette"] == "warm"
    assert db.rows["u-1"]["theme"] == "dark"


def test_patch_preferences_rejects_unknown_avatar(monkeypatch: pytest.MonkeyPatch):
    client, _ = _client_for(monkeypatch)
    _ = client.get("/ui/profile/preferences")
    resp = client.patch("/ui/profile/preferences", json={"avatar_id": "unknown_avatar"})
    assert resp.status_code == 422
    assert "Unsupported avatar_id" in str(resp.json())


def test_patch_preferences_rejects_palette_for_avatar(monkeypatch: pytest.MonkeyPatch):
    client, _ = _client_for(monkeypatch)
    _ = client.get("/ui/profile/preferences")
    resp = client.patch(
        "/ui/profile/preferences",
        json={"avatar_id": "ov_user_02", "avatar_palette": "warm"},
    )
    assert resp.status_code == 422
    assert "Unsupported avatar_palette" in str(resp.json())


def test_patch_preferences_rejects_invalid_theme(monkeypatch: pytest.MonkeyPatch):
    client, _ = _client_for(monkeypatch)
    _ = client.get("/ui/profile/preferences")
    resp = client.patch("/ui/profile/preferences", json={"theme": "sepia"})
    assert resp.status_code == 422
    assert "Unsupported theme" in str(resp.json())
