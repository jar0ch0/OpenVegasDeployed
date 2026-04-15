/**
 * App.tsx
 *
 * Root Ink component. Owns:
 *   - JWT loading (from ~/.openvegas/config.json)
 *   - Exit trap (Ctrl+C double-tap) via useExitTrap
 *   - Route to ChatScreen
 *   - Global overlay layer: ExitModal, MicroAdvanceModal, RakebackClaim
 *
 * RENDER CALL REQUIREMENT
 * ───────────────────────
 *   render(<App />, { exitOnCtrlC: false })   ← set in bin/openvegas.ts
 *   Without exitOnCtrlC: false, Ink exits on the first Ctrl+C before
 *   useExitTrap fires.
 *
 * OVERLAY LAYER
 * ─────────────
 *   Overlays mount after ChatScreen in the Box column so they paint on top.
 *   Each overlay reads its own mount condition from the Zustand store and
 *   returns null when inactive — no prop drilling needed.
 */

import React, { useCallback, useEffect, useRef } from 'react';
import { Box } from 'ink';
import { useStore } from '../store/index.js';
import { loadTokens } from '../auth/localServer.js';
import { useExitTrap } from '../hooks/useExitTrap.js';
import { ChatScreen } from '../screens/ChatScreen.js';
import {
  ExitModal,
  MicroAdvanceModal,
  RakebackClaim,
} from '../components/casino/index.js';

// ─── Props ────────────────────────────────────────────────────────────────────

export interface AppProps {
  apiBase:       string;
  approvalMode:  'ask' | 'allow' | 'exclude';
  initialPrompt?: string;
  sessionId?:    string;
  showCasino:    boolean;
}

// ─── App ─────────────────────────────────────────────────────────────────────

export function App({
  apiBase,
  approvalMode,
  initialPrompt,
  sessionId,
  showCasino,
}: AppProps) {
  const sessionStartMs  = useRef(Date.now()).current;
  const setJwt          = useStore((s) => s.session.setJwt);
  const setApprovalMode = useStore((s) => s.chat.setApprovalMode);

  // Bridge for MicroAdvanceModal → ChatScreen re-submission
  const submitRef = useRef<((prompt: string) => void) | null>(null);

  const handleRegisterSubmit = useCallback((fn: (prompt: string) => void) => {
    submitRef.current = fn;
  }, []);

  const handleResume = useCallback((prompt: string) => {
    submitRef.current?.(prompt);
  }, []);

  // On mount: load saved JWT and set approval mode
  useEffect(() => {
    setApprovalMode(approvalMode);
    const tokens = loadTokens();
    if (tokens && tokens.expiresAt > Math.floor(Date.now() / 1000) + 60) {
      setJwt(tokens.accessToken, tokens.expiresAt);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Exit trap — intercepts Ctrl+C at the top level
  useExitTrap();

  return (
    <Box flexDirection="column">
      {/* ── Main screen ──────────────────────────────────────────────────── */}
      <ChatScreen
        apiBase={apiBase}
        initialPrompt={initialPrompt}
        sessionId={sessionId}
        showCasino={showCasino}
        onRegisterSubmit={handleRegisterSubmit}
      />

      {/* ── Global overlays (mount on top, each self-gated by store state) ─ */}
      <ExitModal sessionStartMs={sessionStartMs} />
      <MicroAdvanceModal apiBase={apiBase} onResume={handleResume} />
      <RakebackClaim />
    </Box>
  );
}
