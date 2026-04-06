'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const https = require('node:https');
const path = require('node:path');

const GITHUB_BASE = 'https://github.com/jar0ch0/OpenVegasDeployed/releases/download';

// ── HTTP download with redirect following ───────────────────────────────────

function downloadFile(url, destPath) {
  return new Promise((resolve, reject) => {
    const attempt = (currentUrl, redirectsLeft) => {
      https.get(currentUrl, res => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          if (redirectsLeft <= 0) {
            return reject(new Error('Too many redirects'));
          }
          res.resume();
          return attempt(res.headers.location, redirectsLeft - 1);
        }
        if (res.statusCode !== 200) {
          res.resume();
          return reject(new Error(`HTTP ${res.statusCode} fetching ${currentUrl}`));
        }

        const total = parseInt(res.headers['content-length'] || '0', 10);
        let received = 0;
        let lastPct = -1;

        const dest = fs.createWriteStream(destPath);
        res.on('data', chunk => {
          received += chunk.length;
          if (total > 0) {
            const pct = Math.floor((received / total) * 100);
            if (pct !== lastPct && pct % 10 === 0) {
              process.stderr.write(`\r  ${pct}%`);
              lastPct = pct;
            }
          }
        });
        res.pipe(dest);
        dest.on('finish', () => {
          if (total > 0) process.stderr.write('\r  100%\n');
          resolve();
        });
        dest.on('error', reject);
        res.on('error', reject);
      }).on('error', reject);
    };

    attempt(url, 10);
  });
}

// ── SHA256 verification ─────────────────────────────────────────────────────

function computeSha256(filePath) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256');
    const stream = fs.createReadStream(filePath);
    stream.on('data', chunk => hash.update(chunk));
    stream.on('end', () => resolve(hash.digest('hex')));
    stream.on('error', reject);
  });
}

async function verifySha256(filePath, checksumFilePath) {
  const raw = fs.readFileSync(checksumFilePath, 'utf8').trim();
  // Format: "<hash>  <filename>" or "<hash> <filename>" or just "<hash>"
  const expected = raw.split(/\s+/)[0].toLowerCase();
  const actual = await computeSha256(filePath);
  if (actual !== expected) {
    throw new Error(
      `SHA256 mismatch for ${path.basename(filePath)}\n` +
      `  expected: ${expected}\n` +
      `  actual:   ${actual}`,
    );
  }
}

// ── Main export ─────────────────────────────────────────────────────────────

async function downloadBinary(version, target, cacheDir) {
  const ext = process.platform === 'win32' ? '.exe' : '';
  const binaryName = `openvegas-${target}${ext}`;
  const checksumName = `${binaryName}.sha256`;

  const binaryUrl = `${GITHUB_BASE}/v${version}/${binaryName}`;
  const checksumUrl = `${GITHUB_BASE}/v${version}/${checksumName}`;

  const binaryDest = path.join(cacheDir, binaryName);
  const checksumDest = path.join(cacheDir, checksumName);

  const RETRIES = 2;
  let lastErr;

  for (let attempt = 0; attempt <= RETRIES; attempt++) {
    if (attempt > 0) {
      const wait = attempt * 1000;
      process.stderr.write(`[openvegas] Retrying in ${wait / 1000}s...\n`);
      await new Promise(r => setTimeout(r, wait));
    }
    try {
      process.stderr.write(`[openvegas] Downloading ${binaryName} (v${version})...\n`);
      await downloadFile(binaryUrl, binaryDest);

      process.stderr.write(`[openvegas] Downloading checksum...\n`);
      await downloadFile(checksumUrl, checksumDest);

      process.stderr.write(`[openvegas] Verifying checksum...\n`);
      await verifySha256(binaryDest, checksumDest);

      if (process.platform !== 'win32') {
        fs.chmodSync(binaryDest, 0o755);
      }

      process.stderr.write(`[openvegas] Ready.\n`);
      return;
    } catch (err) {
      lastErr = err;
      // Clean up partial files before retry
      for (const f of [binaryDest, checksumDest]) {
        try { fs.unlinkSync(f); } catch { /* ignore */ }
      }
    }
  }

  throw lastErr;
}

module.exports = { downloadBinary };
