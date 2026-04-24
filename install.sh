#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WIKI_DIR="${WIKI_DIR:-$HOME/Wiki}"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install it from https://docs.astral.sh/uv/"
  exit 1
fi

echo "=== Apple Notes Wiki Daemon Setup ==="
echo "Project source: $SCRIPT_DIR"
echo "Wiki home: $WIKI_DIR"

mkdir -p "$WIKI_DIR/inbox" "$WIKI_DIR/processed" "$WIKI_DIR/cache/extracted" "$LAUNCH_AGENTS"

if [ ! -f "$WIKI_DIR/config.yml" ]; then
  cp "$SCRIPT_DIR/config.sample.yml" "$WIKI_DIR/config.yml"
fi

if [ ! -f "$WIKI_DIR/schema.md" ]; then
  cp "$SCRIPT_DIR/schema_templates/general.md" "$WIKI_DIR/schema.md"
fi

if [ ! -f "$WIKI_DIR/state.json" ]; then
  printf '%s\n' '{"version":1,"last_run":"","last_lint":"","notes":{},"processed_files":{},"folders_created":[]}' > "$WIKI_DIR/state.json"
fi

uv sync --project "$SCRIPT_DIR"

PYTHON_PATH="$SCRIPT_DIR/.venv/bin/python"

sed \
  -e "s|/usr/local/bin/python3|$PYTHON_PATH|g" \
  -e "s|/Users/USERNAME/Wiki|$WIKI_DIR|g" \
  "$SCRIPT_DIR/launchd/com.user.wiki-daemon.plist" > "$LAUNCH_AGENTS/com.user.wiki-daemon.plist"

sed \
  -e "s|/usr/local/bin/python3|$PYTHON_PATH|g" \
  -e "s|/Users/USERNAME/Wiki|$WIKI_DIR|g" \
  "$SCRIPT_DIR/launchd/com.user.wiki-lint.plist" > "$LAUNCH_AGENTS/com.user.wiki-lint.plist"

echo
echo "Files created:"
echo "- $WIKI_DIR/config.yml"
echo "- $WIKI_DIR/schema.md"
echo "- $WIKI_DIR/state.json"
echo
echo "Next steps:"
echo "1. Edit $WIKI_DIR/config.yml"
echo "2. Add API keys to $WIKI_DIR/.env or your shell environment"
echo "3. Start the agents with:"
echo "   launchctl load $LAUNCH_AGENTS/com.user.wiki-daemon.plist"
echo "   launchctl load $LAUNCH_AGENTS/com.user.wiki-lint.plist"
echo
echo "First run will require allowing Python to control Notes.app in macOS Automation settings."
