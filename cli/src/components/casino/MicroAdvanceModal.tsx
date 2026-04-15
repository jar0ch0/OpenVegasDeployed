/**
 * MicroAdvanceModal.tsx
 *
 * BNPL micro-advance overlay. Mounts when ui.needsMicroAdvance = true,
 * which is set by the inference layer when a request fails due to
 * insufficient $V balance.
 *
 * MECHANIC
 * ────────
 *   User is offered a 5,000 $V advance drawn against their next topup.
 *   Repayment: 5,250 $V (1.05x) deducted automatically on next Stripe charge.
 *   Server side: POST /budget/lock creates an advance-backed budget session.
 *
 * VISUAL (80-col example)
 * ───────────────────────
 *
 *   ╔══════════════════════════════════════════════════════════════════════╗
 *   ║  ADVANCE                                                            ║
 *   ╠══════════════════════════════════════════════════════════════════════╣
 *   ║  Your current session ran out of $V.                                ║
 *   ║                                                                     ║
 *   ║  Advance      5,000  $V                                             ║
 *   ║  Repayment    5,250  $V  (1.05x, deducted from next topup)         ║
 *   ╠══════════════════════════════════════════════════════════════════════╣
 *   ║  Pending      "refactor TypeScript components to..."                ║
 *   ╠══════════════════════════════════════════════════════════════════════╣
 *   ║  [Enter] Accept advance and resume    [Esc] Decline                 ║
 *   ╚══════════════════════════════════════════════════════════════════════╝
 *
 * FLOW
 * ────
 *   Enter → POST /budget/lock { amount_v: 5000, advance: true }
 *         → lockBudget(sessionId, 5000) in budgetSlice
 *         → clearMicroAdvance() in uiSlice
 *         → onResume(pendingPrompt) fires so ChatScreen can re-submit
 *   Esc   → clearMicroAdvance() — user stays at empty wallet prompt
 *
 * ZUSTAND READS
 *   ui.needsMicroAdvance   → mount condition
 *   ui.pendingPrompt       → shows abbreviated prompt text in modal
 *   session.jwt            → auth header
 */

import React, { useState, useCallback } from 'react';
import { Box, Text, useInput, useStdout } from 'ink';
import chalk from 'chalk';
import { useStore } from '../../store';

const ADVANCE_V   = 5_000;
const REPAY_MULT  = 1.05;
const REPAY_V     = Math.round(ADVANCE_V * REPAY_MULT);

interface MicroAdvanceModalProps {
  apiBase: string;
  onResume: (prompt: string) => void;   // called with pendingPrompt after advance accepted
}

export function MicroAdvanceModal({ apiBase, onResume }: MicroAdvanceModalProps) {
  const needsMicroAdvance = useStore((s) => s.ui.needsMicroAdvance);
  const pendingPrompt     = useStore((s) => s.ui.pendingPrompt);
  const jwt               = useStore((s) => s.session.jwt);
  const lockBudget        = useStore((s) => s.budget.lockBudget);
  const clearMicroAdvance = useStore((s) => s.ui.clearMicroAdvance);
  const { stdout }        = useStdout();
  const termW             = stdout?.columns ?? 80;
  const innerW            = termW - 2;

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg]         = useState<string | null>(null);

  const handleAccept = useCallback(async () => {
    if (isSubmitting || !jwt) return;
    setIsSubmitting(true);
    setErrorMsg(null);

    try {
      const res = await fetch(`${apiBase}/budget/lock`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${jwt}`,
        },
        body: JSON.stringify({ amount_v: ADVANCE_V, advance: true }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({})) as { detail?: string };
        setErrorMsg(body.detail ?? `Server error ${res.status}`);
        setIsSubmitting(false);
        return;
      }

      const data = await res.json() as { budget_session_id: string };
      lockBudget(data.budget_session_id, ADVANCE_V);
      clearMicroAdvance();
      if (pendingPrompt) onResume(pendingPrompt);
    } catch {
      setErrorMsg('Network error — check your connection.');
      setIsSubmitting(false);
    }
  }, [isSubmitting, jwt, apiBase, lockBudget, clearMicroAdvance, pendingPrompt, onResume]);

  useInput((input, key) => {
    if (!needsMicroAdvance) return;
    if (key.return && !isSubmitting) {
      void handleAccept();
    } else if (key.escape) {
      clearMicroAdvance();
    }
  });

  if (!needsMicroAdvance) return null;

  // ── Layout ─────────────────────────────────────────────────────────────────
  const hr  = '\u2550'.repeat(innerW - 2);
  const top = '\u2554' + hr + '\u2557';
  const mid = '\u2560' + hr + '\u2563';
  const bot = '\u255A' + hr + '\u255D';

  function padRow(content: string): string {
    const visible = content.replace(/\x1B\[[0-9;]*m/g, '').length;
    return '\u2551  ' + content + ' '.repeat(Math.max(0, innerW - 4 - visible)) + '  \u2551';
  }

  const promptPreview = pendingPrompt
    ? chalk.dim.white('"' + pendingPrompt.slice(0, innerW - 12) + (pendingPrompt.length > innerW - 12 ? '...' : '') + '"')
    : chalk.dim.white('(none)');

  const footerText = isSubmitting
    ? chalk.dim.yellow('Contacting server...')
    : chalk.bold.green('[Enter] Accept advance and resume') +
      chalk.dim.white('    ') +
      chalk.dim.white('[Esc] Decline');

  return (
    <Box flexDirection="column" width={termW}>
      <Text>{top}</Text>
      <Text>{padRow(chalk.bold.yellow('ADVANCE'))}</Text>
      <Text>{mid}</Text>
      <Text>{padRow(chalk.dim.white('Your current session ran out of $V.'))}</Text>
      <Text>{padRow('')}</Text>
      <Text>{padRow(
        chalk.dim.white('Advance'.padEnd(14)) +
        chalk.bold.white(ADVANCE_V.toLocaleString().padStart(6)) +
        chalk.dim.white('  $V')
      )}</Text>
      <Text>{padRow(
        chalk.dim.white('Repayment'.padEnd(14)) +
        chalk.bold.white(REPAY_V.toLocaleString().padStart(6)) +
        chalk.dim.white('  $V  (1.05x, deducted from next topup)')
      )}</Text>
      <Text>{mid}</Text>
      <Text>{padRow(chalk.dim.white('Pending   ') + promptPreview)}</Text>
      <Text>{mid}</Text>
      {errorMsg && (
        <Text>{padRow(chalk.bold.red('Error: ') + chalk.dim.red(errorMsg))}</Text>
      )}
      <Text>{padRow(footerText)}</Text>
      <Text>{bot}</Text>
    </Box>
  );
}
