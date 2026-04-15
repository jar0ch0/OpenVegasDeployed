/**
 * localServer.ts
 *
 * Ephemeral HTTP server on port 8989 that catches the OAuth callback
 * from the Railway backend after Supabase authentication completes.
 *
 * FLOW
 * ────
 *   1. CLI opens browser: https://app.openvegas.ai/ui/login?cli_redirect=1
 *   2. User completes Supabase OAuth in the browser
 *   3. Server issues: 302 → http://localhost:8989/callback?token=<JWT>&refresh=<token>
 *   4. This server receives the GET, persists the tokens, and sends a success page
 *   5. Server shuts down; loginFlow.ts resolves with the JWT
 *
 * SECURITY
 * ────────
 *   - Binds to 127.0.0.1 only (not 0.0.0.0)
 *   - Times out after TIMEOUT_MS if no callback received
 *   - State nonce validated to prevent CSRF on the redirect
 *   - Token written to ~/.openvegas/config.json with mode 0600
 */

import * as http from 'node:http';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';
import * as crypto from 'node:crypto';
import { URL } from 'node:url';

export const CALLBACK_PORT = 8989;
export const TIMEOUT_MS    = 120_000;   // 2 minutes

export interface CallbackPayload {
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
  userId: string;
}

export interface LocalServerResult {
  payload: CallbackPayload;
  stateNonce: string;
}

// ─── Config persistence ───────────────────────────────────────────────────────

function configPath(): string {
  return path.join(os.homedir(), '.openvegas', 'config.json');
}

export function saveTokens(payload: CallbackPayload): void {
  const dir = path.join(os.homedir(), '.openvegas');
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  }

  const cfg = {
    access_token:  payload.accessToken,
    refresh_token: payload.refreshToken,
    expires_at:    payload.expiresAt,
    user_id:       payload.userId,
    saved_at:      Date.now(),
  };

  fs.writeFileSync(configPath(), JSON.stringify(cfg, null, 2), { mode: 0o600 });
}

export function loadTokens(): CallbackPayload | null {
  try {
    const raw = fs.readFileSync(configPath(), 'utf8');
    const cfg = JSON.parse(raw) as Record<string, unknown>;
    if (cfg.access_token && cfg.refresh_token) {
      return {
        accessToken:  String(cfg.access_token),
        refreshToken: String(cfg.refresh_token),
        expiresAt:    Number(cfg.expires_at ?? 0),
        userId:       String(cfg.user_id ?? ''),
      };
    }
  } catch {
    // Config doesn't exist or is malformed
  }
  return null;
}

// ─── Success / error HTML response pages ─────────────────────────────────────

const SUCCESS_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>OpenVegas — Authenticated</title>
  <style>
    body { background: #0a0a0a; color: #00ff88; font-family: monospace;
           display: flex; align-items: center; justify-content: center;
           height: 100vh; margin: 0; text-align: center; }
    h1   { font-size: 2rem; margin-bottom: 0.5rem; }
    p    { color: #888; font-size: 0.9rem; }
  </style>
</head>
<body>
  <div>
    <h1>&#9632; Authenticated</h1>
    <p>You can close this window and return to your terminal.</p>
    <p style="color:#555;margin-top:2rem">openvegas.ai</p>
  </div>
  <script>setTimeout(() => window.close(), 2000);</script>
</body>
</html>`;

const ERROR_HTML = (msg: string) => `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>OpenVegas — Auth Failed</title>
  <style>
    body { background: #0a0a0a; color: #ff4444; font-family: monospace;
           display: flex; align-items: center; justify-content: center;
           height: 100vh; margin: 0; text-align: center; }
    h1   { font-size: 2rem; }
    p    { color: #888; font-size: 0.9rem; }
  </style>
</head>
<body>
  <div>
    <h1>&#9632; Auth Failed</h1>
    <p>${msg}</p>
    <p>Please retry: <code>openvegas login</code></p>
  </div>
</body>
</html>`;

// ─── Server ───────────────────────────────────────────────────────────────────

export function startCallbackServer(stateNonce: string): Promise<CallbackPayload> {
  return new Promise((resolve, reject) => {
    let settled = false;

    const settle = (fn: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeoutHandle);
      server.close();
      fn();
    };

    const server = http.createServer((req, res) => {
      if (!req.url?.startsWith('/callback')) {
        res.writeHead(404).end('Not found');
        return;
      }

      let url: URL;
      try {
        url = new URL(req.url, `http://localhost:${CALLBACK_PORT}`);
      } catch {
        res.writeHead(400).end('Bad request');
        return;
      }

      const token   = url.searchParams.get('token')   ?? '';
      const refresh = url.searchParams.get('refresh') ?? '';
      const state   = url.searchParams.get('state')   ?? '';
      const expRaw  = url.searchParams.get('expires_at') ?? '0';
      const userId  = url.searchParams.get('user_id') ?? '';
      const errMsg  = url.searchParams.get('error')   ?? '';

      // Auth error forwarded from server
      if (errMsg) {
        res.writeHead(200, { 'Content-Type': 'text/html' }).end(ERROR_HTML(errMsg));
        settle(() => reject(new Error(`OAuth error: ${errMsg}`)));
        return;
      }

      // CSRF: validate state nonce
      if (!state || state !== stateNonce) {
        res.writeHead(400, { 'Content-Type': 'text/html' })
           .end(ERROR_HTML('State mismatch — possible CSRF. Retry login.'));
        settle(() => reject(new Error('state_mismatch')));
        return;
      }

      if (!token || !refresh) {
        res.writeHead(400, { 'Content-Type': 'text/html' })
           .end(ERROR_HTML('Missing token in callback. Retry login.'));
        settle(() => reject(new Error('missing_token')));
        return;
      }

      const payload: CallbackPayload = {
        accessToken:  token,
        refreshToken: refresh,
        expiresAt:    parseInt(expRaw, 10) || Math.floor(Date.now() / 1000) + 3600,
        userId,
      };

      res.writeHead(200, { 'Content-Type': 'text/html' }).end(SUCCESS_HTML);
      settle(() => resolve(payload));
    });

    // Bind to loopback only — never expose on 0.0.0.0
    server.listen(CALLBACK_PORT, '127.0.0.1', () => {
      // Server is ready; loginFlow can now open the browser
    });

    server.on('error', (err: NodeJS.ErrnoException) => {
      if (err.code === 'EADDRINUSE') {
        settle(() => reject(new Error(
          `Port ${CALLBACK_PORT} is already in use. Close any other openvegas processes and retry.`
        )));
      } else {
        settle(() => reject(err));
      }
    });

    // Timeout after 2 minutes
    const timeoutHandle = setTimeout(() => {
      settle(() => reject(new Error('Login timed out (120s). Run `openvegas login` again.')));
    }, TIMEOUT_MS);
  });
}

// ─── State nonce generator ────────────────────────────────────────────────────

export function generateStateNonce(): string {
  return crypto.randomBytes(16).toString('hex');
}
