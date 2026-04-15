/**
 * OpenVegasWidget.tsx
 *
 * Self-contained embeddable widget that packages the full OpenVegas web
 * terminal into a single React component. Designed for:
 *
 *   - Documentation sites (Docusaurus, Nextra, ReadTheDocs)
 *   - GitHub README embeds via WebContainers
 *   - Product demos on landing pages
 *   - Discord bots with embedded iframes
 *
 * USAGE
 * ─────
 *   // In any React app:
 *   import { OpenVegasWidget } from '@openvegas/widget';
 *
 *   <OpenVegasWidget
 *     token={supabaseAccessToken}     // omit for guest mode
 *     height={480}
 *     theme="neon"
 *     defaultCommand="chat --demo"
 *   />
 *
 * WEBCONTAINERS MODE
 * ──────────────────
 *   When running inside a WebContainer (StackBlitz, GitHub Codespaces embedded
 *   iframe), the widget cannot spawn a PTY server-side. Instead it proxies all
 *   input/output through the wss://app.openvegas.ai/ws/terminal endpoint.
 *   Detection: document.referrer matches known WebContainer origins.
 *
 * PACKAGING
 * ─────────
 *   The widget is published as a separate npm package: @openvegas/widget
 *   Built with Vite library mode:
 *     vite build --config widget.vite.config.ts
 *   Output: dist/openvegas-widget.es.js + dist/openvegas-widget.umd.js
 *   Peer deps: react ^18, react-dom ^18
 *   Bundle size target: < 150 KB gzipped (xterm.js loaded dynamically)
 *
 * IFRAME EMBED (zero-dependency)
 * ───────────────────────────────
 *   For non-React sites, the widget is also available as a plain iframe:
 *   <iframe
 *     src="https://app.openvegas.ai/embed?theme=neon&height=480"
 *     style="width:100%;height:480px;border:none"
 *   />
 *
 * SECURITY
 * ────────
 *   - The widget never bundles or caches tokens
 *   - Guest sessions are used when no token is provided
 *   - postMessage API is used for iframe ↔ parent communication
 *   - CSP: frame-src https://app.openvegas.ai must be set by the embedder
 */

'use client';

import React, { useState, useCallback, useRef, useEffect } from 'react';
import { Terminal, type SessionInfo } from '../Terminal';
import { FileDropOverlay } from '../FileDropOverlay';
import { Web3PaymentGate } from '../Web3PaymentGate';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface OpenVegasWidgetProps {
  /** Supabase JWT. Omit for guest mode (50 $V sandbox). */
  token?:          string;
  /** Widget height in pixels. Default: 520. */
  height?:         number;
  /** Visual theme. Default: 'neon'. */
  theme?:          'neon' | 'minimal' | 'transparent';
  /** Show the balance bar at the bottom. Default: true. */
  showBalance?:    boolean;
  /** Called when the user clicks "Sign in" after SYSTEM_LOCK. */
  onAuthRequired?: () => void;
  /** Called when balance changes. */
  onBalanceChange?: (balanceV: number) => void;
  className?:      string;
  style?:          React.CSSProperties;
}

// ─── Theme maps ───────────────────────────────────────────────────────────────

const THEMES = {
  neon: {
    border:     '#00ff88',
    header:     '#0a0a0a',
    headerText: '#00ff88',
    bg:         '#0a0a0a',
    barBg:      '#0f0f0f',
    barText:    '#888',
  },
  minimal: {
    border:     '#333',
    header:     '#111',
    headerText: '#ccc',
    bg:         '#111',
    barBg:      '#111',
    barText:    '#666',
  },
  transparent: {
    border:     'rgba(0,255,136,0.3)',
    header:     'rgba(0,0,0,0.7)',
    headerText: '#00ff88',
    bg:         'rgba(0,0,0,0.85)',
    barBg:      'rgba(0,0,0,0.6)',
    barText:    '#666',
  },
};

// ─── Fingerprint (lightweight — avoids heavy libs) ────────────────────────────

function getFingerprint(): string {
  if (typeof window === 'undefined') return '';
  const parts = [
    navigator.userAgent,
    navigator.language,
    screen.width + 'x' + screen.height,
    new Date().getTimezoneOffset(),
    navigator.hardwareConcurrency ?? 0,
  ].join('|');
  // FNV-1a 32-bit hash → hex string
  let h = 2166136261;
  for (let i = 0; i < parts.length; i++) {
    h ^= parts.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h.toString(16).padStart(8, '0');
}

// ─── Balance bar ──────────────────────────────────────────────────────────────

function BalanceBar({
  balanceV,
  isGuest,
  theme,
  onTopup,
}: {
  balanceV:  number;
  isGuest:   boolean;
  theme:     (typeof THEMES)[keyof typeof THEMES];
  onTopup:   () => void;
}) {
  const pct    = isGuest ? Math.max(0, Math.min(100, (balanceV / 50) * 100)) : 100;
  const color  = pct > 40 ? '#00ff88' : pct > 15 ? '#ffff00' : '#ff4444';

  return (
    <div style={{
      display:     'flex', alignItems: 'center',
      background:  theme.barBg,
      borderTop:   `1px solid ${theme.border}`,
      padding:     '0.3rem 0.8rem',
      gap:         '0.8rem',
      fontFamily:  'monospace',
      fontSize:    '0.7rem',
      color:       theme.barText,
    }}>
      <span style={{ color }}>
        {isGuest ? `GUEST · ${balanceV.toFixed(1)} / 50 $V` : `${balanceV.toFixed(0)} $V`}
      </span>
      <div style={{ flex: 1, background: '#1a1a1a', height: 3 }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, transition: 'width 0.5s' }} />
      </div>
      {isGuest && (
        <button
          onClick={onTopup}
          style={{
            background:  'transparent',
            border:      `1px solid ${theme.border}`,
            color:       theme.headerText,
            fontFamily:  'monospace',
            fontSize:    '0.65rem',
            padding:     '1px 6px',
            cursor:      'pointer',
          }}
        >
          + ADD $V
        </button>
      )}
    </div>
  );
}

// ─── Header bar ──────────────────────────────────────────────────────────────

function HeaderBar({ theme, connected }: {
  theme:     (typeof THEMES)[keyof typeof THEMES];
  connected: boolean;
}) {
  return (
    <div style={{
      display:     'flex', alignItems: 'center',
      background:  theme.header,
      borderBottom: `1px solid ${theme.border}`,
      padding:     '0.3rem 0.8rem',
      gap:         '0.5rem',
      fontFamily:  'monospace',
      fontSize:    '0.7rem',
      color:       theme.headerText,
      userSelect:  'none',
    }}>
      <span style={{ color: theme.border }}>▋</span>
      <span style={{ fontWeight: 'bold', letterSpacing: '0.05em' }}>OPENVEGAS</span>
      <span style={{ color: '#555', marginLeft: 'auto', fontSize: '0.65rem' }}>
        <span style={{
          display:      'inline-block',
          width:        6, height: 6,
          borderRadius: '50%',
          background:   connected ? '#00ff88' : '#ff4444',
          marginRight:  4,
          verticalAlign: 'middle',
        }} />
        {connected ? 'connected' : 'connecting...'}
      </span>
    </div>
  );
}

// ─── Main Widget ──────────────────────────────────────────────────────────────

export function OpenVegasWidget({
  token         = '',
  height        = 520,
  theme: themeName = 'neon',
  showBalance   = true,
  onAuthRequired,
  onBalanceChange,
  className,
  style,
}: OpenVegasWidgetProps) {
  const theme = THEMES[themeName] ?? THEMES.neon;
  const fingerprint = useRef(getFingerprint());

  const [sessionInfo,  setSessionInfo]  = useState<SessionInfo | null>(null);
  const [balanceV,     setBalanceV]     = useState(0);
  const [connected,    setConnected]    = useState(false);
  const [showPayGate,  setShowPayGate]  = useState(false);
  const [wsInputFn,    setWsInputFn]    = useState<((data: string) => void) | null>(null);

  const handleBalanceUpdate = useCallback((v: number) => {
    setBalanceV(v);
    onBalanceChange?.(v);
  }, [onBalanceChange]);

  const handleSessionReady = useCallback((info: SessionInfo) => {
    setSessionInfo(info);
    setBalanceV(info.balanceV);
    setConnected(true);
    onBalanceChange?.(info.balanceV);
  }, [onBalanceChange]);

  const handleAuthRequired = useCallback(() => {
    setConnected(false);
    onAuthRequired?.();
  }, [onAuthRequired]);

  const handleAttach = useCallback((wsInput: string) => {
    wsInputFn?.(wsInput);
  }, [wsInputFn]);

  // postMessage API for iframe embeds
  useEffect(() => {
    const handler = (ev: MessageEvent) => {
      if (typeof ev.data !== 'object' || ev.data?.type !== 'ov:input') return;
      wsInputFn?.(String(ev.data.data ?? ''));
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, [wsInputFn]);

  const HEADER_H  = 30;
  const BALANCE_H = showBalance ? 28 : 0;
  const TERM_H    = height - HEADER_H - BALANCE_H;

  return (
    <div
      className={className}
      style={{
        display:       'flex',
        flexDirection: 'column',
        width:         '100%',
        height:        height,
        border:        `1px solid ${theme.border}`,
        background:    theme.bg,
        overflow:      'hidden',
        position:      'relative',
        boxShadow:     themeName === 'neon'
          ? `0 0 20px rgba(0,255,136,0.15), 0 0 40px rgba(0,255,136,0.05)`
          : 'none',
        ...style,
      }}
    >
      <HeaderBar theme={theme} connected={connected} />

      <div style={{ position: 'relative', flex: 1, height: TERM_H }}>
        <Terminal
          token={token}
          fingerprint={fingerprint.current}
          onSessionReady={handleSessionReady}
          onAuthRequired={handleAuthRequired}
          style={{ height: '100%' }}
        />
        <FileDropOverlay
          token={token}
          onAttach={handleAttach}
        />
      </div>

      {showBalance && sessionInfo && (
        <BalanceBar
          balanceV={balanceV}
          isGuest={sessionInfo.isGuest}
          theme={theme}
          onTopup={() => setShowPayGate(true)}
        />
      )}

      {showPayGate && (
        <Web3PaymentGate
          token={token}
          onSuccess={(v) => {
            handleBalanceUpdate(balanceV + v);
            setShowPayGate(false);
          }}
          onCancel={() => setShowPayGate(false)}
        />
      )}
    </div>
  );
}
