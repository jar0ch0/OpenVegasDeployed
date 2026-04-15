/**
 * store/index.ts
 *
 * Root Zustand store. Combines all slices.
 *
 * Usage in components:
 *   const isStreaming  = useStore(s => s.stream.isStreaming);
 *   const remainingV   = useStore(s => s.budget.remainingV);
 *   const triggerSlots = useStore(s => s.casino.triggerSlots);
 *
 * Usage outside React (IPC layer, budget charge handler):
 *   import { store } from '@/store';
 *   store.getState().casino.pushTickerEvent('[WIN] ...');
 */

import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';
import { type CasinoSlice, createCasinoSlice } from './casinoSlice';

// ─── Stream slice ─────────────────────────────────────────────────────────────

interface StreamSlice {
  buffer: string;
  isStreaming: boolean;
  streamError: string | null;
  appendBuffer: (chunk: string) => void;
  setStreaming: (v: boolean) => void;
  clearBuffer: () => void;
}

// ─── Session slice ────────────────────────────────────────────────────────────

interface SessionSlice {
  jwt: string | null;
  userId: string | null;
  allowScopes: Set<string>;
  expiresAt: number;
  setJwt: (jwt: string, expiresAt: number) => void;
  clearSession: () => void;
}

// ─── Budget slice ─────────────────────────────────────────────────────────────

interface BudgetSlice {
  budgetSessionId: string | null;
  lockedV: number;
  remainingV: number;
  drainedV: number;
  autoAcceptActive: boolean;
  lockBudget: (sessionId: string, amountV: number) => void;
  decrementRemaining: (amountV: number) => void;
  clearBudget: () => void;
}

// ─── Chat slice ───────────────────────────────────────────────────────────────

interface ChatSlice {
  approvalMode: 'ask' | 'allow' | 'exclude';
  planMode: boolean;
  workspaceRoot: string;
  currentRunId: string | null;
  setApprovalMode: (m: 'ask' | 'allow' | 'exclude') => void;
  setRunId: (id: string | null) => void;
}

// ─── UI slice — exit trap + micro-advance overlay state ───────────────────────

interface UISlice {
  // Exit trap — set true on first Ctrl+C; second Ctrl+C / 'y' calls exit()
  isExiting: boolean;
  // Micro-advance — set true when inference is blocked by empty wallet
  needsMicroAdvance: boolean;
  // Pending prompt to resume after micro-advance is accepted
  pendingPrompt: string | null;
  setExiting: (v: boolean) => void;
  setNeedsMicroAdvance: (prompt: string) => void;
  clearMicroAdvance: () => void;
}

// ─── Metrics slice — streak, rakeback, lifetime burn tracking ─────────────────

interface MetricsSlice {
  // Total $V burned in the current session (used to gate rakeback threshold)
  totalBurnedV: number;
  // Daily login streak (fetched from server on mount)
  dailyStreakDays: number;
  // ISO date of last recorded active day ("YYYY-MM-DD")
  lastActiveDate: string | null;
  // Rakeback notification state — 5% of each 10,000 $V burned
  rakebackPending: boolean;
  rakebackAmountV: number;
  incrementBurnedV: (v: number) => void;
  recordDailyStreak: (days: number, date: string) => void;
  setRakebackPending: (amountV: number) => void;
  claimRakeback: () => void;
}

// ─── Root store type ──────────────────────────────────────────────────────────

interface RootStore {
  stream: StreamSlice;
  session: SessionSlice;
  budget: BudgetSlice;
  chat: ChatSlice;
  ui: UISlice;
  metrics: MetricsSlice;
  casino: CasinoSlice;
}

// ─── Root store ───────────────────────────────────────────────────────────────

export const useStore = create<RootStore>()(
  immer((set) => ({
    // ── Stream ──────────────────────────────────────────────────────────────
    stream: {
      buffer: '',
      isStreaming: false,
      streamError: null,
      appendBuffer: (chunk) =>
        set((s) => { s.stream.buffer += chunk; }),
      setStreaming: (v) =>
        set((s) => { s.stream.isStreaming = v; }),
      clearBuffer: () =>
        set((s) => { s.stream.buffer = ''; s.stream.streamError = null; }),
    },

    // ── Session ─────────────────────────────────────────────────────────────
    session: {
      jwt: null,
      userId: null,
      allowScopes: new Set(),
      expiresAt: 0,
      setJwt: (jwt, expiresAt) =>
        set((s) => { s.session.jwt = jwt; s.session.expiresAt = expiresAt; }),
      clearSession: () =>
        set((s) => {
          s.session.jwt = null;
          s.session.userId = null;
          s.session.expiresAt = 0;
        }),
    },

    // ── Budget ──────────────────────────────────────────────────────────────
    budget: {
      budgetSessionId: null,
      lockedV: 0,
      remainingV: 0,
      drainedV: 0,
      autoAcceptActive: false,
      lockBudget: (sessionId, amountV) =>
        set((s) => {
          s.budget.budgetSessionId = sessionId;
          s.budget.lockedV = amountV;
          s.budget.remainingV = amountV;
          s.budget.drainedV = 0;
          s.budget.autoAcceptActive = true;
        }),
      decrementRemaining: (amountV) =>
        set((s) => {
          s.budget.remainingV = Math.max(0, s.budget.remainingV - amountV);
          s.budget.drainedV += amountV;
          if (s.budget.remainingV === 0) s.budget.autoAcceptActive = false;
        }),
      clearBudget: () =>
        set((s) => {
          s.budget.budgetSessionId = null;
          s.budget.lockedV = 0;
          s.budget.remainingV = 0;
          s.budget.drainedV = 0;
          s.budget.autoAcceptActive = false;
        }),
    },

    // ── Chat ────────────────────────────────────────────────────────────────
    chat: {
      approvalMode: 'ask',
      planMode: false,
      workspaceRoot: process.cwd(),
      currentRunId: null,
      setApprovalMode: (m) =>
        set((s) => { s.chat.approvalMode = m; }),
      setRunId: (id) =>
        set((s) => { s.chat.currentRunId = id; }),
    },

    // ── UI ──────────────────────────────────────────────────────────────────
    ui: {
      isExiting: false,
      needsMicroAdvance: false,
      pendingPrompt: null,
      setExiting: (v) =>
        set((s) => { s.ui.isExiting = v; }),
      setNeedsMicroAdvance: (prompt) =>
        set((s) => {
          s.ui.needsMicroAdvance = true;
          s.ui.pendingPrompt = prompt;
        }),
      clearMicroAdvance: () =>
        set((s) => {
          s.ui.needsMicroAdvance = false;
          s.ui.pendingPrompt = null;
        }),
    },

    // ── Metrics ─────────────────────────────────────────────────────────────
    metrics: {
      totalBurnedV: 0,
      dailyStreakDays: 0,
      lastActiveDate: null,
      rakebackPending: false,
      rakebackAmountV: 0,
      incrementBurnedV: (v) =>
        set((s) => {
          const prev = s.metrics.totalBurnedV;
          const next = prev + v;
          s.metrics.totalBurnedV = next;
          // Gate: every 10,000 $V burned → 5% rakeback (500 $V)
          const prevTier = Math.floor(prev / 10_000);
          const nextTier = Math.floor(next / 10_000);
          if (nextTier > prevTier && !s.metrics.rakebackPending) {
            s.metrics.rakebackPending = true;
            s.metrics.rakebackAmountV = 500;
          }
        }),
      recordDailyStreak: (days, date) =>
        set((s) => {
          s.metrics.dailyStreakDays = days;
          s.metrics.lastActiveDate = date;
        }),
      setRakebackPending: (amountV) =>
        set((s) => {
          s.metrics.rakebackPending = true;
          s.metrics.rakebackAmountV = amountV;
        }),
      claimRakeback: () =>
        set((s) => {
          s.metrics.rakebackPending = false;
          s.metrics.rakebackAmountV = 0;
        }),
    },

    // ── Casino — factory pattern keeps slice logic co-located ───────────────
    casino: createCasinoSlice((fn) => set((s) => fn(s.casino))),
  }))
);

// ─── Named selector hooks ─────────────────────────────────────────────────────
// Stable references — avoids inline arrow functions in component renders.

export const useIsStreaming      = () => useStore((s) => s.stream.isStreaming);
export const useStreamBuffer     = () => useStore((s) => s.stream.buffer);
export const useBudgetRemaining  = () => useStore((s) => s.budget.remainingV);
export const useBudgetActive     = () => useStore((s) => s.budget.autoAcceptActive);
export const useCasino           = () => useStore((s) => s.casino);
export const useLatencyP50       = () => useStore((s) => s.casino.inferenceLatencyP50Ms);
export const useUI               = () => useStore((s) => s.ui);
export const useMetrics          = () => useStore((s) => s.metrics);
export const useIsExiting        = () => useStore((s) => s.ui.isExiting);
export const useNeedsMicroAdvance = () => useStore((s) => s.ui.needsMicroAdvance);
export const useRakebackPending  = () => useStore((s) => s.metrics.rakebackPending);

// Direct store access for non-React code (IPC layer, budget charge handler)
export const store = useStore;
