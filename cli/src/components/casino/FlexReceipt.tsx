/**
 * FlexReceipt.tsx
 *
 * ASCII punch-card receipt rendered after a jackpot win or large code generation.
 * Designed for copy-paste to Discord / X: pure box-drawing + ASCII, no ANSI color
 * in the copyable body (color only in the Ink render layer via chalk wrappers).
 *
 * DESIGN GOALS
 * ────────────
 *   - 56 chars wide (fits in Discord code blocks at default font)
 *   - All box-drawing via Unicode double-line characters
 *   - Each section visually distinct: header / session / economics / verify
 *   - printReceipt() returns a plain-text string for clipboard copy
 *
 * COPYABLE OUTPUT (no chalk, pure ASCII):
 *
 *   ╔══════════════════════════════════════════════════════╗
 *   ║  OPENVEGAS RECEIPT    //  SESSION 0x3F2A...8B       ║
 *   ╠══════════════════════════════════════════════════════╣
 *   ║  DATE      2026-04-15  23:42:18 UTC                 ║
 *   ║  MODEL     claude-opus-4-6                          ║
 *   ║  PROVIDER  anthropic                                ║
 *   ╠══════════════════════════════════════════════════════╣
 *   ║  WAGERED        5,000  $V                           ║
 *   ║  TOKENS IN     12,450  tok                          ║
 *   ║  TOKENS OUT     4,891  tok                          ║
 *   ║  TOTAL         17,341  tok                          ║
 *   ╠══════════════════════════════════════════════════════╣
 *   ║  MULTIPLIER           10x                           ║
 *   ║  PAYOUT        50,000  $V  [##########]             ║
 *   ║  NET P&L      +45,000  $V                           ║
 *   ╠══════════════════════════════════════════════════════╣
 *   ║  VERIFY  sha256:9f3a...2c1e                         ║
 *   ║  openvegas.gg/verify/0x3F2A                         ║
 *   ╚══════════════════════════════════════════════════════╝
 *
 * ZUSTAND READS
 *   casino.lastResult     → GameResult object
 *   casino.showReceipt    → mount condition
 *   casino.dismissFlexReceipt → called on any keypress to dismiss
 */

import React from 'react';
import { Box, Text, useInput } from 'ink';
import Gradient from 'ink-gradient';
import chalk from 'chalk';
import type { GameResult } from '../../store/casinoSlice';
import { useCasino } from '../../store';

const RECEIPT_W = 56;  // inner width (between ║ characters)
const PAYOUT_BAR_W = 10;

// ─── Pure-text receipt builder (clipboard-safe) ───────────────────────────────

export function buildReceiptText(r: GameResult): string {
  const W = RECEIPT_W;
  const pad = (l: string, v: string) =>
    `\u2551  ${l.padEnd(12)}${v.padStart(W - 14 - 2)}\u2551`;

  const hr = '\u2550'.repeat(W);
  const top    = '\u2554' + hr + '\u2557';
  const mid    = '\u2560' + hr + '\u2563';
  const bottom = '\u255A' + hr + '\u255D';

  const sessionShort = r.sessionId.slice(0, 18);
  const header = `\u2551  OPENVEGAS RECEIPT  //  SESSION ${sessionShort.padEnd(W - 36)}\u2551`;

  const date = new Date(r.timestamp).toISOString().replace('T', '  ').slice(0, 22) + ' UTC';
  const payoutFill = Math.round((Math.min(r.multiplier, 10) / 10) * PAYOUT_BAR_W);
  const payoutBar = '[' + '#'.repeat(payoutFill) + ' '.repeat(PAYOUT_BAR_W - payoutFill) + ']';
  const netSign = r.netV >= 0 ? '+' : '';

  const lines = [
    top,
    header,
    mid,
    pad('DATE',     date),
    pad('MODEL',    r.model),
    pad('PROVIDER', r.provider),
    mid,
    pad('WAGERED',    r.wageredV.toLocaleString() + '  $V'),
    pad('TOKENS IN',  r.inputTokens.toLocaleString() + '  tok'),
    pad('TOKENS OUT', r.outputTokens.toLocaleString() + '  tok'),
    pad('TOTAL', (r.inputTokens + r.outputTokens).toLocaleString() + '  tok'),
    mid,
    pad('MULTIPLIER', r.multiplier + 'x'),
    pad('PAYOUT',  r.payoutV.toLocaleString() + '  $V  ' + payoutBar),
    pad('NET P&L', netSign + r.netV.toLocaleString() + '  $V'),
    mid,
    pad('VERIFY',  'sha256:' + r.verifyHash.slice(0, 16) + '...'),
    pad('',        'openvegas.gg/verify/' + r.sessionId.slice(0, 8)),
    bottom,
  ];

  return lines.join('\n');
}

// ─── Ink renderer ─────────────────────────────────────────────────────────────

const JACKPOT_GRADIENT = ['#ff00ff', '#00ffff', '#ffff00'];

export function FlexReceipt() {
  const { lastResult, showReceipt, dismissFlexReceipt } = useCasino();

  useInput(() => { dismissFlexReceipt(); });

  if (!showReceipt || !lastResult) return null;

  const r = lastResult;
  const text = buildReceiptText(r);
  const lines = text.split('\n');

  const isJackpot = r.multiplier >= 10;
  const netSign = r.netV >= 0 ? '+' : '';

  // Render with chalk colors on top of the plain ASCII structure
  const colorLine = (line: string, i: number): string => {
    // Top / bottom borders
    if (i === 0 || i === lines.length - 1) {
      return isJackpot ? line : chalk.green(line);
    }
    // Section dividers
    if (line.startsWith('\u2560')) {
      return chalk.dim.green(line);
    }
    // Header line
    if (line.includes('OPENVEGAS RECEIPT')) {
      return chalk.bold.cyan(line);
    }
    // P&L line — green for profit, red for loss
    if (line.includes('NET P&L')) {
      return r.netV >= 0 ? chalk.bold.green(line) : chalk.bold.red(line);
    }
    // Multiplier line — yellow for jackpot
    if (line.includes('MULTIPLIER')) {
      return isJackpot ? chalk.bold.yellow(line) : chalk.white(line);
    }
    return chalk.dim.white(line);
  };

  const hint = chalk.dim.white('  press any key to dismiss');

  return (
    <Box flexDirection="column">
      {isJackpot && (
        <Gradient colors={JACKPOT_GRADIENT}>
          <Text bold>{'  JACKPOT  '.padStart(30).padEnd(RECEIPT_W)}</Text>
        </Gradient>
      )}
      {lines.map((line, i) =>
        isJackpot && (i === 0 || i === lines.length - 1) ? (
          <Gradient key={i} colors={JACKPOT_GRADIENT}>
            <Text>{line}</Text>
          </Gradient>
        ) : (
          <Text key={i}>{colorLine(line, i)}</Text>
        )
      )}
      <Text>{hint}</Text>
    </Box>
  );
}
