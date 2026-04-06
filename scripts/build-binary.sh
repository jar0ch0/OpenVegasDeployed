#!/usr/bin/env bash
# Build a standalone OpenVegas CLI binary using PyInstaller.
# Usage: bash scripts/build-binary.sh <target>
#   target: linux-x64 | darwin-arm64 | darwin-x64 | win-x64
set -euo pipefail

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
  echo "Usage: $0 <target>" >&2
  echo "  target: linux-x64 | darwin-arm64 | darwin-x64 | win-x64" >&2
  exit 1
fi

case "$TARGET" in
  linux-x64|darwin-arm64)
    BINARY_NAME="openvegas-${TARGET}"
    EXE_SUFFIX=""
    ;;
  win-x64)
    BINARY_NAME="openvegas-${TARGET}"
    EXE_SUFFIX=".exe"
    ;;
  *)
    echo "Unknown target: $TARGET" >&2
    exit 1
    ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Building $BINARY_NAME for target $TARGET"

pyinstaller \
  --onefile \
  --name "$BINARY_NAME" \
  --collect-all textual \
  --collect-all rich \
  --collect-all openai \
  --collect-all anthropic \
  --collect-all google.generativeai \
  --hidden-import click \
  --hidden-import httpx \
  --hidden-import httpx._transports.default \
  --hidden-import supabase \
  --hidden-import gotrue \
  --hidden-import storage3 \
  --hidden-import postgrest \
  --hidden-import jose \
  --hidden-import jose.jwt \
  --hidden-import cryptography \
  --hidden-import websockets \
  --hidden-import stripe \
  --hidden-import redis \
  --hidden-import celery \
  --hidden-import PIL \
  --hidden-import PIL.Image \
  --hidden-import qrcode \
  --hidden-import anyio \
  --hidden-import sniffio \
  --hidden-import certifi \
  --hidden-import charset_normalizer \
  --hidden-import h11 \
  --hidden-import h2 \
  --hidden-import hpack \
  --hidden-import hyperframe \
  openvegas/cli.py

echo "==> Binary written to dist/${BINARY_NAME}${EXE_SUFFIX}"

# Generate SHA256 checksum (Linux/macOS only — Windows handled in CI)
if command -v sha256sum &>/dev/null; then
  sha256sum "dist/${BINARY_NAME}${EXE_SUFFIX}" > "dist/${BINARY_NAME}${EXE_SUFFIX}.sha256"
  echo "==> Checksum written to dist/${BINARY_NAME}${EXE_SUFFIX}.sha256"
elif command -v shasum &>/dev/null; then
  shasum -a 256 "dist/${BINARY_NAME}${EXE_SUFFIX}" > "dist/${BINARY_NAME}${EXE_SUFFIX}.sha256"
  echo "==> Checksum written to dist/${BINARY_NAME}${EXE_SUFFIX}.sha256"
fi
