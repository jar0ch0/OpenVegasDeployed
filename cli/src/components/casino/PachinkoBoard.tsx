/**
 * PachinkoBoard.tsx
 *
 * Split-screen component: inference stream (left) + typographical pachinko (right).
 *
 * LAYOUT
 * ──────
 *   ┌─ INFERENCE STREAM ──────────────────┬─ PACHINKO ───────────────┐
 *   │  ...streaming text from             │  . + . + . + . + . + .  │
 *   │  POST /inference/stream...          │ + . + . + . + . + . + . │
 *   │                                     │  . + . + . + . + . + .  │
 *   │                                     │        O                 │  ← ball
 *   │                                     │  . + . + . + . + . + .  │
 *   │                                     │ ┌───┬───┬───┬───┬───┐  │
 *   │                                     │ │1x │2x │5x │10x│5x │  │
 *   └─────────────────────────────────────┴─┴───┴───┴───┴───┴───┘──┘
 *
 * Borders are rendered manually as chalk-colored strings so we can swap
 * them for ink-gradient neon strings during the jackpot flash.
 *
 * LATENCY BINDING
 * ───────────────
 *   startDrop() is called the moment isStreaming flips true.
 *   usePachinko receives latencyP50Ms from the Zustand store.
 *   drop speed = BOARD_H / (latencyP50Ms / FRAME_MS)
 *   Ball lands in a bucket right as the stream finishes loading.
 *
 * ZUSTAND READS
 *   stream.buffer          → left panel text
 *   stream.isStreaming      → triggers drop + slot spinner
 *   casino.inferenceLatencyP50Ms → drop speed
 *   casino.setPachinkoOutcome   → written when ball lands
 *   casino.pachinkoIsJackpot    → triggers flash CSS (via ink-gradient)
 */

import React, { useEffect, useCallback } from 'react';
import { Box, Text, useStdout } from 'ink';
import Gradient from 'ink-gradient';
import chalk from 'chalk';
import { useStore, useStreamBuffer, useIsStreaming, useLatencyP50, useCasino } from '../../store';
import {
  usePachinko,
  BOARD_H,
  NUM_BUCKETS,
  BUCKET_MULTIPLIERS,
} from '../../hooks/usePachinko';

// ─── Constants ────────────────────────────────────────────────────────────────

const RIGHT_PANEL_RATIO = 0.40;  // 40% of terminal width
const MIN_RIGHT_W = 32;
const BUCKET_CHARS = ['1x', '2x', '5x', '10x', '5x', '2x', '1x'] as const;

// Neon color stops for jackpot gradient flash
const JACKPOT_COLORS = ['#ff00ff', '#00ffff', '#ff00ff', '#ff6600', '#00ff00'];

// ─── Board rendering ──────────────────────────────────────────────────────────

interface RenderOpts {
  boardW: number;
  pegPositions: boolean[][];
  ballRow: number | null;
  ballCol: number | null;
  trail: { row: number; col: number }[];
  outcome: number | null;
  bucketW: number;
}

function renderBoardRows({
  boardW,
  pegPositions,
  ballRow,
  ballCol,
  trail,
  outcome,
  bucketW,
}: RenderOpts): string[] {
  const rows: string[] = [];

  for (let r = 0; r < BOARD_H; r++) {
    let line = '';
    for (let c = 0; c < boardW; c++) {
      const isTrail = trail.some(
        (t) => Math.round(t.row) === r && Math.round(t.col) === c
      );
      const isBall =
        ballRow !== null &&
        ballCol !== null &&
        Math.round(ballRow) === r &&
        Math.round(ballCol) === c;

      if (isBall) {
        line += chalk.bold.white('O');
      } else if (isTrail) {
        line += chalk.dim.white('\u00B7');          // middle-dot ·
      } else if (pegPositions[r]?.[c]) {
        line += chalk.dim.cyan('+');
      } else {
        line += ' ';
      }
    }
    rows.push('\u2502' + line + '\u2502');           // │ row │
  }

  // Bucket row
  const buckets = BUCKET_MULTIPLIERS.map((m, i) => {
    const label = BUCKET_CHARS[i].padStart(3).padEnd(bucketW - 1);
    const isWin = outcome === m;
    return isWin ? chalk.bold.yellow(label) : chalk.dim.white(label);
  }).join(chalk.dim.white('\u2502'));                // │

  const bucketTop =
    '\u251C' +                                       // ├
    BUCKET_MULTIPLIERS.map(() => '\u2500'.repeat(bucketW - 1)).join('\u252C') +
    '\u2524';                                        // ┤
  const bucketBot =
    '\u2514' +                                       // └
    BUCKET_MULTIPLIERS.map(() => '\u2500'.repeat(bucketW - 1)).join('\u2534') +
    '\u2518';                                        // ┘

  rows.push(chalk.dim.green(bucketTop));
  rows.push('\u2502' + buckets + '\u2502');
  rows.push(chalk.dim.green(bucketBot));

  return rows;
}

// ─── Border helpers ───────────────────────────────────────────────────────────

function borderH(width: number, left: string, fill: string, right: string): string {
  return left + fill.repeat(width) + right;
}

// ─── Component ───────────────────────────────────────────────────────────────

interface PachinkoBoardProps {
  runId?: string;    // used as RNG seed — new runId = new drop path
}

export function PachinkoBoard({ runId = 'default' }: PachinkoBoardProps) {
  const { stdout } = useStdout();
  const termW = stdout?.columns ?? 100;

  const rightW = Math.max(MIN_RIGHT_W, Math.floor(termW * RIGHT_PANEL_RATIO));
  const leftW = termW - rightW - 1;           // -1 for divider
  const boardW = rightW - 4;                  // -4 for borders + padding
  const bucketW = Math.floor(boardW / NUM_BUCKETS);

  const buffer = useStreamBuffer();
  const isStreaming = useIsStreaming();
  const latencyMs = useLatencyP50();
  const { setPachinkoOutcome, clearPachinkoOutcome, pachinkoIsJackpot, flashFrames: _f } = useCasino();
  const flashFrames = useStore((s) => s.casino.pachinkoOutcome === null ? 0 : s.casino.pachinkoIsJackpot ? 20 : 0);

  const { state, startDrop, reset } = usePachinko({
    boardW,
    latencyMs,
    seed: runId,
  });

  // Start drop when streaming begins; reset when idle
  useEffect(() => {
    if (isStreaming && !state.isDropping && state.outcome === null) {
      startDrop();
      clearPachinkoOutcome();
    }
  }, [isStreaming, state.isDropping, state.outcome, startDrop, clearPachinkoOutcome]);

  // Commit outcome to Zustand when ball lands
  useEffect(() => {
    if (state.outcome !== null && state.ball !== null) {
      const bucketIdx = Math.min(
        NUM_BUCKETS - 1,
        Math.max(0, Math.floor(state.ball.col / bucketW))
      );
      setPachinkoOutcome({
        label: BUCKET_CHARS[bucketIdx],
        value: state.outcome,
        colIndex: bucketIdx,
      });
    }
  }, [state.outcome, state.ball, bucketW, setPachinkoOutcome]);

  // ── Render ────────────────────────────────────────────────────────────────

  const isFlashing = state.isJackpot && state.flashFrames > 0;

  const boardRows = renderBoardRows({
    boardW,
    pegPositions: state.pegPositions,
    ballRow: state.ball?.row ?? null,
    ballCol: state.ball?.col ?? null,
    trail: state.trail,
    outcome: state.outcome,
    bucketW,
  });

  // Border strings
  const topBorder = borderH(rightW - 2, '\u250C', '\u2500', '\u2510');
  const titleLine = '\u2502' + chalk.cyan(' PACHINKO'.padEnd(rightW - 2)) + '\u2502';
  const divider   = borderH(rightW - 2, '\u251C', '\u2500', '\u2524');

  // Trim stream buffer to fit left panel height
  const streamLines = buffer.split('\n').slice(-BOARD_H);

  // Outcome banner (shown after drop)
  const outcomeLine = state.outcome !== null
    ? state.isJackpot
      ? chalk.bold.yellow(`  JACKPOT  ${state.outcome}x  `)
      : chalk.bold.green(`  ${state.outcome}x  `)
    : chalk.dim.white('  DROPPING... ');

  return (
    <Box flexDirection="row" width={termW}>

      {/* ── Left panel: inference stream ── */}
      <Box
        flexDirection="column"
        width={leftW}
        borderStyle="single"
        borderColor="cyan"
        paddingLeft={1}
        paddingRight={1}
        overflowY="hidden"
      >
        <Text color="cyan" bold>INFERENCE STREAM</Text>
        <Text color="greenBright" dimColor>{'─'.repeat(Math.max(0, leftW - 6))}</Text>
        {streamLines.map((line, i) => (
          <Text key={i} wrap="truncate">{line || ' '}</Text>
        ))}
      </Box>

      {/* ── Right panel: pachinko board ── */}
      <Box flexDirection="column" width={rightW} paddingLeft={1}>

        {/* Top border — gradient when jackpot flashing */}
        {isFlashing ? (
          <Gradient colors={JACKPOT_COLORS}>
            <Text>{topBorder}</Text>
          </Gradient>
        ) : (
          <Text color="green">{topBorder}</Text>
        )}

        {/* Title */}
        {isFlashing ? (
          <Gradient colors={JACKPOT_COLORS}>
            <Text>{titleLine}</Text>
          </Gradient>
        ) : (
          <Text color="green">{titleLine}</Text>
        )}

        <Text color="green">{divider}</Text>

        {/* Board rows */}
        {boardRows.map((row, i) => (
          <Text key={i}>{row}</Text>
        ))}

        {/* Outcome banner */}
        {state.outcome !== null && (
          isFlashing ? (
            <Gradient colors={JACKPOT_COLORS}>
              <Text bold>{outcomeLine}</Text>
            </Gradient>
          ) : (
            <Text>{outcomeLine}</Text>
          )
        )}
      </Box>

    </Box>
  );
}
