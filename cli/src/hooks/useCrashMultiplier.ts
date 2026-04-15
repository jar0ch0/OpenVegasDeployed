/**
 * useCrashMultiplier.ts
 *
 * Manages the Crash Compiler mini-game multiplier.
 *
 * The multiplier grows continuously while a bash execution is running.
 * Formula:  mult(t) = 1.0 + t_seconds * GROWTH_RATE
 * (linear growth keeps the math transparent to users; exponential would be
 * more dramatic but harder to reason about for a CLI tool context)
 *
 * GROWTH_RATE is configurable so it can be tuned per execution type:
 *   - Standard test suite:  0.15  (1x → ~2.5x over 10 seconds)
 *   - Long build:           0.08  (1x → ~1.8x over 10 seconds)
 *
 * Cash-out:
 *   User presses Space → cashOut() is called → component calls
 *   POST /budget/charge to earn a flat reward scaled by the multiplier.
 *   The Zustand store is updated via casinoSlice.recordCrashCashOut().
 *   Animation stays visible for LINGER_MS after cash-out before onComplete fires.
 *
 * History:
 *   Snapshots of the multiplier are kept every SNAPSHOT_INTERVAL_MS for
 *   the bar chart display in CrashCompiler.tsx.
 */

import { useState, useCallback, useRef } from 'react';
import { useAnimationFrame } from './useAnimationFrame';

const SNAPSHOT_INTERVAL_MS = 400;  // take a bar-chart snapshot every 400ms
const MAX_HISTORY_BARS = 14;       // number of bars shown in the chart
const LINGER_MS = 1200;            // stay visible after cash-out
const BASE_MULT = 1.0;

export interface CrashMultiplierSnapshot {
  mult: number;
  isCashOut: boolean;              // true for the snapshot taken at cash-out
}

export interface CrashMultiplierState {
  multiplier: number;
  elapsedMs: number;
  cashedOut: boolean;
  history: CrashMultiplierSnapshot[];   // for bar chart; oldest first
  lingerFrames: number;                 // countdown after cash-out before done
}

export interface UseCrashMultiplierOptions {
  isRunning: boolean;
  growthRate?: number;             // multiplier points per second (default 0.15)
  onCashOut?: (mult: number) => void;   // called once when user cashes out
  onComplete?: () => void;         // called after linger period ends
}

export interface UseCrashMultiplierReturn {
  state: CrashMultiplierState;
  cashOut: () => void;             // bind to Space key in component
}

export function useCrashMultiplier({
  isRunning,
  growthRate = 0.15,
  onCashOut,
  onComplete,
}: UseCrashMultiplierOptions): UseCrashMultiplierReturn {
  const [state, setState] = useState<CrashMultiplierState>({
    multiplier: BASE_MULT,
    elapsedMs: 0,
    cashedOut: false,
    history: [],
    lingerFrames: 0,
  });

  // Track time since last snapshot without causing a state update
  const lastSnapshotRef = useRef<number>(0);
  const growthRateRef = useRef(growthRate);
  growthRateRef.current = growthRate;

  const cashOut = useCallback(() => {
    setState((prev) => {
      if (prev.cashedOut) return prev;
      const lingerFrames = Math.ceil(LINGER_MS / 40);
      onCashOut?.(prev.multiplier);
      return {
        ...prev,
        cashedOut: true,
        lingerFrames,
        history: [
          ...prev.history.slice(-(MAX_HISTORY_BARS - 1)),
          { mult: prev.multiplier, isCashOut: true },
        ],
      };
    });
  }, [onCashOut]);

  useAnimationFrame(
    useCallback((deltaMs: number) => {
      setState((prev) => {
        // Linger countdown after cash-out
        if (prev.cashedOut) {
          const remaining = prev.lingerFrames - 1;
          if (remaining <= 0) { onComplete?.(); }
          return { ...prev, lingerFrames: Math.max(0, remaining) };
        }

        if (!isRunning) return prev;

        const newElapsed = prev.elapsedMs + deltaMs;
        const newMult = parseFloat(
          (BASE_MULT + (newElapsed / 1000) * growthRateRef.current).toFixed(2)
        );

        // Snapshot for bar chart
        let newHistory = prev.history;
        if (newElapsed - lastSnapshotRef.current >= SNAPSHOT_INTERVAL_MS) {
          lastSnapshotRef.current = newElapsed;
          newHistory = [
            ...prev.history.slice(-(MAX_HISTORY_BARS - 1)),
            { mult: newMult, isCashOut: false },
          ];
        }

        return { ...prev, multiplier: newMult, elapsedMs: newElapsed, history: newHistory };
      });
    }, [isRunning, onComplete]),
    isRunning || state.cashedOut
  );

  return { state, cashOut };
}
