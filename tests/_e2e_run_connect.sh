#!/usr/bin/env bash
# Connect dry-run E2E — real scubiee commands, no IDE config writes.
# Run from repo root: bash tests/_e2e_run_connect.sh

set +e
unset CTX_HOME

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
export PATH="${HOME}/.local/bin:${PATH}"

LOG="${REPO_ROOT}/tests/_connect_e2e_results.txt"
DRY_JSON="${REPO_ROOT}/tests/_connect_dry_run.json"

: > "$LOG"

log() {
  echo "$1" | tee -a "$LOG"
}

run() {
  local id="$1" cmd="$2" expect="$3"
  log ""
  log "=== $id : $cmd ==="
  eval "$cmd" >> "$LOG" 2>&1
  local exit=$?
  log "[$id] exit=$exit expect=$expect"
  return "$exit"
}

log "=== Scubiee connect E2E $(date -Iseconds) ==="
log "Repo: $REPO_ROOT"

# Need enrollment for fan-out
if [ ! -f .scubiee/id.json ]; then
  log "[setup] not enrolled — running setup + init"
  scubiee setup --repair >> "$LOG" 2>&1
  scubiee init . >> "$LOG" 2>&1
fi

# --- Dry-run: priority tools ---
run C1 "scubiee connect --cursor --claude-code --codex --opencode --amp --pi --dry-run" "OK exit 0"

# --- Dry-run: all tools ---
run C2 "scubiee connect --all --dry-run > \"$DRY_JSON\"" "OK exit 0"

if command -v python3 >/dev/null 2>&1 && [ -f "$DRY_JSON" ]; then
  python3 - <<'PY' >> "$LOG" 2>&1
import json, pathlib, sys
p = pathlib.Path("tests/_connect_dry_run.json")
raw = p.read_text(encoding="utf-8-sig")
data = json.loads(raw)
bad = [x.get("slug") for x in data if not x.get("ok")]
print(f"[C2-check] tools={len(data)} bad={bad}")
if bad:
    sys.exit(1)
for x in data:
    print(f"  {x['slug']:16} {x.get('mcp_path','')}")
PY
  log "[C2-check] exit=$?"
fi

# --- Help ---
run C3 "scubiee connect --help" "OK"
run C4 "scubiee disconnect --help" "OK"

# --- Real connect for cursor only (optional: comment out if you prefer dry-run only) ---
# Uncomment to write real MCP on your machine:
# run C5 "scubiee connect --cursor" "OK"
# run C6 "test -f .cursor/mcp.json && echo cursor_mcp_exists" "OK"

log ""
log "=== DONE $(date -Iseconds) ==="
log "Results: $LOG"
log "Dry-run JSON: $DRY_JSON"
