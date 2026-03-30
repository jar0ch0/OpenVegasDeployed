from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.middleware.auth import get_current_user
from server.routes import payments as payment_routes


class _FakeBillingService:
    def __init__(self):
        self.calls: list[tuple[str, int]] = []

    async def list_activity_history(self, *, user_id: str, limit: int = 50) -> dict:
        self.calls.append((user_id, limit))
        return {
            "entries": [
                {
                    "time": "2026-03-30T12:00:00+00:00",
                    "type": "gameplay",
                    "status": "won",
                    "amount_usd": None,
                    "amount_v": "50.000000",
                    "amount_v_2dp": "50.00",
                    "reference_id": "r1",
                    "game_code": "roulette",
                    "source": "human_casino",
                }
            ],
            "conversion": {"v_per_usd": "100.000000", "usd_per_v": "0.01"},
        }


def _app(fake: _FakeBillingService) -> FastAPI:
    app = FastAPI()
    app.include_router(payment_routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u-test"}
    payment_routes.get_billing_service = lambda: fake
    return app


def test_billing_activity_route_returns_normalized_shape_and_scopes_user():
    fake = _FakeBillingService()
    client = TestClient(_app(fake))

    response = client.get("/billing/activity?limit=7")

    assert response.status_code == 200
    payload = response.json()
    assert "entries" in payload
    assert "conversion" in payload
    assert payload["entries"][0]["type"] == "gameplay"
    assert payload["entries"][0]["status"] == "won"
    assert fake.calls == [("u-test", 7)]
