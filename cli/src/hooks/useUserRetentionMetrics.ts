/**
 * useUserRetentionMetrics.ts
 *
 * Mounts once in ChatScreen. Handles two disclosed engagement mechanics:
 *
 * 1. DAILY STREAK PING
 *    On mount, POST /user/streak with today's ISO date. Server returns
 *    { streak_days: number, date: string }. Stored in metricsSlice so
 *    any component can read it. Streak days are purely informational —
 *    no hidden RTP changes occur.
 *
 * 2. RAKEBACK THRESHOLD (disclosed, user-visible)
 *    Watches metrics.totalBurnedV via a Zustand subscription.
 *    Every time totalBurnedV crosses a new 10,000 $V tier, the server
 *    is told to deposit 500 $V rakeback to the user's wallet
 *    (POST /user/rakeback). metricsSlice.rakebackPending = true triggers
 *    the <RakebackClaim> toast notification.
 *
 * DESIGN NOTE
 *    The subscription runs outside React via store.subscribe() so it
 *    doesn't depend on the component re-render cycle. The useEffect
 *    handles mount/unmount and the streak ping only.
 *
 * ZUSTAND READS/WRITES
 *   metrics.totalBurnedV          → subscription target
 *   metrics.recordDailyStreak()   → called on streak response
 *   metrics.setRakebackPending()  → called when server confirms deposit
 */

import { useEffect } from 'react';
import { store } from '../store';

const RAKEBACK_TIER_V = 10_000;  // every 10k $V burned
const RAKEBACK_PCT    = 0.05;    // 5% = 500 $V per tier

export interface UseUserRetentionMetricsOptions {
  jwt: string | null;
  apiBase: string;       // e.g. "https://api.openvegas.gg"
}

export function useUserRetentionMetrics({
  jwt,
  apiBase,
}: UseUserRetentionMetricsOptions): void {
  // ── Daily streak ping — fires once on mount ─────────────────────────────────
  useEffect(() => {
    if (!jwt) return;

    const today = new Date().toISOString().slice(0, 10); // "YYYY-MM-DD"

    fetch(`${apiBase}/user/streak`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${jwt}`,
      },
      body: JSON.stringify({ date: today }),
    })
      .then((r) => r.ok ? r.json() : null)
      .then((data: { streak_days?: number; date?: string } | null) => {
        if (data?.streak_days != null && data.date) {
          store.getState().metrics.recordDailyStreak(data.streak_days, data.date);
        }
      })
      .catch(() => {
        // Network failure — streak is cosmetic, safe to swallow
      });
  }, [jwt, apiBase]);

  // ── Rakeback threshold subscription — runs outside React render cycle ───────
  useEffect(() => {
    if (!jwt) return;

    // Track the last tier we processed so we don't double-fire on re-subscribe
    let lastProcessedTier = Math.floor(
      store.getState().metrics.totalBurnedV / RAKEBACK_TIER_V
    );

    const unsub = store.subscribe((state) => {
      const currentTier = Math.floor(state.metrics.totalBurnedV / RAKEBACK_TIER_V);
      if (currentTier <= lastProcessedTier) return;
      lastProcessedTier = currentTier;

      const rakebackV = Math.round(RAKEBACK_TIER_V * RAKEBACK_PCT);

      fetch(`${apiBase}/user/rakeback`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${jwt}`,
        },
        body: JSON.stringify({ amount_v: rakebackV }),
      })
        .then((r) => r.ok ? r.json() : null)
        .then((data: { deposited_v?: number } | null) => {
          const deposited = data?.deposited_v ?? rakebackV;
          store.getState().metrics.setRakebackPending(deposited);
        })
        .catch(() => {
          // Failed to post — still surface the notification; server will reconcile
          store.getState().metrics.setRakebackPending(rakebackV);
        });
    });

    return () => { unsub(); };
  }, [jwt, apiBase]);
}
