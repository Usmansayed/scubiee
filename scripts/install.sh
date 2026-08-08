#!/usr/bin/env bash
# Context Engine installer — ONE command for full MCP setup: bash scripts/install.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PROFILE="${1:-auto}"
INDEX_PATH="${2:-}"

echo "==> Installing Context Engine (Cursor MCP)"

if [[ ! -x .venv/bin/python ]]; then
  echo "==> Creating .venv"
  python3 -m venv .venv
fi
PY="$(pwd)/.venv/bin/python"

echo "==> Package + Graphify + MCP"
"$PY" -m pip install -U pip setuptools wheel
"$PY" -m pip install -e ".[mcp]"

echo "==> Configure (GPU/CPU, start service, register MCP)"
SETUP_ARGS=()
if [[ "$PROFILE" != "auto" ]]; then
  SETUP_ARGS+=(--profile "$PROFILE")
fi
if [[ -n "$INDEX_PATH" ]]; then
  SETUP_ARGS+=(--register --repo "$INDEX_PATH")
fi
"$PY" -m pipeline setup "${SETUP_ARGS[@]+"${SETUP_ARGS[@]}"}"

echo
echo "Done. Context Engine MCP is installed."
echo "  1. Reload MCP in Cursor (Settings → MCP → refresh)"
echo "  2. Use tools: search_code, locate_capability, status, …"
echo "  Optional CLI: .venv/bin/ctx search 'your query' ."
echo "  Optional UI:  http://127.0.0.1:8765/dashboard"
