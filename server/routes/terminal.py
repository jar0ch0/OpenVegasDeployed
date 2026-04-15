"""WebSocket terminal bridge — wss://app.openvegas.ai/ws/terminal

Spawns a PTY running the OpenVegas CLI agent loop. Bi-directionally pipes:
  browser keystrokes → PTY stdin
  PTY stdout (ANSI/Ink) → WebSocket → xterm.js

GUEST MODE INTEGRATION
──────────────────────
  Unauthenticated connections resolve to a GuestSession (see guest_session.py).
  When the guest's $V balance hits 0, this endpoint sends a SYSTEM_LOCK
  control message that freezes the xterm.js UI and prompts authentication.

WIRE PROTOCOL
─────────────
  Browser → Server (text frames):
    { "type": "input",   "data": "<keystrokes>" }
    { "type": "resize",  "cols": 120, "rows": 40 }
    { "type": "ping" }

  Server → Browser (text frames):
    { "type": "output",       "data": "<ANSI bytes, base64-encoded>" }
    { "type": "SYSTEM_LOCK",  "reason": "guest_balance_exhausted",
      "message": "Create a free account to continue." }
    { "type": "session_info", "session_id": "...", "balance_v": 50 }
    { "type": "balance_update","remaining_v": 42 }
    { "type": "pong" }
    { "type": "error",        "message": "..." }

PTY MANAGEMENT
──────────────
  Uses asyncio + os.openpty() for non-blocking PTY I/O.
  Each WebSocket connection gets its own PTY + agent subprocess.
  Subprocess: openvegas chat --session-id=<ws_session_id>
  If the binary is not installed, falls back to a demo echo loop.

RESIZE EVENTS
─────────────
  The client sends { "type": "resize", "cols": N, "rows": M } on
  every window resize. Server calls fcntl.ioctl(fd, TIOCSWINSZ, ...).
"""

from __future__ import annotations

import asyncio
import base64
import fcntl
import json
import logging
import os
import pty
import signal
import struct
import termios
import uuid
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from server.middleware.guest_session import GuestSession, resolve_terminal_session
from server.services.dependencies import get_redis

logger = logging.getLogger(__name__)
router = APIRouter()

# Env var or fall back to discovering the binary on PATH
OPENVEGAS_BIN = os.getenv("OPENVEGAS_BIN", "openvegas")
MAX_READ_BYTES = 4096
HEARTBEAT_INTERVAL = 20   # seconds between server-initiated pings


# ─── PTY process ──────────────────────────────────────────────────────────────

class PtyProcess:
    """Wraps a subprocess running in a PTY."""

    def __init__(self, pid: int, fd: int):
        self.pid = pid
        self.fd  = fd
        self._exited = False

    def resize(self, cols: int, rows: int) -> None:
        try:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass

    def write(self, data: bytes) -> None:
        if self._exited:
            return
        try:
            os.write(self.fd, data)
        except OSError:
            self._exited = True

    async def read(self) -> bytes | None:
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, lambda: os.read(self.fd, MAX_READ_BYTES))
        except OSError:
            self._exited = True
            return None

    def terminate(self) -> None:
        if self._exited:
            return
        self._exited = True
        try:
            os.kill(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        # Reap the zombie.  os.fork() children become zombies (defunct entries
        # in the process table) until the parent calls waitpid().  On a busy
        # Railway instance with many WebSocket connections this accumulates into
        # a resource leak.  WNOHANG lets us reap without blocking if the child
        # hasn't exited yet — we've already sent SIGTERM so it will exit soon
        # and the OS will clean it up at the next GC pass.
        try:
            os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            pass


def _spawn_pty(session_id: str, cols: int, rows: int) -> PtyProcess:
    """Fork a PTY subprocess running the OpenVegas CLI."""
    master_fd, slave_fd = pty.openpty()

    # Set initial window size
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)

    pid = os.fork()
    if pid == 0:
        # ── Child: become the PTY slave ──────────────────────────────────────
        os.close(master_fd)
        os.setsid()
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

        os.dup2(slave_fd, 0)   # stdin
        os.dup2(slave_fd, 1)   # stdout
        os.dup2(slave_fd, 2)   # stderr
        if slave_fd > 2:
            os.close(slave_fd)

        os.environ["TERM"]       = "xterm-256color"
        os.environ["COLORTERM"]  = "truecolor"
        os.environ["OV_WEB_SESSION"] = session_id

        # Prefer the installed binary; fall back to demo
        try:
            os.execvp(OPENVEGAS_BIN, [OPENVEGAS_BIN, "chat", f"--session-id={session_id}"])
        except FileNotFoundError:
            # Demo mode: echo everything back
            os.execvp("python3", ["python3", "-c",
                "import sys, time\n"
                "print('\\x1b[1;32mOpenVegas demo mode\\x1b[0m')\n"
                "print('Binary not found — install at app.openvegas.ai/install')\n"
                "sys.stdout.flush()\n"
                "while True:\n"
                "    line = sys.stdin.readline()\n"
                "    if not line: break\n"
                "    sys.stdout.write(f'> {line}')\n"
                "    sys.stdout.flush()\n"
            ])
        os._exit(1)

    # ── Parent ────────────────────────────────────────────────────────────────
    os.close(slave_fd)
    return PtyProcess(pid=pid, fd=master_fd)


# ─── WebSocket handler ────────────────────────────────────────────────────────

async def _send(ws: WebSocket, msg: dict[str, Any]) -> bool:
    """Send a JSON control frame; returns False if the socket is closed."""
    if ws.client_state != WebSocketState.CONNECTED:
        return False
    try:
        await ws.send_text(json.dumps(msg))
        return True
    except Exception:
        return False


@router.websocket("/ws/terminal")
async def terminal_ws(
    ws: WebSocket,
    token: str = Query(default=""),    # JWT from query param (xterm.js sends it here)
    cols:  int = Query(default=80),
    rows:  int = Query(default=24),
):
    await ws.accept()

    # ── Auth / guest session resolution ───────────────────────────────────────
    session: GuestSession = await resolve_terminal_session(token, ws, get_redis())

    ws_session_id = str(uuid.uuid4())
    await _send(ws, {
        "type":       "session_info",
        "session_id": ws_session_id,
        "balance_v":  session.balance_v,
        "guest":      session.is_guest,
    })

    # ── Spawn PTY ─────────────────────────────────────────────────────────────
    pty_proc = _spawn_pty(ws_session_id, cols=cols, rows=rows)

    async def pty_reader():
        """Streams PTY output to the WebSocket."""
        while True:
            data = await pty_proc.read()
            if data is None:
                await _send(ws, {"type": "error", "message": "Terminal process exited"})
                break
            encoded = base64.b64encode(data).decode()
            if not await _send(ws, {"type": "output", "data": encoded}):
                break

            # Guest balance drain: debit 1 $V per 10KB of output
            if session.is_guest and len(data) > 0:
                drained = await session.drain(get_redis(), cost_v=len(data) / 10_240)
                if drained <= 0:
                    await _send(ws, {
                        "type":    "SYSTEM_LOCK",
                        "reason":  "guest_balance_exhausted",
                        "message": "Create a free account to keep going — it takes 10 seconds.",
                    })
                    break
                elif drained < 10:
                    await _send(ws, {"type": "balance_update", "remaining_v": round(drained, 2)})

    async def ws_reader():
        """Forwards browser input to the PTY."""
        async for raw in ws.iter_text():
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            kind = msg.get("type", "")
            if kind == "input":
                data = str(msg.get("data", "")).encode("utf-8", errors="replace")
                pty_proc.write(data)
            elif kind == "resize":
                c = int(msg.get("cols", cols))
                r = int(msg.get("rows", rows))
                pty_proc.resize(c, r)
            elif kind == "ping":
                await _send(ws, {"type": "pong"})

    async def heartbeat():
        """Sends periodic pings to keep Railway's 60s idle timeout from closing the socket."""
        while ws.client_state == WebSocketState.CONNECTED:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            await _send(ws, {"type": "pong"})

    try:
        await asyncio.gather(
            pty_reader(),
            ws_reader(),
            heartbeat(),
            return_exceptions=True,
        )
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        pty_proc.terminate()
        try:
            await ws.close()
        except Exception:
            pass
