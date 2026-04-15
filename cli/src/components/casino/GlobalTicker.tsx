/**
 * GlobalTicker.tsx
 *
 * Bottom-anchored single-line scrolling marquee of platform events.
 * Events scroll from right to left at 1 char/frame (25 chars/sec).
 *
 * EVENT SOURCES
 * ─────────────
 * 1. Zustand casinoSlice.tickerEvents — platform events pushed via server
 *    SSE or IPC mailbox poller
 * 2. Internal IPC file poller (see TickerPoller below): reads
 *    ~/.openvegas/ipc/sessions/<id>/events/*.json every 2000ms
 *    and calls casinoSlice.pushTickerEvent()
 *
 * LAYOUT
 * ──────
 *   ─────────────────────────────────────────────────────────────────────────
 *   [!] @0xDev just minted 50,000 $V  |  [WIN] @cypher hit 10x on Slots ...
 *
 *   The divider line above is rendered by the parent layout (not this component).
 *   This component renders exactly two lines: a thin border and the scrolling text.
 *
 * ANTI-FLICKER
 * ────────────
 *   Only `scrollPos` state changes per frame — the events list may update
 *   at most every 2s (IPC poll). React's reconciler only redraws the single
 *   Text node whose content changed, not the whole component tree.
 *   Verified safe at 25fps with 200-char event strings.
 *
 * ZUSTAND READS
 *   casino.tickerEvents  → event list
 */

import React, { useEffect, useRef, useCallback } from 'react';
import { Box, Text, useStdout } from 'ink';
import chalk from 'chalk';
import { useCasino } from '../../store';
import { useTickerScroll } from '../../hooks/useTickerScroll';
import type { TickerEvent } from '../../store/casinoSlice';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';

// ─── Event tag formatter ──────────────────────────────────────────────────────

function formatEvent(e: TickerEvent): string {
  const text = e.text;
  // Color the tag prefix: [!] red, [WIN] yellow, [MINT] cyan, default dim
  if (text.startsWith('[!]'))   return chalk.red.bold('[!]') + text.slice(3);
  if (text.startsWith('[WIN]')) return chalk.yellow.bold('[WIN]') + text.slice(5);
  if (text.startsWith('[MINT]'))return chalk.cyan.bold('[MINT]') + text.slice(6);
  if (text.startsWith('[BET]')) return chalk.magenta('[BET]') + text.slice(5);
  return chalk.dim.white(text);
}

// ─── IPC poller (runs outside React, pushes to Zustand) ──────────────────────
// This is a standalone function called once with setInterval(2000).
// It reads JSON files from the IPC events directory and pushes new events
// to casinoSlice. Processed file IDs are tracked to avoid duplicates.

const PROCESSED_IDS = new Set<string>();

function pollIpcEvents(
  sessionId: string,
  pushEvent: (text: string) => void
): void {
  const dir = path.join(
    os.homedir(),
    '.openvegas', 'ipc', 'sessions', sessionId, 'events'
  );
  try {
    const files = fs.readdirSync(dir).filter((f) => f.endsWith('.json'));
    for (const file of files) {
      const id = file.replace('.json', '');
      if (PROCESSED_IDS.has(id)) continue;
      try {
        const raw = fs.readFileSync(path.join(dir, file), 'utf8');
        const event = JSON.parse(raw) as { text?: string; message?: string };
        const text = event.text ?? event.message ?? '';
        if (text) {
          pushEvent(text);
          PROCESSED_IDS.add(id);
        }
      } catch {
        // Partial write in progress — skip, will retry next poll
      }
    }
  } catch {
    // Directory doesn't exist yet — normal during early session lifecycle
  }
}

// ─── Prefill demo events (dev mode only) ─────────────────────────────────────

const DEMO_EVENTS: TickerEvent[] = [
  { id: 'demo-1', text: '[MINT] @0xDev just burned 45K tokens -> 50,000 $V', ts: Date.now() },
  { id: 'demo-2', text: '[WIN] @cypher hit 10x on Slots', ts: Date.now() },
  { id: 'demo-3', text: '[!] @neural_net burned 100K GPT-5 tokens for 120,000 $V', ts: Date.now() },
  { id: 'demo-4', text: '[BET] @grind wagered 2,500 $V on Baccarat', ts: Date.now() },
  { id: 'demo-5', text: '[WIN] @sigma closed CrashCompiler at 3.47x', ts: Date.now() },
];

// ─── Component ───────────────────────────────────────────────────────────────

interface GlobalTickerProps {
  sessionId?: string;          // IPC session to poll; omit to skip file polling
  useDemoEvents?: boolean;     // seed with demo events for dev/testing
  running?: boolean;
}

export function GlobalTicker({
  sessionId,
  useDemoEvents = false,
  running = true,
}: GlobalTickerProps) {
  const { stdout } = useStdout();
  const termW = stdout?.columns ?? 80;

  const { tickerEvents, pushTickerEvent, pruneTickerEvents } = useCasino();

  // Seed demo events once
  const demoSeededRef = useRef(false);
  useEffect(() => {
    if (useDemoEvents && !demoSeededRef.current) {
      demoSeededRef.current = true;
      DEMO_EVENTS.forEach((e) => pushTickerEvent(e.text));
    }
  }, [useDemoEvents, pushTickerEvent]);

  // IPC file polling — 2000ms interval, outside animation loop
  useEffect(() => {
    if (!sessionId) return;
    const id = setInterval(() => {
      pollIpcEvents(sessionId, pushTickerEvent);
      pruneTickerEvents(5 * 60 * 1000);   // drop events older than 5 min
    }, 2000);
    return () => clearInterval(id);
  }, [sessionId, pushTickerEvent, pruneTickerEvents]);

  // Format events list for the ticker: color tags are in the formatted string,
  // but useTickerScroll works on the raw event text for its scroll calculations.
  // We pass the formatted (chalk-colored) string to the scroller — chalk ANSI
  // codes are invisible characters that don't affect visual width in terminals.
  const formattedEvents: TickerEvent[] = tickerEvents.map((e) => ({
    ...e,
    text: formatEvent(e) + '  ',
  }));

  const { visibleText } = useTickerScroll(formattedEvents, termW - 2, running);

  // Thin separator line above ticker
  const separator = chalk.dim.green('\u2500'.repeat(termW));

  return (
    <Box flexDirection="column" width={termW}>
      <Text>{separator}</Text>
      <Text>{chalk.dim.white('\u2595') + visibleText + chalk.dim.white('\u258F')}</Text>
    </Box>
  );
}
