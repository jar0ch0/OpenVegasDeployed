#!/usr/bin/env node
'use strict';

const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const pkg = require('../package.json');
const { downloadBinary } = require('../lib/download.js');

// ── Platform detection ──────────────────────────────────────────────────────

const PLATFORM_MAP = {
  darwin: 'darwin',
  linux: 'linux',
  win32: 'win',
};

const ARCH_MAP = {
  arm64: 'arm64',
  x64: 'x64',
};

function getTarget() {
  const platform = PLATFORM_MAP[process.platform];
  const arch = ARCH_MAP[process.arch];
  if (!platform || !arch) {
    console.error(
      `[openvegas] Unsupported platform: ${process.platform}/${process.arch}\n` +
      `Supported: linux/x64, darwin/arm64, darwin/x64, win32/x64\n\n` +
      `To install manually:\n` +
      `  https://github.com/jar0ch0/OpenVegasDeployed/releases`,
    );
    process.exit(1);
  }
  return `${platform}-${arch}`;
}

// ── Cache paths ─────────────────────────────────────────────────────────────

function getCacheDir(version) {
  return path.join(os.homedir(), '.openvegas', 'bin', version);
}

function getBinaryPath(version, target) {
  const ext = process.platform === 'win32' ? '.exe' : '';
  return path.join(getCacheDir(version), `openvegas-${target}${ext}`);
}

// ── Old-version cleanup ─────────────────────────────────────────────────────

function cleanOldVersions(currentVersion) {
  const binRoot = path.join(os.homedir(), '.openvegas', 'bin');
  if (!fs.existsSync(binRoot)) return;
  for (const entry of fs.readdirSync(binRoot)) {
    if (entry !== currentVersion) {
      const dir = path.join(binRoot, entry);
      try {
        fs.rmSync(dir, { recursive: true, force: true });
      } catch {
        // best-effort
      }
    }
  }
}

// ── Main ────────────────────────────────────────────────────────────────────

async function main() {
  const args = process.argv.slice(2);
  const isInstallHook = args.includes('--_install');
  const isUpgrade = args.includes('--upgrade');
  const version = pkg.version;
  const target = getTarget();
  const binaryPath = getBinaryPath(version, target);

  const needsDownload = isInstallHook || isUpgrade || !fs.existsSync(binaryPath);

  if (needsDownload) {
    const cacheDir = getCacheDir(version);
    fs.mkdirSync(cacheDir, { recursive: true });

    try {
      await downloadBinary(version, target, cacheDir);
      cleanOldVersions(version);
    } catch (err) {
      console.error(`\n[openvegas] Download failed: ${err.message}`);
      console.error(
        `\nManual install:\n` +
        `  https://github.com/jar0ch0/OpenVegasDeployed/releases/tag/v${version}`,
      );
      process.exit(1);
    }
  }

  // postinstall hook — don't exec the binary, just exit after download
  if (isInstallHook) {
    process.exit(0);
  }

  // Forward all args to the cached binary
  const forwardArgs = args.filter(a => a !== '--upgrade');
  try {
    execFileSync(binaryPath, forwardArgs, { stdio: 'inherit' });
    process.exit(0);
  } catch (err) {
    process.exit(typeof err.status === 'number' ? err.status : 1);
  }
}

main().catch(err => {
  console.error(`[openvegas] Unexpected error: ${err.message}`);
  process.exit(1);
});
