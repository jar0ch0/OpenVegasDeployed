from __future__ import annotations

import io
import inspect
from decimal import Decimal
from click.testing import CliRunner
import pytest
from rich.console import Console

from openvegas.cli import cli
from openvegas.client import OpenVegasClient
from openvegas.tui import chat_renderer


class _FakeTopupHintClient:
    instances: list["_FakeTopupHintClient"] = []
    balance_sequence: list[str] = ["200.000000", "200.000000"]
    status_sequence: list[str] = ["checkout_created"]

    def __init__(self):
        self.thread_id = "thread-topup"
        self.run_id = "run-topup"
        self.run_version = 0
        self.signature = "sha256:" + ("a" * 64)
        self.get_balance_calls = 0
        self.get_topup_status_calls = 0
        self.suggest_topup_calls = 0
        self._balance_idx = 0
        self._status_idx = 0
        _FakeTopupHintClient.instances.append(self)

    @classmethod
    def configure(cls, *, balances: list[str], statuses: list[str]) -> None:
        cls.instances.clear()
        cls.balance_sequence = list(balances)
        cls.status_sequence = list(statuses)

    async def get_mode(self):
        return {"conversation_mode": "persistent"}

    async def agent_run_create(self, **_kwargs):
        return {
            "run_id": self.run_id,
            "run_version": self.run_version,
            "valid_actions_signature": self.signature,
        }

    async def agent_register_workspace(self, **_kwargs):
        return {"ok": True}

    async def ide_get_context(self, **_kwargs):
        raise RuntimeError("no ide bridge")

    async def ask(self, prompt, _provider, _model, **kwargs):
        _ = prompt
        if kwargs.get("enable_tools"):
            return {"thread_id": self.thread_id, "text": "Done.", "v_cost": "0.01", "tool_calls": []}
        return {"thread_id": self.thread_id, "text": "Done.", "v_cost": "0.01"}

    async def get_balance(self) -> dict:
        self.get_balance_calls += 1
        idx = min(self._balance_idx, len(self.balance_sequence) - 1)
        self._balance_idx += 1
        value = self.balance_sequence[idx]
        # Keep both shapes to detect accidental client/CLI contract drift.
        return {"balance": value, "balance_v": value}

    async def suggest_topup(self, suggested_topup_usd: Decimal | str | None = None) -> dict:
        _ = suggested_topup_usd
        self.suggest_topup_calls += 1
        topup_id = f"topup_{self.suggest_topup_calls}"
        return {
            "low_balance": True,
            "balance_v": "200.000000",
            "balance_usd_equiv": "2.00",
            "low_balance_floor_usd": "5.00",
            "suggested_topup_usd": "20.00",
            "topup_id": topup_id,
            "status": "checkout_created",
            "mode": "simulated",
            "checkout_url": f"https://checkout.openvegas.local/topup/{topup_id}",
            "qr_value": f"https://checkout.openvegas.local/topup/{topup_id}",
            "payment_methods_display": ["Card", "PayPal", "Apple Pay", "Alipay"],
        }

    async def get_topup_status(self, topup_id: str) -> dict:
        _ = topup_id
        self.get_topup_status_calls += 1
        idx = min(self._status_idx, len(self.status_sequence) - 1)
        self._status_idx += 1
        return {"topup_id": "topup_1", "status": self.status_sequence[idx]}


def _run_chat_script(monkeypatch, tmp_path, scripted_inputs: list[str]):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("openvegas.client.OpenVegasClient", _FakeTopupHintClient)
    monkeypatch.setattr("openvegas.cli.load_config", lambda: {})
    monkeypatch.setenv("TOPUP_LOW_BALANCE_FLOOR_USD", "5.00")
    monkeypatch.setenv("V_PER_USD", "100")
    monkeypatch.setenv("TOPUP_SUGGEST_COOLDOWN_SEC", "300")
    items = iter(scripted_inputs)
    monkeypatch.setattr("openvegas.cli.Prompt.ask", lambda *_args, **_kwargs: next(items))
    runner = CliRunner()
    return runner.invoke(cli, ["chat"])


def test_cli_low_balance_hint_shown_once_for_reused_pending_topup(monkeypatch, tmp_path):
    _FakeTopupHintClient.configure(
        balances=["200.000000", "200.000000"],
        statuses=["checkout_created"],
    )
    result = _run_chat_script(
        monkeypatch,
        tmp_path,
        ["hello", "second turn no repeat", "/exit"],
    )
    assert result.exit_code == 0, result.output
    assert result.output.count("Low balance") == 1
    assert "https://checkout.openvegas.local/topup/topup_1" in result.output
    assert "topup_2" not in result.output

    inst = _FakeTopupHintClient.instances[-1]
    assert inst.get_balance_calls == 2
    assert inst.get_topup_status_calls == 1
    assert inst.suggest_topup_calls == 1


@pytest.mark.parametrize("wake_status", ["paid", "expired", "failed", "manual_reconciliation_required"])
def test_cli_status_change_wakeup_triggers_new_suggestion(monkeypatch, tmp_path, wake_status: str):
    _FakeTopupHintClient.configure(
        balances=["200.000000", "200.000000"],
        statuses=[wake_status],
    )
    result = _run_chat_script(
        monkeypatch,
        tmp_path,
        ["first", "second after paid wakeup", "/exit"],
    )
    assert result.exit_code == 0, result.output
    assert result.output.count("Low balance") == 2
    assert "https://checkout.openvegas.local/topup/topup_1" in result.output
    assert "https://checkout.openvegas.local/topup/topup_2" in result.output

    inst = _FakeTopupHintClient.instances[-1]
    assert inst.get_balance_calls == 2
    assert inst.get_topup_status_calls == 1
    assert inst.suggest_topup_calls == 2


def test_cli_above_floor_shows_no_hint_and_no_suggestion_call(monkeypatch, tmp_path):
    _FakeTopupHintClient.configure(
        balances=["900.000000", "900.000000"],
        statuses=["checkout_created"],
    )
    result = _run_chat_script(
        monkeypatch,
        tmp_path,
        ["hello", "still above floor", "/exit"],
    )
    assert result.exit_code == 0, result.output
    assert "Low balance" not in result.output

    inst = _FakeTopupHintClient.instances[-1]
    assert inst.get_balance_calls == 2
    assert inst.suggest_topup_calls == 0


def test_render_topup_hint_qr_rendered_when_tty_and_width_fit(monkeypatch):
    class _TTY:
        @staticmethod
        def isatty() -> bool:
            return True

    monkeypatch.setattr(chat_renderer.sys, "stdout", _TTY())
    monkeypatch.setattr(chat_renderer, "qr_width", lambda _value, border=0: 10)
    monkeypatch.setattr(chat_renderer, "qr_half_block", lambda _value, border=0: "QRLINE1\nQRLINE2")
    console = Console(file=io.StringIO(), record=True, width=120, force_terminal=False)
    chat_renderer.render_topup_hint(
        console,
        {
            "balance_v": "200.000000",
            "suggested_topup_usd": "20.00",
            "checkout_url": "https://checkout.openvegas.local/topup/topup_1",
            "qr_value": "https://checkout.openvegas.local/topup/topup_1",
            "mode": "simulated",
            "payment_methods_display": ["Card"],
        },
    )
    out = console.export_text()
    assert "QRLINE1" in out


def test_render_topup_hint_qr_skipped_when_terminal_too_narrow(monkeypatch):
    class _TTY:
        @staticmethod
        def isatty() -> bool:
            return True

    monkeypatch.setattr(chat_renderer.sys, "stdout", _TTY())
    monkeypatch.setattr(chat_renderer, "qr_width", lambda _value, border=0: 10_000)
    monkeypatch.setattr(chat_renderer, "qr_half_block", lambda _value, border=0: "QRLINE1\nQRLINE2")
    console = Console(file=io.StringIO(), record=True, width=60, force_terminal=False)
    chat_renderer.render_topup_hint(
        console,
        {
            "balance_v": "200.000000",
            "suggested_topup_usd": "20.00",
            "checkout_url": "https://checkout.openvegas.local/topup/topup_1",
            "qr_value": "https://checkout.openvegas.local/topup/topup_1",
            "mode": "simulated",
            "payment_methods_display": ["Card"],
        },
    )
    out = console.export_text()
    assert "QRLINE1" not in out


def test_cli_fake_client_signatures_match_real_client_contract():
    assert inspect.signature(_FakeTopupHintClient.get_balance) == inspect.signature(OpenVegasClient.get_balance)
    assert inspect.signature(_FakeTopupHintClient.suggest_topup) == inspect.signature(OpenVegasClient.suggest_topup)
    assert inspect.signature(_FakeTopupHintClient.get_topup_status) == inspect.signature(
        OpenVegasClient.get_topup_status
    )


def test_render_topup_hint_signature_is_stable():
    sig = inspect.signature(chat_renderer.render_topup_hint)
    assert tuple(sig.parameters.keys()) == ("console", "hint")
