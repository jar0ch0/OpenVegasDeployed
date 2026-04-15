/**
 * useTickerScroll.ts
 *
 * Scrolls a concatenated string of events from right to left, one character
 * per frame. New events appended to the right enter from off-screen.
 *
 * VISIBLE WINDOW
 * ─────────────
 *   fullText = events.join('  |  ')
 *   The ticker shows a `width`-character sliding window over:
 *     padding(width spaces) + fullText + padding(width spaces)
 *   scrollPos increases by SCROLL_SPEED chars/frame.
 *   When scrollPos >= len(fullText) + width, it wraps back to 0 (loop).
 *
 * SCROLL_SPEED: 1 char/frame at 25fps = 25 chars/second — comfortable
 * reading speed for short event strings.
 *
 * IPC POLLING
 * ───────────
 * The hook accepts `events` as a prop. Callers wire this to:
 *   1. casinoSlice.tickerEvents (Zustand) for server-side events
 *   2. A local poller that reads ~/.openvegas/ipc/sessions/<id>/events/*.json
 *      and calls casinoSlice.pushTickerEvent()
 * The hook itself is pure display — no I/O.
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import { useAnimationFrame } from './useAnimationFrame';
import type { TickerEvent } from '../store/casinoSlice';

const SCROLL_SPEED = 1;   // characters per frame
const SEPARATOR = '  |  ';

export interface UseTickerScrollReturn {
  visibleText: string;   // exactly `width` characters, padded with spaces
}

export function useTickerScroll(
  events: TickerEvent[],
  width: number,
  running: boolean = true
): UseTickerScrollReturn {
  const [scrollPos, setScrollPos] = useState(0);

  // Build the full ticker string from events. Recomputed when events change.
  const fullTextRef = useRef<string>('');
  const totalLenRef = useRef<number>(0);

  useEffect(() => {
    if (events.length === 0) {
      fullTextRef.current = '';
      totalLenRef.current = width; // loop length when empty
      return;
    }
    const text = events.map((e) => e.text).join(SEPARATOR);
    fullTextRef.current = text;
    totalLenRef.current = text.length + width;   // full loop length
    // When new events are added, don't reset scrollPos — events slide in from right
  }, [events, width]);

  useAnimationFrame(
    useCallback(() => {
      setScrollPos((pos) => {
        const nextPos = pos + SCROLL_SPEED;
        return nextPos >= totalLenRef.current ? 0 : nextPos;
      });
    }, []),
    running && events.length > 0
  );

  // Construct visible window
  const visibleText = (() => {
    if (events.length === 0) {
      return ' '.repeat(width);
    }
    const padded = ' '.repeat(width) + fullTextRef.current;
    // Slice a width-length window starting at scrollPos
    const start = Math.min(scrollPos, padded.length);
    const window = padded.slice(start, start + width);
    // Right-pad to exactly width chars if near the end of the string
    return window.padEnd(width, ' ');
  })();

  return { visibleText };
}
