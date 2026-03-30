from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.middleware.auth import get_current_user
from server.routes import profile_preferences


class _Db:
    def __init__(self):
        self.row = None

    async def execute(self, query: str, *args):
        if "INSERT INTO profiles" in " ".join(query.split()):
            if self.row is None:
                self.row = {
                    "avatar_id": str(args[3]),
                    "avatar_palette": str(args[4]),
                    "dealer_skin_id": str(args[5]),
                    "theme": str(args[6]),
                }
        return "OK"

    async def fetchrow(self, query: str, *args):
        q = " ".join(query.split())
        if "SELECT avatar_id" in q:
            return self.row
        if "UPDATE profiles" in q and self.row is not None:
            self.row = {
                "avatar_id": str(args[1]),
                "avatar_palette": str(args[2]),
                "dealer_skin_id": str(args[3]),
                "theme": str(args[4]),
            }
            return self.row
        return self.row


def test_avatar_profile_persistence_read_after_write(monkeypatch):
    db = _Db()
    monkeypatch.setattr(profile_preferences, "get_db", lambda: db)
    monkeypatch.setattr(
        profile_preferences,
        "_load_manifest",
        lambda: {
            "dealer": [{"id": "ov_dealer_female_tux_v1"}],
            "users": [{"id": "ov_user_01", "palettes": ["default", "warm"]}],
        },
    )

    app = FastAPI()
    app.include_router(profile_preferences.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u-e2e"}
    client = TestClient(app)

    before = client.get("/ui/profile/preferences")
    assert before.status_code == 200

    patch = client.patch(
        "/ui/profile/preferences",
        json={"avatar_id": "ov_user_01", "avatar_palette": "warm", "dealer_skin_id": "ov_dealer_female_tux_v1", "theme": "dark"},
    )
    assert patch.status_code == 200

    after = client.get("/ui/profile/preferences")
    assert after.status_code == 200
    assert after.json()["avatar_palette"] == "warm"
    assert after.json()["theme"] == "dark"
