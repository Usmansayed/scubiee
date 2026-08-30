#!/usr/bin/env bash
# Real scubiee CLI combination test - user-side commands only (macOS / Linux).
# Run from repo root: bash tests/_e2e_run_cmds.sh

set +e
unset CTX_HOME

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

export PATH="${HOME}/.local/bin:${PATH}"
LOG="${REPO_ROOT}/tests/_e2e_cmd_results.txt"

: > "$LOG"

log() {
  local id="$1" exit="$2" cmd="$3" expect="$4" tail="$5"
  local line="[$id] exit=$exit | $cmd | $expect :: $tail"
  echo "$line" >> "$LOG"
  echo "$line"
}

run() {
  local id="$1" cmd="$2" expect="$3"
  echo ""
  echo "=== $id : $cmd ==="
  local out
  out="$(eval "$cmd" 2>&1)"
  local exit=$?
  local tail="${out:0:400}"
  [[ ${#out} -gt 400 ]] && tail="${tail}..."
  tail="${tail//$'\n'/ | }"
  log "$id" "$exit" "$cmd" "$expect" "$tail"
  return "$exit"
}

{
  echo "=== Scubiee real CLI test $(date -Iseconds) ==="
  echo "Repo: $REPO_ROOT"
  echo "Version: $(scubiee --version 2>&1 | head -1)"
} >> "$LOG"

# --- Baseline ---
run B1 "scubiee --version" "OK"
run B3 "scubiee doctor" "ANY"
run B5 "scubiee status ." "ANY"
run B7 "scubiee setup --repair" "OK"
run B8 "scubiee init ." "OK"
run B10 "scubiee status ." "OK enrolled"

# --- Global stop ---
run G1 "scubiee stop -y" "OK"
run G2 "scubiee stop -y" "NOOP"
run G3 "scubiee init ." "BLOCK"
run G5 "scubiee setup --repair" "OK repair allowed"
run G12 "scubiee doctor" "OK read-only"
run G14 "scubiee halt" "OK recovery"
run G17 "scubiee resume" "OK"
run G18 "scubiee init ." "OK idempotent"

# --- Halt / unlock ---
run H1 "scubiee halt" "OK"
run H2 "scubiee resume" "OK after halt"

# --- Repo wipe ---
run W1 "scubiee wipe . --confirm" "OK repo wipe"
id_exists=$([ -f .scubiee/id.json ] && echo true || echo false)
echo "[W1-check] .scubiee/id.json exists=$id_exists (expect false after wipe)" >> "$LOG"

run W1b "scubiee init ." "OK re-init after repo wipe"
run W2 "scubiee stop -y" "OK before full wipe prep"

# --- Full wipe (keep package) ---
run G16 "scubiee wipe --all" "CONFIRM exit 2"
run G16b "scubiee wipe --all --confirm --keep-package" "OK full clean"

home_exists=$([ -d "$HOME/.scubiee" ] && echo true || echo false)
echo "[G16b-check] ~/.scubiee exists=$home_exists (expect false)" >> "$LOG"
id_after=$([ -f .scubiee/id.json ] && echo true || echo false)
echo "[G16b-check] .scubiee/id.json exists=$id_after (expect false)" >> "$LOG"

# Belt-and-suspenders: keep-package wipe must leave the CLI on PATH (W5 regression).
if ! command -v scubiee >/dev/null 2>&1; then
  echo "[G16b-recover] scubiee missing after keep-package wipe — reinstalling from repo" >> "$LOG"
  if command -v uv >/dev/null 2>&1; then
    uv tool install --force . >> "$LOG" 2>&1 || true
  fi
fi
scubiee_ok=$([ -x "$(command -v scubiee 2>/dev/null || true)" ] && echo true || echo false)
echo "[G16b-check] scubiee on PATH=$scubiee_ok (expect true)" >> "$LOG"

# --- Post full wipe ---
run P1 "scubiee setup --repair" "OK after full wipe"
run P2 "scubiee init ." "OK fresh init"
run P3 "scubiee status ." "OK"

# --- Help / read-only ---
run R1 "scubiee --help" "OK"
run R2 "scubiee halt --help" "OK"
run R3 "scubiee wipe --help" "OK"
run R4 "scubiee list" "OK"

# --- Connect dry-run ---
run C1 "scubiee connect --cursor --claude-code --codex --opencode --amp --pi --dry-run" "OK"
run C2 "scubiee connect --all --dry-run > \"${REPO_ROOT}/tests/_connect_dry_run.json\"" "OK"

echo "=== DONE $(date -Iseconds) ===" >> "$LOG"
echo ""
echo "Results written to $LOG"
