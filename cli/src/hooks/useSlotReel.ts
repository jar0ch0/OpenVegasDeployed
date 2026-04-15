/**
 * useSlotReel.ts
 *
 * Drives the three-reel slot animation that plays while the AI inference
 * request is in flight (before text starts streaming).
 *
 * REEL LIFECYCLE
 * ─────────────
 *   SPINNING  →  reel cycles through symbolPool rapidly
 *   LOCKING   →  reel decelerates (increasing tick interval per symbol)
 *   LOCKED    →  reel shows final symbol, stops animating
 *
 * The three reels lock sequentially with configurable delays:
 *   Reel 0 locks at lockDelays[0] ms after startSpin()
 *   Reel 1 locks at lockDelays[1] ms
 *   Reel 2 locks at lockDelays[2] ms
 *
 * Final symbols are deterministic: derived by hashing (seed + reelIndex)
 * through the symbol pool — same seed always shows same final symbols.
 *
 * INTEGRATION: The SlotSpinner component calls startSpin() when
 * streamSlice.isStreaming transitions false→true. It hides automatically
 * once all reels are locked and a brief display pause has elapsed.
 */

import { useState, useCallback, useRef } from 'react';
import { useAnimationFrame, FRAME_MS } from './useAnimationFrame';

export const SYMBOL_POOL = [
  '@', '#', '$', '%', '&', '*', '?', '!',
  '+', '-', '=', '~', '^', '0', '1', '2',
  '3', '4', '5', '6', '7', '8', '9', 'A',
  'B', 'C', 'D', 'E', 'F', 'X', 'Y', 'Z',
];

const DEFAULT_LOCK_DELAYS = [700, 1200, 1700] as const;  // ms per reel
const DISPLAY_LINGER_MS = 600;   // stay visible after all reels lock

type ReelStatus = 'idle' | 'spinning' | 'locking' | 'locked';

interface ReelState {
  symbol: string;
  status: ReelStatus;
  finalSymbol: string;
  // Deceleration: each lock phase doubles the tick interval up to this floor
  ticksPerSymbol: number;
  tickAccum: number;
}

export interface SlotReelState {
  reels: [ReelState, ReelState, ReelState];
  running: boolean;
  allLocked: boolean;
  lingerFrames: number;
}

export interface UseSlotReelReturn {
  symbols: [string, string, string];
  statuses: [ReelStatus, ReelStatus, ReelStatus];
  allLocked: boolean;
  visible: boolean;                // false once linger expires
  startSpin: (seed: string) => void;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function seedSymbol(seed: string, reelIndex: number): string {
  let h = 0x811c9dc5;
  const s = seed + reelIndex;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return SYMBOL_POOL[(h >>> 0) % SYMBOL_POOL.length];
}

function makeReelState(finalSymbol: string): ReelState {
  return {
    symbol: SYMBOL_POOL[Math.floor(Math.random() * SYMBOL_POOL.length)],
    status: 'spinning',
    finalSymbol,
    ticksPerSymbol: 1,   // cycles 1 symbol per frame at full speed
    tickAccum: 0,
  };
}

// ─── Hook ────────────────────────────────────────────────────────────────────

export function useSlotReel(
  lockDelays: readonly [number, number, number] = DEFAULT_LOCK_DELAYS
): UseSlotReelReturn {
  const [state, setState] = useState<SlotReelState>({
    reels: [
      makeReelState('O'),
      makeReelState('V'),
      makeReelState('G'),
    ],
    running: false,
    allLocked: false,
    lingerFrames: 0,
  });

  // Track elapsed ms from spin start without triggering re-renders
  const spinStartRef = useRef<number>(0);

  const startSpin = useCallback((seed: string) => {
    spinStartRef.current = Date.now();
    setState({
      reels: [
        makeReelState(seedSymbol(seed, 0)),
        makeReelState(seedSymbol(seed, 1)),
        makeReelState(seedSymbol(seed, 2)),
      ],
      running: true,
      allLocked: false,
      lingerFrames: 0,
    });
  }, []);

  useAnimationFrame(
    useCallback((_delta: number) => {
      const elapsed = Date.now() - spinStartRef.current;

      setState((prev) => {
        if (!prev.running) return prev;

        // Linger countdown
        if (prev.allLocked) {
          const rem = prev.lingerFrames - 1;
          return { ...prev, lingerFrames: Math.max(0, rem), running: rem > 0 };
        }

        const newReels = prev.reels.map((reel, i): ReelState => {
          const lockAt = lockDelays[i as 0 | 1 | 2];

          if (reel.status === 'locked') return reel;

          if (elapsed >= lockAt) {
            // Decelerate: increase ticks needed before next symbol change
            const newTicks = Math.min(reel.ticksPerSymbol + 1, 6);
            const newAccum = reel.tickAccum + 1;

            if (newAccum >= newTicks) {
              // Close enough to final symbol — snap to lock
              const distanceToFinal = SYMBOL_POOL.indexOf(reel.finalSymbol) -
                SYMBOL_POOL.indexOf(reel.symbol);
              const atFinal = Math.abs(distanceToFinal) <= 2;
              if (atFinal || newTicks >= 6) {
                return { ...reel, symbol: reel.finalSymbol, status: 'locked', tickAccum: 0 };
              }
              // Shuffle toward final symbol
              const dir = distanceToFinal >= 0 ? 1 : -1;
              const nextIdx = (SYMBOL_POOL.indexOf(reel.symbol) + dir + SYMBOL_POOL.length)
                % SYMBOL_POOL.length;
              return {
                ...reel,
                symbol: SYMBOL_POOL[nextIdx],
                status: 'locking',
                ticksPerSymbol: newTicks,
                tickAccum: 0,
              };
            }
            return { ...reel, status: 'locking', ticksPerSymbol: newTicks, tickAccum: newAccum };
          }

          // Full-speed spinning: advance symbol every ticksPerSymbol frames
          const newAccum = reel.tickAccum + 1;
          if (newAccum >= reel.ticksPerSymbol) {
            const nextIdx = (SYMBOL_POOL.indexOf(reel.symbol) + 1) % SYMBOL_POOL.length;
            return { ...reel, symbol: SYMBOL_POOL[nextIdx], tickAccum: 0 };
          }
          return { ...reel, tickAccum: newAccum };
        }) as [ReelState, ReelState, ReelState];

        const allLocked = newReels.every((r) => r.status === 'locked');
        const lingerFrames = allLocked && !prev.allLocked
          ? Math.ceil(DISPLAY_LINGER_MS / FRAME_MS)
          : prev.lingerFrames;

        return { ...prev, reels: newReels, allLocked, lingerFrames };
      });
    }, [lockDelays]),
    state.running
  );

  return {
    symbols: state.reels.map((r) => r.symbol) as [string, string, string],
    statuses: state.reels.map((r) => r.status) as [ReelStatus, ReelStatus, ReelStatus],
    allLocked: state.allLocked,
    visible: state.running || state.allLocked,
    startSpin,
  };
}
