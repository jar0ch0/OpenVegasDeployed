/**
 * ProvablyFairReceipt.tsx
 *
 * Renders the full cryptographic verification trail for a completed game round.
 * Invoked via the `/verify` slash command in ChatScreen.
 *
 * VERIFICATION PROTOCOL (commit-reveal)
 * ─────────────────────────────────────
 *   Before the round:
 *     Server generates server_seed, publishes SHA256(server_seed) as commitment
 *   After the round:
 *     Server reveals server_seed
 *
 *   Client verifies:
 *     1. SHA256(server_seed) === commitment hash               [seed integrity]
 *     2. outcome = HMAC-SHA256(server_seed, client_seed:nonce) % numOutcomes
 *        === recorded outcome                                  [result integrity]
 *
 *   Both checks are computed locally in this component using node:crypto.
 *   The server cannot retroactively change either seed without breaking step 1.
 *
 * VISUAL (80-col)
 * ───────────────
 *
 *   ╔═══════════════════════════════════════════════════════╗
 *   ║  PROVABLY FAIR VERIFICATION                          ║
 *   ╠═══════════════════════════════════════════════════════╣
 *   ║  ROUND      0x3F2A...8B                              ║
 *   ║  DATE       2026-04-15  23:42:18 UTC                 ║
 *   ╠═══════════════════════════════════════════════════════╣
 *   ║  STEP 1 — COMMITMENT                                 ║
 *   ║  Published  sha256:9f3a8c2e...1b4d                   ║
 *   ╠═══════════════════════════════════════════════════════╣
 *   ║  STEP 2 — CLIENT SEED                                ║
 *   ║  Seed       a1b2c3d4                                 ║
 *   ║  Nonce      42                                       ║
 *   ╠═══════════════════════════════════════════════════════╣
 *   ║  STEP 3 — SERVER REVEAL                              ║
 *   ║  Seed       c0ffee42...                              ║
 *   ║  SHA256     9f3a8c2e...1b4d   [OK]                   ║
 *   ╠═══════════════════════════════════════════════════════╣
 *   ║  STEP 4 — OUTCOME                                    ║
 *   ║  HMAC       HMAC-SHA256(server, "a1b2c3d4:42")       ║
 *   ║             = fe3a9b1c...                            ║
 *   ║  Result     0xfe3a9b1c % 7 = 3   → 10x   [MATCH]    ║
 *   ╚═══════════════════════════════════════════════════════╝
 *
 * ZUSTAND READS
 *   (none — fully prop-driven; caller fetches from /v1/game/verify/:id)
 */

import React from 'react';
import { Box, Text, useInput, useStdout } from 'ink';
import chalk from 'chalk';
import { createHash, createHmac } from 'node:crypto';
import type { GameResult } from '../../store/casinoSlice';

// ─── Verification types ───────────────────────────────────────────────────────

export interface VerifyData {
  serverSeedHash: string;   // SHA256(serverSeed) — commitment published before round
  serverSeed: string;       // revealed after round ends
  clientSeed: string;
  nonce: number;
  numOutcomes: number;      // 7 for pachinko buckets
  recordedOutcomeIdx: number; // bucket index that was recorded server-side
}

export interface ProvablyFairReceiptProps {
  result: GameResult;
  verifyData: VerifyData;
  onDismiss: () => void;
}

// ─── Crypto helpers ───────────────────────────────────────────────────────────

function sha256hex(input: string): string {
  return createHash('sha256').update(input, 'utf8').digest('hex');
}

function hmacSha256hex(key: string, data: string): string {
  return createHmac('sha256', key).update(data, 'utf8').digest('hex');
}

// ─── Verification computation ─────────────────────────────────────────────────

interface VerificationResult {
  commitmentMatch: boolean;
  computedHash: string;
  hmacHex: string;
  firstU32Hex: string;
  computedOutcomeIdx: number;
  outcomeMatch: boolean;
}

function runVerification(v: VerifyData): VerificationResult {
  const computedHash     = sha256hex(v.serverSeed);
  const commitmentMatch  = computedHash === v.serverSeedHash;

  const message  = `${v.clientSeed}:${v.nonce}`;
  const hmacHex  = hmacSha256hex(v.serverSeed, message);
  const firstU32 = parseInt(hmacHex.slice(0, 8), 16);
  const computedOutcomeIdx = firstU32 % v.numOutcomes;
  const outcomeMatch = computedOutcomeIdx === v.recordedOutcomeIdx;

  return {
    commitmentMatch,
    computedHash,
    hmacHex,
    firstU32Hex: '0x' + firstU32.toString(16).padStart(8, '0'),
    computedOutcomeIdx,
    outcomeMatch,
  };
}

// ─── Component ───────────────────────────────────────────────────────────────

const RECEIPT_W = 58;

export function ProvablyFairReceipt({
  result,
  verifyData,
  onDismiss,
}: ProvablyFairReceiptProps) {
  const { stdout } = useStdout();
  const termW      = stdout?.columns ?? 80;

  useInput(() => { onDismiss(); });

  const v   = runVerification(verifyData);
  const W   = RECEIPT_W;
  const hr  = '\u2550'.repeat(W - 2);
  const top = '\u2554' + hr + '\u2557';
  const mid = '\u2560' + hr + '\u2563';
  const bot = '\u255A' + hr + '\u255D';

  function row(label: string, value: string, badge?: string): string {
    const l = label.padEnd(12);
    const b = badge ? '  ' + badge : '';
    const content = chalk.dim.white(l) + chalk.white(value) + b;
    const visible = content.replace(/\x1B\[[0-9;]*m/g, '').length;
    return '\u2551  ' + content + ' '.repeat(Math.max(0, W - 4 - visible)) + '\u2551';
  }

  function sectionHeader(title: string): string {
    const t = chalk.bold.cyan(title);
    const visible = t.replace(/\x1B\[[0-9;]*m/g, '').length;
    return '\u2551  ' + t + ' '.repeat(Math.max(0, W - 4 - visible)) + '\u2551';
  }

  const ok  = chalk.bold.green('[OK]');
  const bad = chalk.bold.red('[FAIL]');
  const match = chalk.bold.green('[MATCH]');
  const mismatch = chalk.bold.red('[MISMATCH]');

  const date = new Date(result.timestamp)
    .toISOString().replace('T', '  ').slice(0, 22) + ' UTC';

  const shortHash = (h: string) => h.slice(0, 12) + '...' + h.slice(-4);
  const shortSeed = (s: string) => s.slice(0, 16) + (s.length > 16 ? '...' : '');

  const message = `${verifyData.clientSeed}:${verifyData.nonce}`;

  const titleText = chalk.bold.white('PROVABLY FAIR VERIFICATION');
  const titleVisible = titleText.replace(/\x1B\[[0-9;]*m/g, '').length;
  const titleRow = '\u2551  ' + titleText +
    ' '.repeat(Math.max(0, W - 4 - titleVisible)) + '\u2551';

  const lines = [
    top,
    titleRow,
    mid,
    // Round info
    row('Round', result.sessionId.slice(0, 20) + '...'),
    row('Date', date),
    mid,
    // Step 1 — Commitment
    sectionHeader('STEP 1 — COMMITMENT'),
    row('Published', 'sha256:' + shortHash(verifyData.serverSeedHash)),
    mid,
    // Step 2 — Client seed
    sectionHeader('STEP 2 — CLIENT SEED'),
    row('Seed', verifyData.clientSeed),
    row('Nonce', String(verifyData.nonce)),
    mid,
    // Step 3 — Reveal
    sectionHeader('STEP 3 — SERVER REVEAL'),
    row('Seed', shortSeed(verifyData.serverSeed)),
    row('SHA256', shortHash(v.computedHash), v.commitmentMatch ? ok : bad),
    mid,
    // Step 4 — Outcome
    sectionHeader('STEP 4 — OUTCOME'),
    row('HMAC', 'HMAC-SHA256(server, "' + message.slice(0, 14) + '")'),
    row('', shortHash(v.hmacHex)),
    row('Result',
      `${v.firstU32Hex} % ${verifyData.numOutcomes} = ${v.computedOutcomeIdx}  → ${result.multiplier}x`,
      v.outcomeMatch ? match : mismatch
    ),
    bot,
  ];

  const overallBadge = v.commitmentMatch && v.outcomeMatch
    ? chalk.bold.green('VERIFIED')
    : chalk.bold.red('TAMPERED');

  return (
    <Box flexDirection="column" width={Math.max(termW, W + 4)}>
      {lines.map((line, i) => <Text key={i}>{line}</Text>)}
      <Text>{'  ' + overallBadge + chalk.dim.white('  press any key to dismiss')}</Text>
    </Box>
  );
}
