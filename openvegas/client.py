"""HTTP client for communicating with OpenVegas backend."""

from __future__ import annotations

from decimal import Decimal
import json
from typing import Any, AsyncGenerator

import httpx

from openvegas.config import get_backend_url, get_bearer_token


class APIError(Exception):
    def __init__(self, status: int, detail: str, data: dict | None = None):
        self.status = status
        self.detail = detail
        self.data = data or {}
        super().__init__(f"API error {status}: {detail}")


class OpenVegasClient:
    """REST client for the OpenVegas backend."""

    def __init__(self):
        self.base_url = get_backend_url()
        self.token = get_bearer_token()

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=self._headers(),
                    **kwargs,
                )
                if resp.status_code >= 400:
                    detail = resp.text
                    data: dict | None = None
                    try:
                        body = resp.json()
                        if isinstance(body, dict):
                            data = body
                            detail = body.get("detail") or body.get("error") or resp.text
                    except Exception:
                        pass
                    raise APIError(resp.status_code, detail, data=data)
                return resp.json()
        except httpx.HTTPError as e:
            raise APIError(
                503,
                f"Backend request failed: {type(e).__name__}. Check server is running and reachable at {self.base_url}.",
            ) from e

    async def get_balance(self) -> dict:
        return await self._request("GET", "/wallet/balance")

    async def get_history(self) -> dict:
        return await self._request("GET", "/wallet/history")

    async def create_mint_challenge(
        self, amount_usd: float, provider: str, mode: str
    ) -> dict:
        return await self._request(
            "POST", "/mint/challenge",
            json={"amount_usd": amount_usd, "provider": provider, "mode": mode},
        )

    async def verify_mint(
        self, challenge_id: str, nonce: str, provider: str, model: str, api_key: str
    ) -> dict:
        return await self._request(
            "POST", "/mint/verify",
            json={
                "challenge_id": challenge_id,
                "nonce": nonce,
                "provider": provider,
                "model": model,
                "tier": "proxied",
                "api_key": api_key,
            },
        )

    async def play_game(self, game: str, bet: dict) -> dict:
        return await self._request("POST", f"/games/{game}/play", json=bet)

    async def play_game_demo(self, game: str, bet: dict) -> dict:
        return await self._request("POST", f"/games/{game}/play-demo", json=bet)

    async def create_horse_quote(
        self,
        *,
        bet_type: str,
        budget_v: Decimal | str,
        idempotency_key: str,
    ) -> dict:
        return await self._request(
            "POST",
            "/games/horse/quotes",
            json={
                "bet_type": bet_type,
                "budget_v": str(Decimal(str(budget_v))),
                "idempotency_key": idempotency_key,
            },
        )

    async def play_horse_quote(
        self,
        *,
        quote_id: str,
        horse: int,
        idempotency_key: str,
        demo_mode: bool = False,
    ) -> dict:
        payload = {
            "quote_id": quote_id,
            "horse": int(horse),
            "idempotency_key": idempotency_key,
        }
        path = "/games/horse/play-demo" if demo_mode else "/games/horse/play"
        return await self._request("POST", path, json=payload)

    async def ask(
        self,
        prompt: str,
        provider: str,
        model: str,
        *,
        idempotency_key: str | None = None,
        thread_id: str | None = None,
        conversation_mode: str | None = None,
        persist_context: bool | None = None,
        enable_tools: bool | None = None,
    ) -> dict:
        payload = {"prompt": prompt, "provider": provider, "model": model}
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key
        if thread_id:
            payload["thread_id"] = thread_id
        if conversation_mode:
            payload["conversation_mode"] = conversation_mode
        if persist_context is not None:
            payload["persist_context"] = bool(persist_context)
        if enable_tools is not None:
            payload["enable_tools"] = bool(enable_tools)
        return await self._request("POST", "/inference/ask", json=payload)

    async def get_mode(self) -> dict:
        return await self._request("GET", "/inference/mode")

    async def set_mode(
        self,
        *,
        llm_mode: str | None = None,
        conversation_mode: str | None = None,
    ) -> dict:
        payload: dict = {}
        if llm_mode is not None:
            payload["llm_mode"] = llm_mode
        if conversation_mode is not None:
            payload["conversation_mode"] = conversation_mode
        return await self._request("POST", "/inference/mode", json=payload)

    async def list_models(self, provider: str | None = None) -> dict:
        params = {}
        if provider:
            params["provider"] = provider
        return await self._request("GET", "/models", params=params)

    async def verify_game(self, game_id: str) -> dict:
        return await self._request("GET", f"/games/verify/{game_id}")

    async def verify_demo_game(self, game_id: str) -> dict:
        return await self._request("GET", f"/games/demo/verify/{game_id}")

    async def store_list(self) -> dict:
        return await self._request("GET", "/store/list")

    async def store_buy(self, item_id: str, idempotency_key: str | None = None) -> dict:
        payload: dict = {"item_id": item_id}
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key
        return await self._request("POST", "/store/buy", json=payload)

    async def store_grants(self) -> dict:
        return await self._request("GET", "/store/grants")

    async def create_topup_checkout(
        self,
        amount_usd: Decimal | str,
        idempotency_key: str | None = None,
    ) -> dict:
        payload: dict = {"amount_usd": str(amount_usd)}
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key
        return await self._request("POST", "/billing/topups/checkout", json=payload)

    async def suggest_topup(self, suggested_topup_usd: Decimal | str | None = None) -> dict:
        payload: dict[str, str] = {}
        if suggested_topup_usd is not None:
            payload["suggested_topup_usd"] = str(suggested_topup_usd)
        return await self._request("POST", "/billing/topups/suggest", json=payload)

    async def get_topup_status(self, topup_id: str) -> dict:
        return await self._request("GET", f"/billing/topups/{topup_id}")

    async def complete_fake_topup(self, topup_id: str) -> dict:
        return await self._request(
            "POST",
            "/billing/webhook/fake/complete",
            json={"topup_id": str(topup_id)},
        )

    async def human_casino_start_session(
        self,
        *,
        max_loss_v: Decimal | str,
        max_rounds: int,
        idempotency_key: str,
    ) -> dict:
        return await self._request(
            "POST",
            "/casino/human/sessions/start",
            json={
                "max_loss_v": float(Decimal(str(max_loss_v))),
                "max_rounds": int(max_rounds),
                "idempotency_key": idempotency_key,
            },
        )

    async def human_casino_list_games(self) -> dict:
        return await self._request("GET", "/casino/human/games")

    async def human_casino_start_round(
        self,
        *,
        casino_session_id: str,
        game_code: str,
        wager_v: Decimal | str,
        idempotency_key: str,
    ) -> dict:
        return await self._request(
            "POST",
            "/casino/human/rounds/start",
            json={
                "casino_session_id": casino_session_id,
                "game_code": game_code,
                "wager_v": float(Decimal(str(wager_v))),
                "idempotency_key": idempotency_key,
            },
        )

    async def human_casino_action(
        self,
        *,
        round_id: str,
        action: str,
        payload: dict,
        idempotency_key: str,
    ) -> dict:
        return await self._request(
            "POST",
            f"/casino/human/rounds/{round_id}/action",
            json={
                "action": action,
                "payload": payload,
                "idempotency_key": idempotency_key,
            },
        )

    async def human_casino_resolve(self, *, round_id: str, idempotency_key: str) -> dict:
        return await self._request(
            "POST",
            f"/casino/human/rounds/{round_id}/resolve",
            json={"idempotency_key": idempotency_key},
        )

    async def human_casino_verify(self, round_id: str) -> dict:
        return await self._request("GET", f"/casino/human/rounds/{round_id}/verify")

    async def human_casino_get_session(self, session_id: str) -> dict:
        return await self._request("GET", f"/casino/human/sessions/{session_id}")

    async def human_casino_demo_autoplay(
        self,
        *,
        casino_session_id: str,
        game_code: str,
        wager_v: Decimal | str,
        idempotency_key: str,
    ) -> dict:
        return await self._request(
            "POST",
            "/casino/human/rounds/demo-autoplay",
            json={
                "casino_session_id": casino_session_id,
                "game_code": game_code,
                "wager_v": float(Decimal(str(wager_v))),
                "idempotency_key": idempotency_key,
            },
        )

    async def agent_run_create(
        self,
        *,
        state: str = "running",
        is_resumable: bool = False,
        expires_in_seconds: int | None = None,
    ) -> dict:
        payload: dict = {"state": state, "is_resumable": bool(is_resumable)}
        if expires_in_seconds is not None:
            payload["expires_in_seconds"] = int(expires_in_seconds)
        return await self._request("POST", "/agent/runs", json=payload)

    async def agent_run_get(self, run_id: str) -> dict:
        return await self._request("GET", f"/agent/runs/{run_id}")

    async def agent_run_transition(
        self,
        *,
        run_id: str,
        action: str,
        expected_run_version: int,
        expected_valid_actions_signature: str,
        idempotency_key: str,
        payload: dict | None = None,
    ) -> dict:
        return await self._request(
            "POST",
            f"/agent/runs/{run_id}/transition",
            json={
                "action": action,
                "payload": payload or {},
                "expected_run_version": int(expected_run_version),
                "expected_valid_actions_signature": expected_valid_actions_signature,
                "idempotency_key": idempotency_key,
            },
        )

    async def agent_run_cancel(
        self,
        *,
        run_id: str,
        expected_run_version: int,
        expected_valid_actions_signature: str,
        idempotency_key: str,
    ) -> dict:
        return await self._request(
            "POST",
            f"/agent/runs/{run_id}/cancel",
            json={
                "expected_run_version": int(expected_run_version),
                "expected_valid_actions_signature": expected_valid_actions_signature,
                "idempotency_key": idempotency_key,
            },
        )

    async def agent_run_handoff_check(self, *, run_id: str) -> dict:
        return await self._request("POST", f"/agent/runs/{run_id}/ui/handoff-check", json={})

    async def agent_register_workspace(
        self,
        *,
        run_id: str,
        runtime_session_id: str,
        workspace_root: str,
        workspace_fingerprint: str,
        git_root: str | None = None,
    ) -> dict:
        payload: dict = {
            "runtime_session_id": runtime_session_id,
            "workspace_root": workspace_root,
            "workspace_fingerprint": workspace_fingerprint,
        }
        if git_root:
            payload["git_root"] = git_root
        return await self._request(
            "POST",
            f"/agent/runs/{run_id}/session/register-workspace",
            json=payload,
        )

    async def agent_tool_propose(
        self,
        *,
        run_id: str,
        runtime_session_id: str,
        expected_run_version: int,
        expected_valid_actions_signature: str,
        idempotency_key: str,
        tool_name: str,
        arguments: dict,
        shell_mode: str | None = None,
        timeout_sec: int | None = None,
        plan_mode: bool = False,
    ) -> dict:
        payload: dict = {
            "runtime_session_id": runtime_session_id,
            "expected_run_version": int(expected_run_version),
            "expected_valid_actions_signature": expected_valid_actions_signature,
            "idempotency_key": idempotency_key,
            "tool_name": tool_name,
            "arguments": arguments,
            "plan_mode": bool(plan_mode),
        }
        if shell_mode is not None:
            payload["shell_mode"] = shell_mode
        if timeout_sec is not None:
            payload["timeout_sec"] = int(timeout_sec)
        return await self._request("POST", f"/agent/runs/{run_id}/tools/propose", json=payload)

    async def agent_tool_start(
        self,
        *,
        run_id: str,
        runtime_session_id: str,
        tool_call_id: str,
        execution_token: str,
        expected_run_version: int,
        expected_valid_actions_signature: str,
        idempotency_key: str,
    ) -> dict:
        return await self._request(
            "POST",
            f"/agent/runs/{run_id}/tools/start",
            json={
                "runtime_session_id": runtime_session_id,
                "tool_call_id": tool_call_id,
                "execution_token": execution_token,
                "expected_run_version": int(expected_run_version),
                "expected_valid_actions_signature": expected_valid_actions_signature,
                "idempotency_key": idempotency_key,
            },
        )

    async def agent_tool_heartbeat(
        self,
        *,
        run_id: str,
        runtime_session_id: str,
        tool_call_id: str,
        execution_token: str,
    ) -> dict:
        return await self._request(
            "POST",
            f"/agent/runs/{run_id}/tools/heartbeat",
            json={
                "runtime_session_id": runtime_session_id,
                "tool_call_id": tool_call_id,
                "execution_token": execution_token,
            },
        )

    async def agent_tool_result(
        self,
        *,
        run_id: str,
        runtime_session_id: str,
        tool_call_id: str,
        execution_token: str,
        result_status: str,
        result_payload: dict,
        stdout: str = "",
        stderr: str = "",
        stdout_truncated: bool = False,
        stderr_truncated: bool = False,
        stdout_sha256: str | None = None,
        stderr_sha256: str | None = None,
        result_submission_hash: str | None = None,
    ) -> dict:
        payload: dict[str, Any] = {
            "runtime_session_id": runtime_session_id,
            "tool_call_id": tool_call_id,
            "execution_token": execution_token,
            "result_status": result_status,
            "result_payload": result_payload,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": bool(stdout_truncated),
            "stderr_truncated": bool(stderr_truncated),
        }
        if stdout_sha256 is not None:
            payload["stdout_sha256"] = stdout_sha256
        if stderr_sha256 is not None:
            payload["stderr_sha256"] = stderr_sha256
        if result_submission_hash is not None:
            payload["result_submission_hash"] = result_submission_hash
        return await self._request(
            "POST",
            f"/agent/runs/{run_id}/tools/result",
            json=payload,
        )

    async def agent_tool_cancel(
        self,
        *,
        run_id: str,
        runtime_session_id: str,
        tool_call_id: str,
        execution_token: str,
    ) -> dict:
        return await self._request(
            "POST",
            f"/agent/runs/{run_id}/tools/{tool_call_id}/cancel",
            json={
                "runtime_session_id": runtime_session_id,
                "execution_token": execution_token,
            },
        )

    async def ide_register_bridge(
        self,
        *,
        run_id: str,
        runtime_session_id: str,
        actor_id: str,
        ide_type: str,
        workspace_root: str,
        workspace_fingerprint: str,
    ) -> dict:
        return await self._request(
            "POST",
            "/ide/register",
            json={
                "run_id": run_id,
                "runtime_session_id": runtime_session_id,
                "actor_id": actor_id,
                "ide_type": ide_type,
                "workspace_root": workspace_root,
                "workspace_fingerprint": workspace_fingerprint,
            },
        )

    async def ide_open_file(
        self,
        *,
        run_id: str,
        runtime_session_id: str,
        path: str,
        line: int | None = None,
        col: int | None = None,
    ) -> dict:
        payload: dict = {
            "run_id": run_id,
            "runtime_session_id": runtime_session_id,
            "path": path,
        }
        if line is not None:
            payload["line"] = int(line)
        if col is not None:
            payload["col"] = int(col)
        return await self._request("POST", "/ide/open-file", json=payload)

    async def ide_run_command(
        self,
        *,
        run_id: str,
        runtime_session_id: str,
        command: str,
        terminal_name: str | None = None,
    ) -> dict:
        payload: dict = {
            "run_id": run_id,
            "runtime_session_id": runtime_session_id,
            "command": command,
        }
        if terminal_name:
            payload["terminal_name"] = terminal_name
        return await self._request("POST", "/ide/run-command", json=payload)

    async def ide_show_diff(
        self,
        *,
        run_id: str,
        runtime_session_id: str,
        path: str,
        new_contents: str,
        allow_partial_accept: bool = True,
    ) -> dict:
        return await self._request(
            "POST",
            "/ide/show-diff",
            json={
                "run_id": run_id,
                "runtime_session_id": runtime_session_id,
                "path": path,
                "new_contents": new_contents,
                "allow_partial_accept": bool(allow_partial_accept),
            },
        )

    async def ide_message(
        self,
        *,
        request_id: str,
        method: str,
        params: dict[str, Any],
    ) -> dict:
        return await self._request(
            "POST",
            "/ide/message",
            json={
                "id": request_id,
                "type": "request",
                "method": method,
                "params": params,
            },
        )

    async def ide_get_context(self, *, run_id: str, runtime_session_id: str) -> dict:
        return await self._request(
            "POST",
            "/ide/context",
            json={"run_id": run_id, "runtime_session_id": runtime_session_id},
        )

    async def stream_tool_output(
        self,
        *,
        run_id: str,
        tool_call_id: str,
    ) -> AsyncGenerator[dict[str, Any], None]:
        url = f"{self.base_url}/agent/runs/{run_id}/tools/{tool_call_id}/stream"
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", url, headers=self._headers()) as resp:
                if resp.status_code >= 400:
                    detail = await resp.aread()
                    raise APIError(resp.status_code, detail.decode("utf-8", errors="ignore"))
                async for line in resp.aiter_lines():
                    raw = (line or "").strip()
                    if not raw.startswith("data:"):
                        continue
                    payload = raw[5:].strip()
                    if not payload:
                        continue
                    try:
                        data = json.loads(payload)
                    except Exception:
                        continue
                    if isinstance(data, dict):
                        yield data

    async def ide_stream_events(
        self,
        *,
        run_id: str,
        runtime_session_id: str,
    ) -> AsyncGenerator[dict[str, Any], None]:
        url = (
            f"{self.base_url}/ide/events/stream"
            f"?run_id={run_id}&runtime_session_id={runtime_session_id}"
        )
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", url, headers=self._headers()) as resp:
                if resp.status_code >= 400:
                    detail = await resp.aread()
                    raise APIError(resp.status_code, detail.decode("utf-8", errors="ignore"))
                async for line in resp.aiter_lines():
                    raw = (line or "").strip()
                    if not raw.startswith("data:"):
                        continue
                    payload = raw[5:].strip()
                    if not payload:
                        continue
                    try:
                        data = json.loads(payload)
                    except Exception:
                        continue
                    if isinstance(data, dict):
                        yield data
