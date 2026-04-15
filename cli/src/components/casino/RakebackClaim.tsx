/**
 * RakebackClaim.tsx
 *
 * Toast notification shown when a 5% rakeback milestone is reached.
 * Mounts when metrics.rakebackPending = true.
 *
 * DISCLOSURE
 * ──────────
 *   The rakeback rate (5% per 10,000 $V burned) is documented in the user's
 *   account settings and surfaced here at point-of-receipt. It is NOT a silent
 *   RTP adjustment — it is a disclosed loyalty rebate deposited to the wallet.
 *
 * VISUAL (80-col example)
 * ───────────────────────
 *
 *   ╔══════════════════════════════════════════════════════╗
 *   ║  RAKEBACK  +500 $V deposited to your wallet         ║
 *   ║  5% rebate on 10,000 $V burned  •  [any key] dismiss║
 *   ╚══════════════════════════════════════════════════════╝
 *
 * AUTO-DISMISS
 * ────────────
 *   Automatically dismisses after 5,000ms. Any keypress also dismisses.
 *   On dismiss, calls metrics.claimRakeback() to clear the pending state.
 *
 * ZUSTAND READS
 *   metrics.rakebackPending   → mount condition
 *   metrics.rakebackAmountV   → shown in notification
 *   metrics.claimRakeback()   → called on dismiss
 */

import React, { useEffect } from 'react';
import { Box, Text, useInput, useStdout } from 'ink';
import chalk from 'chalk';
import { useStore } from '../../store';

const AUTO_DISMISS_MS = 5_000;

export function RakebackClaim() {
  const rakebackPending = useStore((s) => s.metrics.rakebackPending);
  const rakebackAmountV = useStore((s) => s.metrics.rakebackAmountV);
  const claimRakeback   = useStore((s) => s.metrics.claimRakeback);
  const { stdout }      = useStdout();
  const termW           = stdout?.columns ?? 80;

  // Auto-dismiss after 5s
  useEffect(() => {
    if (!rakebackPending) return;
    const id = setTimeout(() => { claimRakeback(); }, AUTO_DISMISS_MS);
    return () => clearTimeout(id);
  }, [rakebackPending, claimRakeback]);

  // Any key dismisses
  useInput(() => {
    if (rakebackPending) claimRakeback();
  });

  if (!rakebackPending) return null;

  // ── Layout ─────────────────────────────────────────────────────────────────
  // Compact two-line toast — double-border box
  const W    = Math.min(termW, 60);
  const hr   = '\u2550'.repeat(W - 2);
  const top  = '\u2554' + hr + '\u2557';
  const bot  = '\u255A' + hr + '\u255D';

  function toastRow(content: string): string {
    const visible = content.replace(/\x1B\[[0-9;]*m/g, '').length;
    return '\u2551 ' + content + ' '.repeat(Math.max(0, W - 3 - visible)) + '\u2551';
  }

  const line1 =
    chalk.bold.green('RAKEBACK') +
    chalk.dim.white('  ') +
    chalk.bold.white('+' + rakebackAmountV.toLocaleString() + ' $V') +
    chalk.dim.white(' deposited to your wallet');

  const line2 =
    chalk.dim.white('5% rebate on 10,000 $V burned') +
    chalk.dim.white('  \u2022  ') +
    chalk.dim.cyan('[any key] dismiss');

  return (
    <Box flexDirection="column" width={W}>
      <Text>{top}</Text>
      <Text>{toastRow(line1)}</Text>
      <Text>{toastRow(line2)}</Text>
      <Text>{bot}</Text>
    </Box>
  );
}
