#!/usr/bin/env bash
# Real-user journey for scubiee inside a fresh Linux container (see run.ps1).
#   Phase A: the published PyPI release, installed the way the README says.
#   Phase B: the local wheel in /vm/dist (unreleased changes), same repo.
# Every step logs to /vm/logs/<NN_name>.log; interactive steps run under a real
# pty via script(1) and also save frame timing (<NN_name>.timing).
set -u
LOG=/vm/logs
REPO=/work/flask
mkdir -p "$LOG" /work
rm -f "$LOG"/*
printf "step\trc\tseconds\n" > "$LOG/steps.tsv"
export PATH="$HOME/.local/bin:$PATH"
export TERM=xterm-256color COLUMNS=110 LINES=40
n=0

_record() {  # id rc t0
  local dt
  dt=$(python3 -c "print(f'{$EPOCHREALTIME - $3:.1f}')")
  printf "%s\t%s\t%s\n" "$1" "$2" "$dt" | tee -a "$LOG/steps.tsv"
}

step() {  # step <name> <shell command>   — piped, like a script or CI
  n=$((n + 1)); local id; id=$(printf "%02d_%s" "$n" "$1")
  local t0=$EPOCHREALTIME
  bash -c "$2" >"$LOG/$id.log" 2>&1 </dev/null
  _record "$id" $? "$t0"
}

tty_step() {  # tty_step <name> <stdin answer> <shell command>   — real terminal
  n=$((n + 1)); local id; id=$(printf "%02d_%s" "$n" "$1")
  local t0=$EPOCHREALTIME
  printf '%b' "$2" | script -q -e -f --log-timing "$LOG/$id.timing" -c "$3" "$LOG/$id.log" >/dev/null 2>&1
  _record "$id" $? "$t0"
}

echo "== prereqs"
apt-get -qq update >/dev/null && apt-get -qq install -y git procps >/dev/null 2>&1
git clone -q --depth 1 https://github.com/pallets/flask "$REPO"

echo "== Phase A: PyPI release"
step install            "pip install -q uv && uv tool install scubiee"
step no_args            "scubiee"
step version            "scubiee --version"
step init_before_setup  "cd $REPO && scubiee init . --confirm"
tty_step setup          ""        "scubiee setup"
step setup_status       "scubiee setup --status"
tty_step init           "y\n"     "cd $REPO && scubiee init ."
step status             "cd $REPO && scubiee status ."
step search             "cd $REPO && scubiee search 'how are url routes registered' ."
step map_find           "cd $REPO && scubiee map --config find 'register url route' ."
step map_focus          "cd $REPO && scubiee map --config focus --names add_url_rule ."
step connect_dry_run    "cd $REPO && scubiee connect --all --dry-run"
step connect_cursor     "cd $REPO && scubiee connect --cursor && ls -la ~/.cursor ~/.cursor/rules"
step edit_and_sync      "cd $REPO && printf '\n\ndef scubiee_canary_symbol():\n    \"\"\"Freshness canary added by the journey.\"\"\"\n    return 42\n' >> src/flask/helpers.py && scubiee sync ."
step search_canary      "cd $REPO && scubiee search 'scubiee_canary_symbol freshness canary' ."
tty_step reinit         ""        "cd $REPO && scubiee init ."
step doctor             "cd $REPO && scubiee doctor ."
step list               "scubiee list"
step stop               "scubiee stop"
step status_stopped     "cd $REPO && scubiee status ."
step resume             "scubiee resume"
step upgrade            "scubiee upgrade"
step wipe_repo          "cd $REPO && scubiee wipe . --confirm"
step status_after_wipe  "cd $REPO && scubiee status ."

echo "== Phase B: local wheel"
WHEEL=$(ls /vm/dist/scubiee-*.whl | head -n1)
step local_install      "uv tool install --force --reinstall '$WHEEL'"
tty_step init_local     "y\n"     "cd $REPO && scubiee init ."
step search_local       "cd $REPO && scubiee search 'how are url routes registered' ."
tty_step wipe_all       ""        "scubiee wipe --all --confirm --keep-package"
step status_final       "cd $REPO && scubiee status ."

echo "== done"
cat "$LOG/steps.tsv"
