#!/usr/bin/env bash
# Full real-CLI combination run in isolated CTX_HOME (safe — does not touch ~/.scubiee).
# Uses venv scubiee when .venv/bin/scubiee exists.
#
#   bash tests/_e2e_cli_combination_isolated.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

SCUBIEE="${SCUBIEE_BIN:-$REPO_ROOT/.venv/bin/scubiee}"
if [[ ! -x "$SCUBIEE" ]]; then
  SCUBIEE="$(command -v scubiee || true)"
fi
if [[ -z "$SCUBIEE" || ! -x "$SCUBIEE" ]]; then
  echo "No scubiee binary — run: uv venv .venv && uv pip install -e '.[mcp]'"
  exit 1
fi

export PATH="$(dirname "$SCUBIEE"):${HOME}/.local/bin:${PATH}"
export CTX_HOME="${CTX_HOME:-$(mktemp -d /tmp/scubiee-combo-XXXXXX)}"
TINY_REPO="${CTX_HOME}/tiny-repo"
mkdir -p "$TINY_REPO/.git"
echo 'print("hi")' > "$TINY_REPO/app.py"

LOG="$REPO_ROOT/tests/_cli_combo_isolated_results.txt"
JSON="$REPO_ROOT/tests/_cli_combo_isolated.json"
: > "$LOG"

log() { echo "$1" | tee -a "$LOG"; }

log "=== Scubiee isolated CLI combination $(date -Iseconds) ==="
log "CTX_HOME=$CTX_HOME"
log "SCUBIEE=$SCUBIEE"
log "Version: $($SCUBIEE --version 2>&1 | tail -1)"

log ""
log "=== 1. Combination matrix (full, real scubiee binary) ==="
PYTHON="${REPO_ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then PYTHON="$(command -v python3)"; fi
"$PYTHON" "$REPO_ROOT/scripts/run_cli_combination_tests.py" \
  --cli "$SCUBIEE" \
  --repo "$TINY_REPO" \
  --json "$JSON" 2>&1 | tee -a "$LOG"
COMBO_EXIT=${PIPESTATUS[0]}

log ""
log "=== 2. Connect dry-run E2E (real scubiee) ==="
export CTX_HOME
bash "$REPO_ROOT/tests/_e2e_run_connect.sh" 2>&1 | tee -a "$LOG" || true

log ""
log "=== 3. MCP merge experiment — 13 tools (real scubiee subprocess) ==="
unset CTX_HOME
export PATH="$(dirname "$SCUBIEE"):${HOME}/.local/bin:${PATH}"
"$PYTHON" "$REPO_ROOT/tests/_e2e_mcp_merge_experiment.py" 2>&1 | tee -a "$LOG" || true

log ""
log "=== 4. Bash MCP merge (cursor/claude/codex/opencode) ==="
bash "$REPO_ROOT/tests/_e2e_mcp_merge_experiment.sh" 2>&1 | tee -a "$LOG" || true

log ""
log "=== DONE combo_exit=$COMBO_EXIT $(date -Iseconds) ==="
log "Results: $LOG"
log "JSON: $JSON"
exit "$COMBO_EXIT"
