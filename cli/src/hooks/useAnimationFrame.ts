/**
 * useAnimationFrame.ts
 *
 * Foundation hook for all casino animations. Drives a callback at a fixed
 * 40ms interval (25fps). Using a fixed interval rather than requestAnimationFrame
 * because we are in a terminal environment where display refresh is not
 * tied to a browser compositor.
 *
 * The callback receives the actual elapsed milliseconds since the last
 * tick — use this for frame-rate-independent physics (distance = velocity * delta).
 *
 * ANTI-FLICKER CONTRACT: callers must batch their own state updates into a
 * single setState call per tick. Multiple setState calls per 40ms window cause
 * Ink to queue extra reconciler passes within the same frame, causing flicker.
 */

import { useEffect, useRef } from 'react';

export const FRAME_MS = 40; // 25fps — matches the SSE flush interval in stream.ts

/**
 * @param callback - Called every FRAME_MS ms with actual elapsed ms.
 *                   Keep this function reference stable (useCallback) to avoid
 *                   re-registering the interval on every render.
 * @param running  - When false the interval is cleared. When it transitions to
 *                   true, the interval re-registers from the current time.
 */
export function useAnimationFrame(
  callback: (deltaMs: number) => void,
  running: boolean
): void {
  // Store latest callback in a ref so we never restart the interval just
  // because the callback closure was re-created (common in inline functions).
  const cbRef = useRef<(delta: number) => void>(callback);
  const lastTickRef = useRef<number>(Date.now());

  // Sync ref on every render — no dependency array is intentional here.
  useEffect(() => {
    cbRef.current = callback;
  });

  useEffect(() => {
    if (!running) return;

    // Reset clock when animation starts so the first delta is not stale.
    lastTickRef.current = Date.now();

    const id = setInterval(() => {
      const now = Date.now();
      const delta = now - lastTickRef.current;
      lastTickRef.current = now;
      cbRef.current(delta);
    }, FRAME_MS);

    return () => clearInterval(id);
  }, [running]);
}

/**
 * Convenience: returns an incrementing frame counter that ticks at FRAME_MS.
 * Useful when you need a monotone clock rather than a callback.
 */
export function useFrameCounter(running: boolean): number {
  const { useState, useCallback } = require('react') as typeof import('react');
  const [frame, setFrame] = useState(0);
  const tick = useCallback(() => setFrame((f) => f + 1), []);
  useAnimationFrame(tick, running);
  return frame;
}
