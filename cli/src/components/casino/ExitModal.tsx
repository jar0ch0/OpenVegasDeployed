/**
 * ExitModal.tsx
 *
 * Mounts when ui.isExiting = true (set by useExitTrap on first Ctrl+C).
 * Renders a neutral, informational overlay — no guilt messaging.
 *
 * VISUAL (80-col example)
 * ───────────────────────
 *
 *   ┌─ EXIT ─────────────────────────────────────────────────────────────────┐
 *   │                                                                        │
 *   │  Session      12:04 elapsed                                            │
 *   │  Balance      4,230 $V                                                 │
 *   │  Run          run_01j3... (active)                                     │
 *   │                                                                        │
 *   │  [Y] Exit    [Enter] Resume                                            │
 *   │                                                                        │
 *   └────────────────────────────────────────────────────────────────────────┘
 *
 * FRAMING RULES
 * ─────────────
 *   - Show session facts, not emotional appeals
 *   - No "Are you sure?" phrasing — just the data and the keys
 *   - Run label: "active" if currentRunId set, "idle" otherwise
 *
 * ZUSTAND READS
 *   ui.isExiting         → mount condition
 *   budget.remainingV    → shown as current balance
 *   chat.currentRunId    → shown as active run ID
 */

import React, { useEffect, useRef, useState } from 'react';
import { Box, Text, useStdout } from 'ink';
import chalk from 'chalk';
import { useStore } from '../../store';

// ─── Elapsed timer ────────────────────────────────────────────────────────────

function useElapsed(startMs: number): string {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startMs) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [startMs]);

  const m = Math.floor(elapsed / 60).toString().padStart(2, '0');
  const s = (elapsed % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

// ─── Component ───────────────────────────────────────────────────────────────

interface ExitModalProps {
  sessionStartMs: number;   // when the CLI session started (Date.now() at mount)
}

export function ExitModal({ sessionStartMs }: ExitModalProps) {
  const isExiting      = useStore((s) => s.ui.isExiting);
  const remainingV     = useStore((s) => s.budget.remainingV);
  const currentRunId   = useStore((s) => s.chat.currentRunId);
  const { stdout }     = useStdout();
  const termW          = stdout?.columns ?? 80;
  const innerW         = termW - 4;

  const elapsed = useElapsed(sessionStartMs);

  if (!isExiting) return null;

  // ── Layout ─────────────────────────────────────────────────────────────────
  const topBorder    = '\u250C' + '\u2500'.repeat(innerW) + '\u2510';
  const bottomBorder = '\u2514' + '\u2500'.repeat(innerW) + '\u2518';
  const emptyRow     = '\u2502' + ' '.repeat(innerW) + '\u2502';

  const titleText = chalk.bold.white(' EXIT ');
  const titleFill = '\u2500'.repeat(Math.max(0, innerW - titleText.replace(/\x1B\[[0-9;]*m/g, '').length));
  const titleRow  = '\u2502' + titleText + titleFill + '\u2502';

  const runLabel = currentRunId
    ? currentRunId.slice(0, 16) + '... ' + chalk.dim.green('(active)')
    : chalk.dim.white('idle');

  function infoRow(label: string, value: string): string {
    const l = chalk.dim.white('  ' + label.padEnd(14));
    const v = chalk.white(value);
    const fill = ' '.repeat(Math.max(0,
      innerW - l.replace(/\x1B\[[0-9;]*m/g, '').length
             - v.replace(/\x1B\[[0-9;]*m/g, '').length - 2
    ));
    return '\u2502' + l + v + fill + '  \u2502';
  }

  const footerText = chalk.bold.yellow('[Y] Exit') +
    chalk.dim.white('    ') +
    chalk.bold.white('[Enter]') + chalk.dim.white(' Resume');
  const footerPad = Math.max(0,
    Math.floor((innerW - footerText.replace(/\x1B\[[0-9;]*m/g, '').length) / 2)
  );
  const footerRow = '\u2502' + ' '.repeat(footerPad) + footerText +
    ' '.repeat(Math.max(0, innerW - footerPad - footerText.replace(/\x1B\[[0-9;]*m/g, '').length)) +
    '\u2502';

  return (
    <Box flexDirection="column" width={termW}>
      <Text color="yellow">{topBorder}</Text>
      <Text>{titleRow}</Text>
      <Text>{emptyRow}</Text>
      <Text>{infoRow('Session', elapsed + ' elapsed')}</Text>
      <Text>{infoRow('Balance', remainingV.toLocaleString() + ' $V')}</Text>
      <Text>{infoRow('Run', runLabel)}</Text>
      <Text>{emptyRow}</Text>
      <Text>{footerRow}</Text>
      <Text>{emptyRow}</Text>
      <Text color="yellow">{bottomBorder}</Text>
    </Box>
  );
}
