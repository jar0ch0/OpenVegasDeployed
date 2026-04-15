/**
 * CrashCompiler.tsx
 *
 * Mini-game that mounts during long-running local bash executions
 * (test suites, builds, lint runs). Displays a ticking multiplier that
 * the user can "cash out" before the execution completes or fails.
 *
 * CASH-OUT MECHANIC
 * ─────────────────
 *   Pressing Space fires cashOut() in useCrashMultiplier, which:
 *   1. Calls props.onCashOut(multiplier) → caller POSTs /budget/charge
 *      with charge_type="shell_run" and a bonus reward proportional to mult
 *   2. Calls casinoSlice.recordCrashCashOut(rewardV) → stores result
 *   3. Renders CASHED OUT banner for LINGER_MS before unmounting
 *
 *   If the bash command fails before cash-out: onCrash() is called and
 *   the CRASHED banner renders instead.
 *
 * VISUAL (80-col example)
 * ───────────────────────
 *
 *   ┌─ CRASH COMPILER ──────────────────── exec: npx jest ──────────────────┐
 *   │                                                                        │
 *   │  MULTIPLIER                                             00:07 elapsed  │
 *   │                                                                        │
 *   │    1.00x  [                    ]                                       │
 *   │    1.10x  [####                ]                                       │
 *   │    1.25x  [########            ]                                       │
 *   │  > 1.47x  [############        ]   <-- current, blinking cursor        │
 *   │                                                                        │
 *   │  [SPACE] cash out    budget: 4,997 $V remaining                        │
 *   └────────────────────────────────────────────────────────────────────────┘
 *
 * BAR CHART
 * ─────────
 *   Each history snapshot is one row. Width of bar = (mult - 1.0) / MAX_DISPLAY_MULT.
 *   MAX_DISPLAY_MULT = 5.0 (a 5x multiplier fills the bar completely).
 *   Bars beyond the displayed area use scrolling (oldest drops off top).
 *
 * ZUSTAND READS
 *   budget.remainingV       → shown in footer
 *   budget.autoAcceptActive → whether budget mode is live
 *   casino.crashIsRunning   → driven by caller via prop
 *   casino.recordCrashCashOut → action called on cash-out
 */

import React, { useCallback } from 'react';
import { Box, Text, useInput, useStdout } from 'ink';
import chalk from 'chalk';
import { useBudgetRemaining, useCasino } from '../../store';
import { useCrashMultiplier } from '../../hooks/useCrashMultiplier';

const BAR_WIDTH = 20;       // chars for the bar chart fill area
const MAX_DISPLAY_MULT = 5.0;

// ─── Bar renderer ─────────────────────────────────────────────────────────────

function renderBar(mult: number, isCurrent: boolean, isCashOut: boolean): string {
  const fill = Math.min(1, (mult - 1.0) / (MAX_DISPLAY_MULT - 1.0));
  const filledChars = Math.round(fill * BAR_WIDTH);
  const emptyChars = BAR_WIDTH - filledChars;

  const bar = chalk.dim.white('[') +
    (isCashOut
      ? chalk.bold.yellow('#'.repeat(filledChars))
      : isCurrent
        ? chalk.bold.green('#'.repeat(filledChars))
        : chalk.dim.green('#'.repeat(filledChars))) +
    ' '.repeat(emptyChars) +
    chalk.dim.white(']');

  const label = mult.toFixed(2) + 'x';
  const prefix = isCurrent ? chalk.bold.white('> ') : '  ';
  const labelStr = isCurrent
    ? chalk.bold.white(label.padStart(7))
    : chalk.dim.white(label.padStart(7));
  const cashFlag = isCashOut ? chalk.bold.yellow(' CASH OUT') : '';

  return prefix + labelStr + '  ' + bar + cashFlag;
}

// ─── Time formatter ───────────────────────────────────────────────────────────

function fmtElapsed(ms: number): string {
  const secs = Math.floor(ms / 1000);
  const m = Math.floor(secs / 60).toString().padStart(2, '0');
  const s = (secs % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

// ─── Component ───────────────────────────────────────────────────────────────

interface CrashCompilerProps {
  isRunning: boolean;          // true while the bash command is executing
  commandLabel?: string;       // e.g. "npx jest"
  growthRate?: number;         // multiplier growth per second (default 0.15)
  onCashOut?: (mult: number, rewardV: number) => void;  // caller does POST /budget/charge
  onCrash?: () => void;        // called if execution fails before cash-out
  onComplete?: () => void;     // called after linger period
}

export function CrashCompiler({
  isRunning,
  commandLabel = 'bash',
  growthRate = 0.15,
  onCashOut,
  onCrash: _onCrash,
  onComplete,
}: CrashCompilerProps) {
  const { stdout } = useStdout();
  const termW = stdout?.columns ?? 80;
  const innerW = termW - 4;

  const remainingV = useBudgetRemaining();
  const { recordCrashCashOut } = useCasino();

  const handleCashOut = useCallback((mult: number) => {
    // Flat reward: 1 $V * multiplier (capped at 50 $V per execution)
    const rewardV = Math.min(50, parseFloat(mult.toFixed(2)));
    recordCrashCashOut(rewardV);
    onCashOut?.(mult, rewardV);
  }, [recordCrashCashOut, onCashOut]);

  const { state, cashOut } = useCrashMultiplier({
    isRunning,
    growthRate,
    onCashOut: handleCashOut,
    onComplete,
  });

  // Space key → cash out (only when running and not already cashed out)
  useInput((input, key) => {
    if (key.escape) return;
    if (input === ' ' && isRunning && !state.cashedOut) {
      cashOut();
    }
  });

  if (!isRunning && !state.cashedOut && state.elapsedMs === 0) return null;

  // ── Layout ─────────────────────────────────────────────────────────────────
  const topBorder    = '\u250C' + '\u2500'.repeat(innerW) + '\u2510';
  const bottomBorder = '\u2514' + '\u2500'.repeat(innerW) + '\u2518';
  const emptyRow     = '\u2502' + ' '.repeat(innerW) + '\u2502';

  // Title row with exec label
  const titleLeft = chalk.cyan(' CRASH COMPILER ');
  const titleRight = chalk.dim.white(' exec: ' + commandLabel.slice(0, 30) + ' ');
  const titleFill = '\u2500'.repeat(
    Math.max(0, innerW - titleLeft.replace(/\x1B\[[0-9;]*m/g, '').length
      - titleRight.replace(/\x1B\[[0-9;]*m/g, '').length)
  );
  const titleRow = '\u2502' + titleLeft + titleFill + titleRight + '\u2502';

  // Elapsed timer
  const elapsed = fmtElapsed(state.elapsedMs);
  const multLabel = chalk.bold.white('  MULTIPLIER');
  const elapsedLabel = chalk.dim.white(elapsed + ' elapsed');
  const multRow = '\u2502' + multLabel +
    ' '.repeat(Math.max(0, innerW - multLabel.replace(/\x1B\[[0-9;]*m/g, '').length
      - elapsedLabel.replace(/\x1B\[[0-9;]*m/g, '').length - 2)) +
    elapsedLabel + '  \u2502';

  // Bar chart rows (last MAX_BARS history entries)
  const MAX_BARS = 6;
  const historyRows = state.history.slice(-MAX_BARS).map((snap, i, arr) => {
    const isCurrent = !state.cashedOut && i === arr.length - 1;
    return '\u2502  ' + renderBar(snap.mult, isCurrent, snap.isCashOut) +
      ' '.repeat(Math.max(0, innerW - 2 - 2 - 7 - 2 - BAR_WIDTH - 2 - (snap.isCashOut ? 9 : 0))) +
      '\u2502';
  });

  // Fill to MAX_BARS rows if history is short
  while (historyRows.length < MAX_BARS) {
    historyRows.unshift(emptyRow);
  }

  // Footer
  const footerLeft = state.cashedOut
    ? chalk.bold.yellow(' [CASHED OUT] +' + state.history.find(h => h.isCashOut)?.mult.toFixed(2) + 'x')
    : isRunning
      ? chalk.dim.white(' [SPACE] cash out')
      : chalk.dim.white(' execution finished');
  const footerRight = chalk.dim.cyan(' budget: ' + remainingV.toLocaleString() + ' $V ');
  const footerFill = ' '.repeat(Math.max(0, innerW
    - footerLeft.replace(/\x1B\[[0-9;]*m/g, '').length
    - footerRight.replace(/\x1B\[[0-9;]*m/g, '').length));
  const footerRow = '\u2502' + footerLeft + footerFill + footerRight + '\u2502';

  return (
    <Box flexDirection="column" width={termW}>
      <Text color="green">{topBorder}</Text>
      <Text>{titleRow}</Text>
      <Text>{emptyRow}</Text>
      <Text>{multRow}</Text>
      <Text>{emptyRow}</Text>
      {historyRows.map((row, i) => <Text key={i}>{row}</Text>)}
      <Text>{emptyRow}</Text>
      <Text>{footerRow}</Text>
      <Text color="green">{bottomBorder}</Text>
    </Box>
  );
}
