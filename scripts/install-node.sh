#!/usr/bin/env bash
# Idempotent: install Node (Apple Silicon) into repo .tools/node for npm without global Homebrew.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOLS="$ROOT/.tools"
NODE_V="${NODE_V:-20.18.1}"
ARCHIVE="node-v${NODE_V}-darwin-arm64.tar.xz"
URL="https://nodejs.org/dist/v${NODE_V}/${ARCHIVE}"

if [ -x "$TOOLS/node/bin/node" ]; then
  echo "Node already at $TOOLS/node/bin/node — $("$TOOLS/node/bin/node" -v)"
  exit 0
fi

mkdir -p "$TOOLS"
echo "Downloading $URL ..."
/usr/bin/curl -fsSL "$URL" -o "$TOOLS/$ARCHIVE"
cd "$TOOLS"
tar -xJf "$ARCHIVE"
mv -f "node-v${NODE_V}-darwin-arm64" node
rm -f "$ARCHIVE"
echo "Installed: $("$TOOLS/node/bin/node" -v) (npm $("$TOOLS/node/bin/npm" -v))"
