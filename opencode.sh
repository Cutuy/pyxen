#!/bin/bash
# opencode.sh — Launch OpenCode CLI for the pyxen project only
#
# Usage:
#   ./opencode.sh          — interactive TUI
#   ./opencode.sh run ...  — run prompt (non-interactive)
#
# Ensures opencode runs with pyxen's local config and repository context.
# Model: deepseek/deepseek-v4-pro via @ai-sdk/openai-compatible plugin.
# API key: loaded from .env (DEEPSEEK_API_KEY) via {env:...} in config.
#

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Load .env into environment ───────────────────────────────────────
if [ -f "$DIR/.env" ]; then
  set -a
  source "$DIR/.env"
  set +a
fi

# ── Ensure opencode is on PATH ───────────────────────────────────────
if ! command -v opencode &>/dev/null; then
  export PATH="$HOME/.opencode/bin:$PATH"
fi

if ! command -v opencode &>/dev/null; then
  echo "❌ OpenCode not found. Install it:"
  echo "   curl -fsSL https://opencode.ai/install | bash"
  exit 1
fi

cd "$DIR"

# If first arg is "run" or non-interactive commands, run from the pyxen dir
if [ "${1:-}" = "run" ] || [ "${1:-}" = "serve" ] || [ "${1:-}" = "web" ]; then
  exec opencode "$@"
fi

# Default: interactive TUI
echo "📦 Pyxen — OpenCode"
echo "   Config: $DIR/opencode.json"
echo "   Model:  deepseek/deepseek-v4-pro"
echo ""

exec opencode "$DIR"
