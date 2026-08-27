#!/usr/bin/env bash
# Copy the watcher + its dependencies into deploy/fc_watcher/ for packaging.
# Run from the repo root: bash deploy/fc_watcher/build_package.sh
#
# Copies: src/tripcascade/ (the full package — only the modules the watcher
# imports are loaded at runtime) + assets/demo_itinerary.json.
# Excludes: .git, __pycache__, tests/, logs/, .venv.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="$REPO_ROOT/deploy/fc_watcher"

echo "=== Cleaning $DEST ==="
rm -rf "$DEST/tripcascade" "$DEST/assets"
echo "=== Copying src/tripcascade -> $DEST/tripcascade ==="
cp -r "$REPO_ROOT/src/tripcascade" "$DEST/tripcascade"
echo "=== Copying assets/demo_itinerary.json -> $DEST/assets ==="
mkdir -p "$DEST/assets"
cp "$REPO_ROOT/assets/demo_itinerary.json" "$DEST/assets/"
echo "=== Stripping __pycache__ ==="
find "$DEST/tripcascade" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find "$DEST/tripcascade" -type f -name '.DS_Store' -delete 2>/dev/null || true

echo "=== Package contents ==="
find "$DEST" -type f | sort
echo "=== Done ==="
echo "Next: cd $DEST && s deploy"