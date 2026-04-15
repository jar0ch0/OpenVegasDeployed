#!/usr/bin/env bun
/**
 * bin/openvegas.ts
 *
 * Commander.js CLI entry point. Parses arguments, then calls Ink's render()
 * with exitOnCtrlC: false so the useExitTrap hook owns Ctrl+C behavior.
 *
 * COMMANDS
 * ────────
 *   openvegas [chat] [prompt...]   Start / resume an agentic session
 *   openvegas login                Authenticate via browser OAuth
 *   openvegas logout               Clear saved credentials
 *
 * GLOBAL FLAGS
 * ────────────
 *   --api-base <url>     Override API base (default: OPENVEGAS_API_BASE env or prod)
 *   --approval <mode>    ask | allow | exclude (default: ask)
 */

import { Command } from 'commander';
import { render }  from 'ink';
import React       from 'react';
import { App }     from '../src/app/App.js';

const DEFAULT_API_BASE =
  process.env.OPENVEGAS_API_BASE ?? 'https://app.openvegas.ai';

const program = new Command();

program
  .name('openvegas')
  .description('OpenVegas — cyberpunk agentic CLI')
  .version('0.4.0')
  .option('--api-base <url>',    'API base URL',                DEFAULT_API_BASE)
  .option('--approval <mode>',   'Approval mode: ask|allow|exclude', 'ask');

// ─── chat ────────────────────────────────────────────────────────────────────

program
  .command('chat [prompt...]', { isDefault: true })
  .description('Start an agentic chat session (default command)')
  .option('--session-id <id>',  'Resume an existing session by ID')
  .option('--no-casino',        'Disable the casino UI overlay')
  .action((promptParts: string[], opts: { sessionId?: string; casino: boolean }) => {
    const globalOpts = program.opts<{ apiBase: string; approval: string }>();
    const initialPrompt = promptParts.join(' ') || undefined;

    const approval = globalOpts.approval as 'ask' | 'allow' | 'exclude';
    if (!['ask', 'allow', 'exclude'].includes(approval)) {
      console.error(`Unknown approval mode "${approval}". Valid: ask, allow, exclude`);
      process.exit(1);
    }

    const { unmount } = render(
      React.createElement(App, {
        apiBase:       globalOpts.apiBase,
        approvalMode:  approval,
        initialPrompt,
        sessionId:     opts.sessionId,
        showCasino:    opts.casino !== false,
      }),
      { exitOnCtrlC: false },
    );

    process.on('unhandledRejection', (reason) => {
      process.stderr.write(`[openvegas] unhandled rejection: ${String(reason)}\n`);
      unmount();
      process.exit(1);
    });
  });

// ─── login ───────────────────────────────────────────────────────────────────

program
  .command('login')
  .description('Authenticate via browser OAuth flow')
  .action(async () => {
    const { runLoginFlow } = await import('../src/auth/loginFlow.js');
    try {
      const result = await runLoginFlow(DEFAULT_API_BASE);
      process.stdout.write(
        `\x1b[1;32m✓\x1b[0m Logged in${result.isNew ? ' (new account)' : ''} — user ${result.userId}\n`,
      );
    } catch (err) {
      process.stderr.write(`\x1b[1;31m✗\x1b[0m Login failed: ${String(err)}\n`);
      process.exit(1);
    }
  });

// ─── logout ──────────────────────────────────────────────────────────────────

program
  .command('logout')
  .description('Clear saved credentials from ~/.openvegas/config.json')
  .action(async () => {
    const { promises: fsp } = await import('node:fs');
    const { join }          = await import('node:path');
    const { homedir }       = await import('node:os');
    const cfgPath = join(homedir(), '.openvegas', 'config.json');
    try {
      await fsp.writeFile(cfgPath, JSON.stringify({}), { mode: 0o600 });
      process.stdout.write('\x1b[1;32m✓\x1b[0m Logged out\n');
    } catch {
      // Config file may not exist; that's fine
      process.stdout.write('\x1b[1;32m✓\x1b[0m Already logged out\n');
    }
  });

program.parse(process.argv);
