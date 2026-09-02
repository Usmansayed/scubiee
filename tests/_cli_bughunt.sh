#!/usr/bin/env bash
# Real scubiee CLI bug-hunt — edge cases, error paths, ordering traps.
# Safe: uses isolated CTX_HOME only (never touches ~/.scubiee).
#
#   SCUBIEE_BIN=/path/to/scubiee bash tests/_cli_bughunt.sh

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCUBIEE="${SCUBIEE_BIN:-scubiee}"
export CTX_HOME="$(mktemp -d /tmp/scubiee-bughunt-XXXXXX)"
TINY="${CTX_HOME}/tiny"
NONGIT="${CTX_HOME}/nongit"
mkdir -p "$TINY/.git" "$NONGIT"
echo 'def bar(): pass' > "$TINY/app.py"
echo 'x=1' > "$NONGIT/readme.txt"

LOG="${REPO_ROOT}/tests/_cli_bughunt_results.txt"
: > "$LOG"
PASS=0
FAIL=0
BUG=0

log() { echo "$1" | tee -a "$LOG"; }

# run ID "desc" expect_exit cmd...
run() {
  local id="$1" desc="$2" expect="$3"
  shift 3
  local out exit
  out="$("$SCUBIEE" "$@" 2>&1)" || true
  exit=$?
  local ok=0
  case "$expect" in
    0)   [[ "$exit" -eq 0 ]] && ok=1 ;;
    nonzero) [[ "$exit" -ne 0 ]] && ok=1 ;;
    2)   [[ "$exit" -eq 2 ]] && ok=1 ;;
    any) ok=1 ;;
  esac
  local status="PASS"
  if [[ "$ok" -eq 0 ]]; then
    status="FAIL"
    ((FAIL++)) || true
  else
    ((PASS++)) || true
  fi
  local tail="${out//$'\n'/ | }"
  tail="${tail:0:200}"
  log "[$status] $id $desc | exit=$exit expect=$expect | $tail"
}

# run_bug ID "desc" — flag unexpected success as potential bug
run_bug() {
  local id="$1" desc="$2" expect="$3"
  shift 3
  local out exit
  out="$("$SCUBIEE" "$@" 2>&1)" || true
  exit=$?
  local ok=0
  case "$expect" in
    0)   [[ "$exit" -eq 0 ]] && ok=1 ;;
    nonzero) [[ "$exit" -ne 0 ]] && ok=1 ;;
    json_ok) echo "$out" | grep -q '"ok": true' && ok=1 ;;
    json_fail) echo "$out" | grep -q '"ok": false' && ok=1 ;;
    blocked) echo "$out" | grep -qi 'stopped\|globally stopped\|resume' && ok=1 ;;
    state:*) local want="${expect#state:}"; echo "$out" | grep -q "\"state\": \"$want\"" && ok=1 ;;
  esac
  local status="PASS"
  if [[ "$ok" -eq 0 ]]; then
    status="BUG?"
    ((BUG++)) || true
  else
    ((PASS++)) || true
  fi
  local tail="${out//$'\n'/ | }"
  tail="${tail:0:250}"
  log "[$status] $id $desc | exit=$exit expect=$expect | $tail"
}

log "=== CLI bug hunt $(date -Iseconds) ==="
log "SCUBIEE=$SCUBIEE version=$($SCUBIEE --version 2>&1 | tail -1)"
log "CTX_HOME=$CTX_HOME"

# --- bootstrap ---
run B01 "setup --repair" 0 setup --repair
run B02 "init tiny repo" 0 init "$TINY"
run B03 "init idempotent" 0 init "$TINY"
run B04 "status enrolled" 0 status "$TINY"

# --- invalid / edge inputs ---
run E01 "init non-git dir" nonzero init "$NONGIT"
run E02 "activate unmanaged" nonzero activate "$NONGIT"
run E03 "pause unmanaged" nonzero pause "$NONGIT"
run E04 "search empty query" any search "$TINY" ""
run E05 "gate unmanaged" any gate "$NONGIT"
run E06 "invalid subcommand" nonzero not-a-real-cmd
run E07 "connect bogus tool" nonzero connect --bogus-tool --dry-run
run E08 "wipe without confirm" 2 wipe --all
run E09 "wipe repo no confirm" 2 wipe "$TINY"

# --- lifecycle ---
run_bug L01 "pause repo" json_ok pause "$TINY"
run_bug L02 "activate un-pauses" state:active activate "$TINY"
run_bug L03 "pause again" json_ok pause "$TINY"
run_bug L04 "resume repo" state:active resume "$TINY"
run_bug L05 "never-index blocks init" json_fail init "$TINY"
run_bug L06 "activate never-index fails" json_fail activate "$TINY"

run L07 "rebuild" any rebuild "$TINY"

# --- global stop matrix ---
run G01 "stop global" 0 stop -y
run_bug G02 "init blocked when stopped" blocked init "$TINY"
run_bug G03 "search blocked" blocked search "$TINY" "def"
run_bug G04 "sync-now blocked" blocked sync-now "$TINY"
run G05 "gate allowed when stopped" any gate "$TINY"
run G06 "doctor allowed when stopped" any doctor
run G07 "list allowed when stopped" any list
run G08 "resume global" 0 resume

# --- engine-only stop ---
run EN01 "engine stop" any engine stop
run_bug EN02 "init after engine stop" 0 init "$TINY"
run EN03 "engine ensure" any engine ensure "$TINY"
run EN04 "engine status" any engine status "$TINY"

# --- connect/disconnect ---
run C01 "connect cursor dry-run" 0 connect --cursor --dry-run
run C02 "connect all dry-run" 0 connect --all --dry-run
run C03 "disconnect cursor noop" any disconnect --cursor
run C04 "connect help" 0 connect --help

# --- recovery / ordering ---
run R01 "halt" any halt
run R02 "resume after halt" any resume
run R03 "double resume noop" any resume
run R04 "double stop noop" any stop -y
run R05 "upgrade check" any upgrade --check
run R06 "migrate check" any migrate --check
run R07 "unlock-tool" any unlock-tool
run R08 "preflight" any preflight
run R09 "diagnose" any diagnose

# --- wipe repo (managed) ---
run W01 "repo wipe confirm" any wipe "$TINY" --confirm
run_bug W02 "status after repo wipe" json_fail status "$TINY"
run W03 "re-init after wipe" 0 init "$TINY"

# --- init combos ---
run I01 "init after stop+resume" any stop -y
run I02 "resume" any resume
run I03 "init after cycle" 0 init "$TINY"

# --- stress: rapid commands ---
for i in 1 2 3; do
  run "S0$i pause-resume rapid" any pause "$TINY"
  run "S1$i activate rapid" any activate "$TINY"
done

# --- moved path simulation (symlink) ---
LINK="${CTX_HOME}/tiny-link"
ln -sfn "$TINY" "$LINK"
run_bug M01 "gate via symlink" 0 gate "$LINK"
run_bug M02 "status via symlink" json_ok status "$LINK"

log ""
log "=== SUMMARY pass=$PASS fail=$FAIL bug?=$BUG ==="
log "CTX_HOME=$CTX_HOME (left for inspection)"
log "Log: $LOG"

if [[ "$FAIL" -gt 0 || "$BUG" -gt 0 ]]; then
  exit 1
fi
exit 0
