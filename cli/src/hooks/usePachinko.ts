/**
 * usePachinko.ts
 *
 * Physics engine for the PachinkoBoard animation.
 *
 * BOARD GEOMETRY
 * ─────────────
 *   boardW  columns  (inner width of the right panel, typically 38)
 *   BOARD_H rows     (fixed at 16 — peg area only, not counting bucket row)
 *
 *   numBuckets = 7
 *   bucketW    = floor(boardW / numBuckets)          ← width of each bucket slot
 *
 *   Peg layout — staggered grid:
 *     Even peg-rows (0, 2, 4…): pegs at cols  bucketW, 2*bucketW, …, 6*bucketW
 *     Odd  peg-rows (1, 3, 5…): pegs at cols  bucketW/2, 3*bucketW/2, …
 *
 *   Ball starts at col = floor(boardW / 2)  (over the center 10x bucket)
 *   Ball falls toward bucket col; each peg contact deflects it ±deflectW
 *
 * LATENCY BINDING
 * ──────────────
 *   The caller passes `latencyMs` (the P50 inference latency from the store).
 *   drop speed (rows/frame) = BOARD_H / (latencyMs / FRAME_MS)
 *   So if latency = 3000ms and FRAME_MS = 40 → 75 frames total → 16/75 ≈ 0.21 rows/frame
 *   The ball reaches the bucket row right as the inference stream completes.
 *
 * SEEDED RNG
 * ─────────
 *   Deflections use an xorshift32 seeded by the sessionId hash, making the
 *   drop path deterministic and re-playable (provably-fair mechanic).
 */

import { useState, useCallback, useRef } from 'react';
import { useAnimationFrame, FRAME_MS } from './useAnimationFrame';

export const BOARD_H = 16;
export const NUM_BUCKETS = 7;
export const BUCKET_MULTIPLIERS = [1, 2, 5, 10, 5, 2, 1];
const TRAIL_LEN = 3;

export interface PachinkoBall {
  row: number;   // float — fractional rows allow smooth sub-frame interpolation
  col: number;   // float
}

export interface PachinkoState {
  ball: PachinkoBall | null;
  trail: PachinkoBall[];            // last TRAIL_LEN positions (for motion blur)
  outcome: number | null;           // multiplier (null while dropping)
  isDropping: boolean;
  isJackpot: boolean;               // outcome >= 10
  flashFrames: number;              // jackpot border-flash countdown
  // Honest near-miss: ball physically passed within 40% of jackpot bucket
  // without landing in it. NOT rigged — purely derived from actual ball path.
  nearMiss: boolean;
  pegPositions: boolean[][];        // [row][col] — true if peg at this cell
  bucketW: number;
}

export interface UsePachinkoOptions {
  boardW: number;
  latencyMs: number;    // from useLatencyP50() — binds drop speed to inference timing
  seed: string;         // sessionId or runId — deterministic deflections
}

export interface UsePachinkoReturn {
  state: PachinkoState;
  startDrop: () => void;
  reset: () => void;
}

// ─── Seeded RNG ──────────────────────────────────────────────────────────────

function hashSeed(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function makeXorshift(seed: string): () => number {
  let state = hashSeed(seed) || 1;
  return () => {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    return ((state >>> 0) / 0xffffffff);
  };
}

// ─── Static board geometry ───────────────────────────────────────────────────

function buildPegGrid(boardW: number): boolean[][] {
  const bucketW = Math.floor(boardW / NUM_BUCKETS);
  const grid: boolean[][] = [];

  for (let r = 0; r < BOARD_H; r++) {
    const row = new Array<boolean>(boardW).fill(false);

    // Only put pegs on rows 1, 3, 5… (every other row for readability)
    if (r % 2 === 1) {
      const isEvenPegRow = Math.floor(r / 2) % 2 === 0;
      for (let b = 0; b < NUM_BUCKETS - 1; b++) {
        const col = isEvenPegRow
          ? bucketW * (b + 1)                   // between bucket boundaries
          : Math.round(bucketW * (b + 0.5));    // at bucket midpoints
        if (col > 0 && col < boardW - 1) row[col] = true;
      }
    }
    grid.push(row);
  }
  return grid;
}

// ─── Hook ────────────────────────────────────────────────────────────────────

export function usePachinko({
  boardW,
  latencyMs,
  seed,
}: UsePachinkoOptions): UsePachinkoReturn {
  const bucketW = Math.floor(boardW / NUM_BUCKETS);

  // Pre-compute static peg grid — only recomputed when boardW changes
  const [pegPositions] = useState<boolean[][]>(() => buildPegGrid(boardW));

  const [state, setState] = useState<PachinkoState>({
    ball: null,
    trail: [],
    outcome: null,
    isDropping: false,
    isJackpot: false,
    flashFrames: 0,
    nearMiss: false,
    pegPositions,
    bucketW,
  });

  // Seeded RNG ref — recreated on seed change, not on every render
  const rngRef = useRef<() => number>(makeXorshift(seed));
  const prevSeedRef = useRef<string>(seed);
  if (seed !== prevSeedRef.current) {
    rngRef.current = makeXorshift(seed);
    prevSeedRef.current = seed;
  }

  // rowSpeed is derived from latencyMs each frame — no stale closure risk
  const latencyRef = useRef(latencyMs);
  latencyRef.current = latencyMs;

  // Tracks minimum distance from ball to jackpot bucket center across a drop.
  // Jackpot bucket is index 3 (10x); center col = 3.5 * bucketW.
  // Reset on each startDrop(). Read on landing to compute nearMiss.
  const minDistToJackpotRef = useRef(Infinity);

  const startDrop = useCallback(() => {
    rngRef.current = makeXorshift(seed);           // reset RNG on each new drop
    minDistToJackpotRef.current = Infinity;        // reset near-miss tracker
    setState((prev) => ({
      ...prev,
      ball: { row: 0, col: Math.floor(boardW / 2) },
      trail: [],
      outcome: null,
      isDropping: true,
      isJackpot: false,
      flashFrames: 0,
      nearMiss: false,
    }));
  }, [boardW, seed]);

  const reset = useCallback(() => {
    minDistToJackpotRef.current = Infinity;
    setState((prev) => ({
      ...prev,
      ball: null,
      trail: [],
      outcome: null,
      isDropping: false,
      isJackpot: false,
      flashFrames: 0,
      nearMiss: false,
    }));
  }, []);

  // Physics tick — runs every FRAME_MS while dropping
  useAnimationFrame(
    useCallback(() => {
      setState((prev) => {
        if (!prev.isDropping || !prev.ball) return prev;

        const rowSpeed = BOARD_H / (latencyRef.current / FRAME_MS);
        const newRowF = prev.ball.row + rowSpeed;
        let newColF = prev.ball.col;

        // ── Peg collision detection ───────────────────────────────────────────
        // Check the integer row the ball is about to enter.
        const prevRowI = Math.floor(prev.ball.row);
        const newRowI = Math.floor(newRowF);
        if (newRowI > prevRowI && newRowI < BOARD_H) {
          const row = prev.pegPositions[newRowI];
          if (row) {
            // Find nearest peg within ±1 column of current col
            const colI = Math.round(newColF);
            const searchRange = Math.ceil(bucketW / 2);
            for (let dc = -searchRange; dc <= searchRange; dc++) {
              const c = colI + dc;
              if (c >= 0 && c < boardW && row[c]) {
                // Deflect away from peg — seeded random determines direction
                const dir = rngRef.current() > 0.5 ? 1 : -1;
                const deflect = bucketW * 0.5 * dir;
                newColF = Math.max(1, Math.min(boardW - 2, newColF + deflect));
                break;
              }
            }
          }
        }

        // ── Near-miss tracking ────────────────────────────────────────────────
        // Jackpot bucket (10x) is index 3; its center column = 3.5 * bucketW.
        // Track minimum distance from ball to that center across the whole drop.
        const jackpotCenter = 3.5 * bucketW;
        const distToJackpot = Math.abs(newColF - jackpotCenter);
        if (distToJackpot < minDistToJackpotRef.current) {
          minDistToJackpotRef.current = distToJackpot;
        }

        // ── Landing ───────────────────────────────────────────────────────────
        if (newRowF >= BOARD_H) {
          const bucketIdx = Math.min(
            NUM_BUCKETS - 1,
            Math.max(0, Math.floor(newColF / bucketW))
          );
          const multiplier = BUCKET_MULTIPLIERS[bucketIdx] ?? 1;
          const isJackpot = multiplier >= 10;

          // Near-miss: ball physically passed within 40% of jackpot bucket
          // width of the jackpot center without landing in it.
          const nearMissThreshold = bucketW * 0.4;
          const nearMiss =
            !isJackpot && minDistToJackpotRef.current < nearMissThreshold;

          return {
            ...prev,
            ball: { row: BOARD_H - 1, col: newColF },
            trail: [],
            isDropping: false,
            outcome: multiplier,
            isJackpot,
            nearMiss,
            flashFrames: isJackpot ? 20 : 0,   // 20 frames ≈ 800ms of flash
          };
        }

        // ── In-flight ─────────────────────────────────────────────────────────
        const newBall = { row: newRowF, col: newColF };
        const newTrail = [...prev.trail, { row: prev.ball.row, col: prev.ball.col }]
          .slice(-TRAIL_LEN);

        // Decrement flash countdown even while dropping (shouldn't fire, but safe)
        const flashFrames = Math.max(0, prev.flashFrames - 1);

        return { ...prev, ball: newBall, trail: newTrail, flashFrames };
      });
    }, [boardW, bucketW]),
    state.isDropping || state.flashFrames > 0
  );

  return { state, startDrop, reset };
}
