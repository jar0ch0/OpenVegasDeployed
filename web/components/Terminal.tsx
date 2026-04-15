/**
 * Terminal.tsx
 *
 * xterm.js terminal component with GPU-accelerated Canvas rendering.
 * Renders the OpenVegas agent loop's raw ANSI/Ink output at up to 60fps,
 * including Pachinko ball physics, chalk colors, and Unicode box-drawing.
 *
 * RENDERING
 * ─────────
 *   Uses @xterm/addon-canvas (Canvas2D API, no WebGL dependency).
 *   The Canvas addon eliminates DOM reflows on Ink frame-diffs — each
 *   40ms Ink flush produces one atomic canvas repaint instead of N DOM mutations.
 *   Observed: Pachinko at 25fps renders cleanly at 60fps browser repaint rate.
 *
 * PACKAGES REQUIRED (add to web/package.json)
 * ──────────────────────────────────────────
 *   @xterm/xterm ^5.x
 *   @xterm/addon-canvas ^0.7.x
 *   @xterm/addon-fit ^0.10.x
 *   @xterm/addon-web-links ^6.x
 *
 * SYSTEM_LOCK OVERLAY
 * ───────────────────
 *   When the WebSocket emits SYSTEM_LOCK (guest balance exhausted),
 *   a neon overlay renders over the terminal with auth CTA.
 *   The terminal is still visible underneath (blurred) to show what the
 *   user is missing. Input is disabled until the user authenticates.
 */

'use client';

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { useTerminalSocket, type SessionInfo, type SystemLock } from '../lib/useTerminalSocket';

// ─── Types ────────────────────────────────────────────────────────────────────

interface TerminalProps {
  /** Supabase JWT. Pass empty string for guest mode. */
  token:             string;
  /** Browser fingerprint for guest rate limiting. */
  fingerprint?:      string;
  /** Called when the user needs to authenticate (after SYSTEM_LOCK). */
  onAuthRequired?:   () => void;
  /** Called once with session metadata. */
  onSessionReady?:   (info: SessionInfo) => void;
  /** CSS class applied to the outer container. */
  className?:        string;
  style?:            React.CSSProperties;
}

// ─── SYSTEM_LOCK overlay ──────────────────────────────────────────────────────

interface LockOverlayProps {
  lock:          SystemLock;
  onLogin:       () => void;
  balanceV:      number;
}

function LockOverlay({ lock, onLogin, balanceV }: LockOverlayProps) {
  return (
    <div style={{
      position:       'absolute',
      inset:          0,
      background:     'rgba(0,0,0,0.85)',
      backdropFilter: 'blur(4px)',
      display:        'flex',
      flexDirection:  'column',
      alignItems:     'center',
      justifyContent: 'center',
      zIndex:         10,
      fontFamily:     '"Courier New", Courier, monospace',
      color:          '#00ff88',
      textAlign:      'center',
      padding:        '2rem',
    }}>
      <div style={{ fontSize: '1.8rem', fontWeight: 'bold', marginBottom: '0.5rem' }}>
        ▋ SESSION PAUSED
      </div>
      <div style={{ color: '#888', fontSize: '0.85rem', marginBottom: '2rem' }}>
        {lock.message || 'Guest session exhausted. Authenticate to continue.'}
      </div>
      <div style={{
        border:        '1px solid #00ff88',
        padding:       '0.5rem 1rem',
        marginBottom:  '1rem',
        fontSize:      '0.75rem',
        color:         '#555',
      }}>
        {balanceV.toFixed(1)} $V remaining → 0.0 $V
      </div>
      <button
        onClick={onLogin}
        style={{
          background:    'transparent',
          border:        '2px solid #00ff88',
          color:         '#00ff88',
          fontFamily:    'inherit',
          fontSize:      '1rem',
          padding:       '0.6rem 2rem',
          cursor:        'pointer',
          letterSpacing: '0.1em',
          transition:    'all 0.15s',
        }}
        onMouseEnter={(e) => {
          (e.target as HTMLElement).style.background = '#00ff88';
          (e.target as HTMLElement).style.color = '#000';
        }}
        onMouseLeave={(e) => {
          (e.target as HTMLElement).style.background = 'transparent';
          (e.target as HTMLElement).style.color = '#00ff88';
        }}
      >
        [ CREATE FREE ACCOUNT ]
      </button>
      <div style={{ color: '#444', fontSize: '0.7rem', marginTop: '1rem' }}>
        or sign in at app.openvegas.ai
      </div>
    </div>
  );
}

// ─── Guest balance indicator ──────────────────────────────────────────────────

function GuestBadge({ balanceV }: { balanceV: number }) {
  const pct = Math.max(0, Math.min(100, (balanceV / 50) * 100));
  const color = pct > 40 ? '#00ff88' : pct > 15 ? '#ffff00' : '#ff4444';
  return (
    <div style={{
      position:   'absolute',
      top:        '0.5rem',
      right:      '0.5rem',
      zIndex:     5,
      fontFamily: 'monospace',
      fontSize:   '0.7rem',
      color:      color,
      background: 'rgba(0,0,0,0.8)',
      padding:    '2px 8px',
      border:     `1px solid ${color}`,
    }}>
      GUEST · {balanceV.toFixed(1)} $V
    </div>
  );
}

// ─── Terminal component ───────────────────────────────────────────────────────

export function Terminal({
  token,
  fingerprint,
  onAuthRequired,
  onSessionReady,
  className,
  style,
}: TerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef      = useRef<import('@xterm/xterm').Terminal | null>(null);
  const fitRef       = useRef<import('@xterm/addon-fit').FitAddon | null>(null);

  const [sessionInfo,  setSessionInfo]  = useState<SessionInfo | null>(null);
  const [systemLock,   setSystemLock]   = useState<SystemLock  | null>(null);
  const [balanceV,     setBalanceV]     = useState(0);
  const [termReady,    setTermReady]    = useState(false);

  // ── Initialize xterm.js (dynamic import — SSR-safe) ───────────────────────
  useEffect(() => {
    if (!containerRef.current || termRef.current) return;

    let cancelled = false;

    (async () => {
      const { Terminal: XTerm }    = await import('@xterm/xterm');
      const { CanvasAddon }         = await import('@xterm/addon-canvas');
      const { FitAddon }            = await import('@xterm/addon-fit');
      const { WebLinksAddon }       = await import('@xterm/addon-web-links');

      if (cancelled || !containerRef.current) return;

      const xterm = new XTerm({
        fontFamily:        '"Cascadia Code", "Fira Code", "Courier New", monospace',
        fontSize:          14,
        lineHeight:        1.2,
        cursorBlink:       true,
        cursorStyle:       'block',
        theme: {
          background:      '#0a0a0a',
          foreground:      '#e0e0e0',
          cursor:          '#00ff88',
          selectionBackground: 'rgba(0,255,136,0.3)',
          black:           '#0a0a0a',
          brightGreen:     '#00ff88',
          green:           '#00cc66',
          cyan:            '#00ccff',
          brightCyan:      '#33ddff',
          yellow:          '#ffff44',
          red:             '#ff4444',
          magenta:         '#ff44ff',
          white:           '#e0e0e0',
          brightBlack:     '#555',
        },
        allowProposedApi:  true,
        scrollback:        5000,
        convertEol:        true,
      });

      const fitAddon   = new FitAddon();
      const canvasAddon = new CanvasAddon();

      xterm.loadAddon(fitAddon);
      xterm.loadAddon(canvasAddon);
      xterm.loadAddon(new WebLinksAddon());

      xterm.open(containerRef.current);
      fitAddon.fit();

      termRef.current = xterm;
      fitRef.current  = fitAddon;
      setTermReady(true);
    })();

    return () => {
      cancelled = true;
      termRef.current?.dispose();
      termRef.current = null;
      fitRef.current  = null;
      setTermReady(false);
    };
  }, []);

  // ── Resize observer → fit + sendResize ────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver(() => {
      fitRef.current?.fit();
      const dims = fitRef.current?.proposeDimensions();
      if (dims) sendResize(dims.cols, dims.rows);
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  });

  const handleSessionInfo = useCallback((info: SessionInfo) => {
    setSessionInfo(info);
    setBalanceV(info.balanceV);
    onSessionReady?.(info);
  }, [onSessionReady]);

  const handleSystemLock = useCallback((lock: SystemLock) => {
    setSystemLock(lock);
    onAuthRequired?.();
  }, [onAuthRequired]);

  // ── WebSocket ──────────────────────────────────────────────────────────────
  const dims = fitRef.current?.proposeDimensions();
  const { connected, sendInput, sendResize } = useTerminalSocket({
    terminal:       termReady ? termRef.current : null,
    token,
    fingerprint,
    cols:           dims?.cols ?? 80,
    rows:           dims?.rows ?? 24,
    onSessionInfo:  handleSessionInfo,
    onSystemLock:   handleSystemLock,
    onBalanceUpdate: setBalanceV,
  });

  // ── Forward xterm keystrokes → WebSocket ──────────────────────────────────
  useEffect(() => {
    if (!termReady || !termRef.current) return;
    const xterm = termRef.current;
    const { dispose } = xterm.onData((data) => sendInput(data));
    return () => dispose();
  }, [termReady, sendInput]);

  // ── Connected indicator ────────────────────────────────────────────────────
  useEffect(() => {
    if (!termReady || !termRef.current) return;
    if (!connected) {
      termRef.current.writeln('\r\x1b[33mConnecting...\x1b[0m');
    }
  }, [connected, termReady]);

  return (
    <div
      ref={containerRef}
      className={className}
      style={{
        position:   'relative',
        width:      '100%',
        height:     '100%',
        background: '#0a0a0a',
        ...style,
      }}
    >
      {/* Guest balance badge */}
      {sessionInfo?.isGuest && !systemLock && (
        <GuestBadge balanceV={balanceV} />
      )}

      {/* SYSTEM_LOCK overlay */}
      {systemLock && (
        <LockOverlay
          lock={systemLock}
          balanceV={balanceV}
          onLogin={() => onAuthRequired?.()}
        />
      )}
    </div>
  );
}
