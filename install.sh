#!/usr/bin/env bash
# Install the APIParityAgent skill into ~/.cursor/skills/
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/APIParityAgent"
DEST_DIR="${CURSOR_SKILLS_DIR:-$HOME/.cursor/skills}"
DEST="$DEST_DIR/APIParityAgent"

[ -d "$SRC" ] || { echo "error: $SRC not found — run this from the cloned repo" >&2; exit 1; }

mkdir -p "$DEST_DIR"

if [ -e "$DEST" ]; then
  BACKUP="$DEST.bak-$(date +%Y%m%d-%H%M%S)"
  mv "$DEST" "$BACKUP"
  echo "backed up existing skill -> $BACKUP"
fi

cp -R "$SRC" "$DEST"
find "$DEST" -name '.DS_Store' -delete

echo "installed -> $DEST"
find "$DEST" -type f | sort | sed "s|$DEST|  APIParityAgent|"

command -v python3 >/dev/null || echo "warning: python3 not found; the SQL tools will not run"

echo
echo "Restart Cursor (Cmd+Q, then reopen), then run: APIParityAgent compare ms-consumer"
