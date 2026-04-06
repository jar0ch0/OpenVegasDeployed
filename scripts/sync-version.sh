#!/usr/bin/env bash
# Sync the version from pyproject.toml into npm-cli/package.json.
# Usage: bash scripts/sync-version.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

VERSION=$(python3 -c "
import re, sys
content = open('$REPO_ROOT/pyproject.toml').read()
m = re.search(r'^version\s*=\s*\"([^\"]+)\"', content, re.MULTILINE)
if not m:
    sys.exit('Could not find version in pyproject.toml')
print(m.group(1))
")

echo "==> Syncing version $VERSION to npm-cli/package.json"

node -e "
const fs = require('fs');
const p = '$REPO_ROOT/npm-cli/package.json';
const pkg = JSON.parse(fs.readFileSync(p, 'utf8'));
pkg.version = '$VERSION';
fs.writeFileSync(p, JSON.stringify(pkg, null, 2) + '\n');
"

echo "==> Done"
