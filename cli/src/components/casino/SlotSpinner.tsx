/**
 * SlotSpinner.tsx
 *
 * Variable-reward loading state. Replaces a plain spinner with three spinning
 * reels that lock in sequence before the AI text starts rendering.
 *
 * WHEN IT MOUNTS
 * ──────────────
 *   Parent passes `active={isStreaming}`. The spinner shows when the inference
 *   request has been sent but no tokens have arrived yet (buffer === '').
 *   It hides automatically once useSlotReel.visible goes false (all reels
 *   locked + linger period elapsed).
 *
 * VISUAL
 * ──────
 *
 *   ┌─ GENERATING ────────────────────────────────────────────┐
 *   │                                                         │
 *   │         [  @  |  #  |  *  ]                            │
 *   │              spinning...                                │
 *   │                                                         │
 *   └─────────────────────────────────────────────────────────┘
 *
 *   After locking:
 *
 *   ┌─ GENERATING ────────────────────────────────────────────┐
 *   │                                                         │
 *   │         [  O  |  V  |  G  ]     <-- locked symbols     │
 *   │              * * *  LOCKED                             │
 *   │                                                         │
 *   └─────────────────────────────────────────────────────────┘
 *
 * REEL SYMBOL STYLING
 *   spinning → dim yellow, cycling
 *   locking  → yellow, decelerating
 *   locked   → bold green with underline
 *
 * ZUSTAND READS
 *   stream.isStreaming   → triggers startSpin()
 *   stream.buffer        → if non-empty, the stream has started; hide spinner
 *   casino.slotTrigger   → alternative external trigger
 *   casino.clearSlotTrigger → called after spin starts
 */

import React, { useEffect, useRef } from 'react';
import { Box, Text, useStdout } from 'ink';
import chalk from 'chalk';
import { useStore, useIsStreaming, useStreamBuffer, useCasino } from '../../store';
import { useSlotReel } from '../../hooks/useSlotReel';

// ─── Reel cell renderer ───────────────────────────────────────────────────────

type ReelStatus = 'idle' | 'spinning' | 'locking' | 'locked';

function reelCell(symbol: string, status: ReelStatus): string {
  switch (status) {
    case 'locked':
      return chalk.bold.greenBright(` ${symbol} `);
    case 'locking':
      return chalk.yellow(` ${symbol} `);
    case 'spinning':
      return chalk.dim.yellow(` ${symbol} `);
    default:
      return chalk.dim.white(` ? `);
  }
}

// Lock indicator pip below each reel
function lockPip(status: ReelStatus): string {
  if (status === 'locked') return chalk.bold.green(' * ');
  if (status === 'locking') return chalk.yellow(' - ');
  return chalk.dim.white(' . ');
}

// ─── Component ───────────────────────────────────────────────────────────────

interface SlotSpinnerProps {
  active: boolean;         // true from outside when inference is pending
  sessionId?: string;      // seed for deterministic final symbols
  width?: number;          // panel width (defaults to terminal width)
}

export function SlotSpinner({ active, sessionId = '', width: widthProp }: SlotSpinnerProps) {
  const { stdout } = useStdout();
  const termW = stdout?.columns ?? 80;
  const width = widthProp ?? termW;

  const isStreaming = useIsStreaming();
  const buffer = useStreamBuffer();
  const { clearSlotTrigger } = useCasino();

  const { symbols, statuses, allLocked, visible, startSpin } = useSlotReel();

  // Trigger spin when streaming starts and buffer is still empty
  const prevStreamingRef = useRef(false);
  useEffect(() => {
    const wasStreaming = prevStreamingRef.current;
    prevStreamingRef.current = isStreaming;

    if (isStreaming && !wasStreaming && active) {
      startSpin(sessionId || String(Date.now()));
      clearSlotTrigger();
    }
  }, [isStreaming, active, sessionId, startSpin, clearSlotTrigger]);

  // Hide once text is flowing (buffer non-empty and all reels locked)
  const hasText = buffer.trim().length > 0;
  const show = visible && !hasText;

  if (!show) return null;

  // ── Layout ─────────────────────────────────────────────────────────────────
  const innerW = width - 4;
  const topBorder    = '\u250C' + '\u2500'.repeat(innerW) + '\u2510';
  const bottomBorder = '\u2514' + '\u2500'.repeat(innerW) + '\u2518';
  const emptyRow     = '\u2502' + ' '.repeat(innerW) + '\u2502';

  // Title
  const titleText = allLocked ? 'LOCKED' : 'GENERATING';
  const titleRow = '\u2502 ' + chalk.cyan(titleText).padEnd(innerW - 1) + '\u2502';

  // Reels: [ A | B | C ]
  const reelParts = [
    chalk.dim.cyan('['),
    reelCell(symbols[0], statuses[0]),
    chalk.dim.cyan('|'),
    reelCell(symbols[1], statuses[1]),
    chalk.dim.cyan('|'),
    reelCell(symbols[2], statuses[2]),
    chalk.dim.cyan(']'),
  ].join('');

  // Center the reel display
  const reelStrLen = 3 + 3 + 1 + 3 + 1 + 3 + 1;  // approximate visible chars
  const reelPad = Math.max(0, Math.floor((innerW - reelStrLen) / 2));
  const reelRow = '\u2502' + ' '.repeat(reelPad) + reelParts +
    ' '.repeat(Math.max(0, innerW - reelPad - reelStrLen)) + '\u2502';

  // Pips row
  const pipsParts = [
    '  ',
    lockPip(statuses[0]),
    ' ',
    lockPip(statuses[1]),
    ' ',
    lockPip(statuses[2]),
    '  ',
  ].join('');
  const pipsRow = '\u2502' + ' '.repeat(reelPad) + pipsParts +
    ' '.repeat(Math.max(0, innerW - reelPad - 14)) + '\u2502';

  // Status label
  const statusLabel = allLocked
    ? chalk.bold.green('READY')
    : chalk.dim.yellow('waiting for tokens...');
  const statusPad = Math.max(0, Math.floor((innerW - statusLabel.replace(/\x1B\[[0-9;]*m/g, '').length) / 2));
  const statusRow = '\u2502' + ' '.repeat(statusPad) + statusLabel +
    ' '.repeat(Math.max(0, innerW - statusPad - statusLabel.replace(/\x1B\[[0-9;]*m/g, '').length)) + '\u2502';

  return (
    <Box flexDirection="column" width={width}>
      <Text color="green">{topBorder}</Text>
      <Text>{titleRow}</Text>
      <Text>{emptyRow}</Text>
      <Text>{reelRow}</Text>
      <Text>{pipsRow}</Text>
      <Text>{statusRow}</Text>
      <Text>{emptyRow}</Text>
      <Text color="green">{bottomBorder}</Text>
    </Box>
  );
}
