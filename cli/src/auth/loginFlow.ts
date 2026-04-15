/**
 * loginFlow.ts
 *
 * Orchestrates the full CLI OAuth login handshake:
 *   1. Generate a CSRF state nonce
 *   2. Start the ephemeral callback server on port 8989
 *   3. Open the browser to the OpenVegas login page (with state + redirect params)
 *   4. Wait for the callback from the Railway backend
 *   5. Persist tokens to ~/.openvegas/config.json
 *   6. Return the access token to the caller
 *
 * BROWSER OPEN
 * ────────────
 *   macOS  → open
 *   Linux  → xdg-open (fallback: prints URL for manual copy)
 *   WSL2   → cmd.exe /c start (detected via /proc/version)
 *
 * DEEP LINK ALTERNATIVE
 * ─────────────────────
 *   If a `--deep-link` flag is passed, uses the openvegas:// URL scheme
 *   instead of localhost:8989. This requires the native app association
 *   to be registered. Default is the localhost server approach.
 */

import * as cp from 'node:child_process';
import * as fs from 'node:fs';
import {
  generateStateNonce,
  startCallbackServer,
  saveTokens,
  loadTokens,
  type CallbackPayload,
} from './localServer';

const APP_BASE = process.env['OPENVEGAS_APP_URL'] ?? 'https://app.openvegas.ai';
const CALLBACK_URL = 'http://localhost:8989/callback';

// ─── Browser opener ───────────────────────────────────────────────────────────

function isWsl(): boolean {
  try {
    const version = fs.readFileSync('/proc/version', 'utf8');
    return /microsoft|wsl/i.test(version);
  } catch {
    return false;
  }
}

function openBrowser(url: string): void {
  try {
    const platform = process.platform;
    if (platform === 'darwin') {
      cp.spawn('open', [url], { detached: true, stdio: 'ignore' }).unref();
    } else if (platform === 'linux' && isWsl()) {
      cp.spawn('cmd.exe', ['/c', 'start', url.replace(/&/g, '^&')],
               { detached: true, stdio: 'ignore' }).unref();
    } else if (platform === 'linux') {
      cp.spawn('xdg-open', [url], { detached: true, stdio: 'ignore' }).unref();
    } else {
      // Fallback: instruct user to open manually
      console.error(`\nCould not detect browser opener. Open this URL manually:\n\n  ${url}\n`);
    }
  } catch {
    console.error(`\nFailed to open browser. Open this URL manually:\n\n  ${url}\n`);
  }
}

// ─── Build the login URL ──────────────────────────────────────────────────────

function buildLoginUrl(stateNonce: string): string {
  const params = new URLSearchParams({
    cli_redirect: CALLBACK_URL,
    state:        stateNonce,
    // Tells the web UI to skip the full page experience and go straight to OAuth
    mode:         'cli',
  });
  return `${APP_BASE}/ui/login?${params.toString()}`;
}

// ─── Login flow ───────────────────────────────────────────────────────────────

export interface LoginResult {
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
  userId: string;
  isNew: boolean;   // true if this was a fresh login vs token reuse
}

export async function login(opts?: { force?: boolean }): Promise<LoginResult> {
  // Fast path: return cached tokens if still valid (5 min buffer)
  if (!opts?.force) {
    const cached = loadTokens();
    if (cached && cached.expiresAt > Math.floor(Date.now() / 1000) + 300) {
      return { ...cached, isNew: false };
    }
  }

  const stateNonce = generateStateNonce();
  const loginUrl   = buildLoginUrl(stateNonce);

  // Start the callback server BEFORE opening the browser so the port is
  // already bound when the redirect arrives.
  const callbackPromise = startCallbackServer(stateNonce);

  console.log('\nOpening browser to authenticate...');
  console.log(`\n  ${loginUrl}\n`);
  console.log('(Waiting up to 2 minutes for login to complete)\n');

  openBrowser(loginUrl);

  let payload: CallbackPayload;
  try {
    payload = await callbackPromise;
  } catch (err) {
    throw new Error(`Login failed: ${(err as Error).message}`);
  }

  saveTokens(payload);
  console.log('\n✓ Authenticated successfully.\n');

  return { ...payload, isNew: true };
}

// ─── Logout ───────────────────────────────────────────────────────────────────

export function logout(): void {
  const cfgDir = `${process.env['HOME'] ?? '~'}/.openvegas`;
  try {
    const configFile = `${cfgDir}/config.json`;
    if (fs.existsSync(configFile)) {
      fs.unlinkSync(configFile);
      console.log('\n✓ Logged out. Credentials removed from ~/.openvegas/config.json\n');
    } else {
      console.log('\nNo active session found.\n');
    }
  } catch (err) {
    console.error(`Logout error: ${(err as Error).message}`);
    process.exit(1);
  }
}
