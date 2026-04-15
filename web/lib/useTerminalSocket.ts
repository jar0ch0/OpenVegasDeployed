/**
 * useTerminalSocket.ts
 *
 * WebSocket hook that connects the xterm.js terminal to the Railway PTY bridge.
 *
 * WIRE PROTOCOL (matches server/routes/terminal.py)
 * ──────────────────────────────────────────────────
 *   Send (browser → server):
 *     { type: "input",  data: "<keystroke bytes>" }
 *     { type: "resize", cols: N, rows: M }
 *     { type: "ping" }
 *
 *   Receive (server → browser):
 *     { type: "output",       data: "<base64 ANSI bytes>" }
 *     { type: "SYSTEM_LOCK",  reason: "...", message: "..." }
 *     { type: "session_info", session_id, balance_v, guest }
 *     { type: "balance_update", remaining_v }
 *     { type: "pong" }
 *     { type: "error", message: "..." }
 *
 * RECONNECT
 * ─────────
 *   Exponential back-off up to 30s. Does NOT reconnect on SYSTEM_LOCK.
 *   Guest sessions are not reconnected after balance exhaustion.
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import type { Terminal } from '@xterm/xterm';

const WS_BASE = process.env['NEXT_PUBLIC_WS_URL'] ?? 'wss://app.openvegas.ai';
const RECONNECT_BASE_MS  = 1_000;
const RECONNECT_MAX_MS   = 30_000;
const RECONNECT_FACTOR   = 2;

export interface SessionInfo {
  sessionId: string;
  balanceV:  number;
  isGuest:   boolean;
}

export interface SystemLock {
  reason:  string;
  message: string;
}

export interface UseTerminalSocketOptions {
  terminal:     Terminal | null;
  token:        string;                        // JWT; empty string → guest mode
  fingerprint?: string;                        // Browser fingerprint for guest rate-limit
  cols?:        number;
  rows?:        number;
  onSessionInfo?: (info: SessionInfo) => void;
  onSystemLock?:  (lock: SystemLock) => void;
  onBalanceUpdate?: (remainingV: number) => void;
}

export function useTerminalSocket({
  terminal,
  token,
  fingerprint = '',
  cols = 80,
  rows = 24,
  onSessionInfo,
  onSystemLock,
  onBalanceUpdate,
}: UseTerminalSocketOptions): {
  connected: boolean;
  sendInput: (data: string) => void;
  sendResize: (cols: number, rows: number) => void;
} {
  const wsRef            = useRef<WebSocket | null>(null);
  const reconnectDelay   = useRef(RECONNECT_BASE_MS);
  const lockedRef        = useRef(false);          // no reconnect after SYSTEM_LOCK
  const [connected, setConnected] = useState(false);

  const buildUrl = useCallback(() => {
    const params = new URLSearchParams({ token, cols: String(cols), rows: String(rows) });
    if (fingerprint) params.set('fp', fingerprint);
    return `${WS_BASE}/ws/terminal?${params}`;
  }, [token, cols, rows, fingerprint]);

  const connect = useCallback(() => {
    if (lockedRef.current) return;

    const ws = new WebSocket(buildUrl());
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      reconnectDelay.current = RECONNECT_BASE_MS;
    };

    ws.onmessage = (ev) => {
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(ev.data as string);
      } catch {
        return;
      }

      switch (msg['type']) {
        case 'output': {
          if (!terminal || typeof msg['data'] !== 'string') break;
          // Decode base64 ANSI bytes → write to xterm
          const bytes = atob(msg['data'] as string);
          terminal.write(bytes);
          break;
        }
        case 'SYSTEM_LOCK': {
          lockedRef.current = true;
          setConnected(false);
          ws.close(1000, 'system_lock');
          onSystemLock?.({
            reason:  String(msg['reason']  ?? ''),
            message: String(msg['message'] ?? ''),
          });
          break;
        }
        case 'session_info': {
          onSessionInfo?.({
            sessionId: String(msg['session_id'] ?? ''),
            balanceV:  Number(msg['balance_v']  ?? 0),
            isGuest:   Boolean(msg['guest']     ?? false),
          });
          break;
        }
        case 'balance_update': {
          onBalanceUpdate?.(Number(msg['remaining_v'] ?? 0));
          break;
        }
        case 'error': {
          terminal?.writeln(`\r\n\x1b[31mServer error: ${msg['message']}\x1b[0m\r\n`);
          break;
        }
      }
    };

    ws.onerror = () => {
      setConnected(false);
    };

    ws.onclose = (ev) => {
      setConnected(false);
      wsRef.current = null;
      // Don't reconnect on SYSTEM_LOCK or normal close
      if (lockedRef.current || ev.code === 1000) return;
      const delay = Math.min(reconnectDelay.current, RECONNECT_MAX_MS);
      reconnectDelay.current = Math.min(delay * RECONNECT_FACTOR, RECONNECT_MAX_MS);
      setTimeout(connect, delay);
    };
  }, [buildUrl, terminal, onSessionInfo, onSystemLock, onBalanceUpdate]);

  useEffect(() => {
    if (!terminal) return;
    connect();
    return () => {
      lockedRef.current = true;   // prevent reconnect on unmount
      wsRef.current?.close(1000, 'unmount');
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [terminal]);    // re-connect only when terminal instance changes

  const sendInput = useCallback((data: string) => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'input', data }));
    }
  }, []);

  const sendResize = useCallback((c: number, r: number) => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'resize', cols: c, rows: r }));
    }
  }, []);

  return { connected, sendInput, sendResize };
}
