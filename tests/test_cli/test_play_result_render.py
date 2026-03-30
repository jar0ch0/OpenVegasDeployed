from __future__ import annotations

from click.testing import CliRunner

from openvegas.cli import cli


class _ClientWin:
    async def play_game(self, _game: str, _payload: dict) -> dict:
        return {
            "game_id": "g-win-1",
            "bet_amount": "1",
            "payout": "2.5",
            "net": "1.5",
            "server_seed_hash": "seed-win",
            "provably_fair": True,
            "outcome_data": {},
        }


class _ClientLoss:
    async def play_game(self, _game: str, _payload: dict) -> dict:
        return {
            "game_id": "g-loss-1",
            "bet_amount": "1",
            "payout": "0",
            "net": "-1",
            "server_seed_hash": "seed-loss",
            "provably_fair": True,
            "outcome_data": {},
        }


def test_play_win_uses_shared_result_panel(monkeypatch):
    calls: dict = {}

    def _fake_render_result(_console, content, *, is_win: bool, animation_enabled: bool, title: str):
        calls["is_win"] = is_win
        calls["animation_enabled"] = animation_enabled
        calls["content"] = content
        calls["title"] = title

    monkeypatch.setattr("openvegas.client.OpenVegasClient", _ClientWin)
    monkeypatch.setattr("openvegas.cli.render_result_panel", _fake_render_result)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {"animation": True})

    runner = CliRunner()
    result = runner.invoke(cli, ["play", "skillshot", "--stake", "50", "--no-render"])

    assert result.exit_code == 0
    assert calls["is_win"] is True
    assert calls["animation_enabled"] is True
    assert calls["title"] == "Result"
    assert "Won 2.5" in calls["content"]


def test_play_loss_uses_plain_result_panel_path(monkeypatch):
    calls: dict = {}

    def _fake_render_result(_console, content, *, is_win: bool, animation_enabled: bool, title: str):
        calls["is_win"] = is_win
        calls["animation_enabled"] = animation_enabled
        calls["content"] = content
        calls["title"] = title

    monkeypatch.setattr("openvegas.client.OpenVegasClient", _ClientLoss)
    monkeypatch.setattr("openvegas.cli.render_result_panel", _fake_render_result)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {"animation": True})

    runner = CliRunner()
    result = runner.invoke(cli, ["play", "skillshot", "--stake", "50", "--no-render"])

    assert result.exit_code == 0
    assert calls["is_win"] is False
    assert calls["title"] == "Result"
    assert "Lost 1" in calls["content"]
