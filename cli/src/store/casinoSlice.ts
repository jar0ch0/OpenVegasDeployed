/**
 * casinoSlice.ts
 *
 * Zustand slice for slow-changing casino state shared across components.
 *
 * DESIGN RULE: High-frequency animation state (ball position, multiplier
 * value, reel symbols) lives in local component hooks — NOT here.
 * This slice stores outcomes, results, and cross-component flags only.
 */

// ─── Shared types ────────────────────────────────────────────────────────────

export interface MultiplierBucket {
  label: string;    // "1x", "2x", "10x"
  value: number;    // numeric multiplier
  colIndex: number; // which bucket column (0..numBuckets-1)
}

export interface GameResult {
  sessionId: string;
  timestamp: number;          // Unix ms
  wageredV: number;
  payoutV: number;
  netV: number;
  multiplier: number;
  inputTokens: number;
  outputTokens: number;
  model: string;
  provider: string;
  verifyHash: string;         // sha256 of session seed for FlexReceipt
}

export interface TickerEvent {
  id: string;
  text: string;               // "[!] @0xDev just minted 50,000 $V"
  ts: number;
}

// ─── Slice state ─────────────────────────────────────────────────────────────

export interface CasinoSliceState {
  // Pachinko outcome — set when ball lands
  pachinkoOutcome: MultiplierBucket | null;
  pachinkoIsJackpot: boolean;
  // Estimated inference latency used to bind ball drop speed.
  // Updated after every inference completion from InferenceResult.
  inferenceLatencyP50Ms: number;

  // SlotSpinner trigger — true when inference is initiated
  slotTrigger: boolean;

  // CrashCompiler — true while a bash tool execution is running
  crashIsRunning: boolean;
  crashCashOutV: number | null; // set when user cashes out

  // FlexReceipt — last completed game result
  lastResult: GameResult | null;
  showReceipt: boolean;

  // GlobalTicker event queue (capped at 50 events)
  tickerEvents: TickerEvent[];

  // Near-miss flag — true when ball passed within 40% of jackpot bucket without winning jackpot
  nearMiss: boolean;
}

// ─── Slice actions ───────────────────────────────────────────────────────────

export interface CasinoSliceActions {
  setPachinkoOutcome: (bucket: MultiplierBucket) => void;
  clearPachinkoOutcome: () => void;
  recordInferenceLatency: (ms: number) => void;

  triggerSlots: () => void;
  clearSlotTrigger: () => void;

  startCrash: () => void;
  stopCrash: () => void;
  recordCrashCashOut: (rewardV: number) => void;

  setLastResult: (result: GameResult) => void;
  showFlexReceipt: () => void;
  dismissFlexReceipt: () => void;

  pushTickerEvent: (text: string) => void;
  pruneTickerEvents: (maxAge: number) => void;

  setNearMiss: (v: boolean) => void;
  clearNearMiss: () => void;
}

export type CasinoSlice = CasinoSliceState & CasinoSliceActions;

// ─── Initial state ────────────────────────────────────────────────────────────

export const initialCasinoState: CasinoSliceState = {
  pachinkoOutcome: null,
  pachinkoIsJackpot: false,
  inferenceLatencyP50Ms: 3000,

  slotTrigger: false,

  crashIsRunning: false,
  crashCashOutV: null,

  lastResult: null,
  showReceipt: false,

  tickerEvents: [],
  nearMiss: false,
};

// ─── Slice factory (called by root store create()) ───────────────────────────

export function createCasinoSlice(
  set: (fn: (state: CasinoSlice) => void) => void
): CasinoSlice {
  return {
    ...initialCasinoState,

    setPachinkoOutcome: (bucket) =>
      set((s) => {
        s.pachinkoOutcome = bucket;
        s.pachinkoIsJackpot = bucket.value >= 10;
      }),

    clearPachinkoOutcome: () =>
      set((s) => {
        s.pachinkoOutcome = null;
        s.pachinkoIsJackpot = false;
      }),

    // Exponential moving average: 70% old, 30% new sample
    recordInferenceLatency: (ms) =>
      set((s) => {
        s.inferenceLatencyP50Ms =
          Math.round(s.inferenceLatencyP50Ms * 0.7 + ms * 0.3);
      }),

    triggerSlots: () => set((s) => { s.slotTrigger = true; }),
    clearSlotTrigger: () => set((s) => { s.slotTrigger = false; }),

    startCrash: () =>
      set((s) => {
        s.crashIsRunning = true;
        s.crashCashOutV = null;
      }),

    stopCrash: () => set((s) => { s.crashIsRunning = false; }),

    recordCrashCashOut: (rewardV) =>
      set((s) => {
        s.crashCashOutV = rewardV;
        s.crashIsRunning = false;
      }),

    setLastResult: (result) => set((s) => { s.lastResult = result; }),
    showFlexReceipt: () => set((s) => { s.showReceipt = true; }),
    dismissFlexReceipt: () => set((s) => { s.showReceipt = false; }),

    pushTickerEvent: (text) =>
      set((s) => {
        const event: TickerEvent = {
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
          text,
          ts: Date.now(),
        };
        s.tickerEvents = [...s.tickerEvents.slice(-49), event];
      }),

    pruneTickerEvents: (maxAge) =>
      set((s) => {
        const cutoff = Date.now() - maxAge;
        s.tickerEvents = s.tickerEvents.filter((e) => e.ts >= cutoff);
      }),

    setNearMiss: (v) => set((s) => { s.nearMiss = v; }),
    clearNearMiss: () => set((s) => { s.nearMiss = false; }),
  };
}
