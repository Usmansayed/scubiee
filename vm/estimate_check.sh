#!/usr/bin/env bash
# Live check: init's "(est. …)" vs real wall time — first with only setup's
# calibration, then with the speed measured by that first init.
#   powershell -File vm\run.ps1 estimate_check.sh
set -u
LOG=/vm/logs_estimate
mkdir -p "$LOG" /work
rm -f "$LOG"/*
printf "step\trc\tseconds\n" > "$LOG/steps.tsv"
export PATH="$HOME/.local/bin:$PATH"
export TERM=xterm-256color COLUMNS=110 LINES=40
n=0

_record() {
  local dt
  dt=$(python3 -c "print(f'{$EPOCHREALTIME - $3:.1f}')")
  printf "%s\t%s\t%s\n" "$1" "$2" "$dt" | tee -a "$LOG/steps.tsv"
}

step() {
  n=$((n + 1)); local id; id=$(printf "%02d_%s" "$n" "$1")
  local t0=$EPOCHREALTIME
  bash -c "$2" >"$LOG/$id.log" 2>&1 </dev/null
  _record "$id" $? "$t0"
}

tty_step() {
  n=$((n + 1)); local id; id=$(printf "%02d_%s" "$n" "$1")
  local t0=$EPOCHREALTIME
  printf '%b' "$2" | script -q -e -f --log-timing "$LOG/$id.timing" -c "$3" "$LOG/$id.log" >/dev/null 2>&1
  _record "$id" $? "$t0"
}

apt-get -qq update >/dev/null && apt-get -qq install -y git procps >/dev/null 2>&1
git clone -q --depth 1 https://github.com/pallets/flask /work/flask
git clone -q --depth 1 https://github.com/psf/requests /work/requests

step install          "pip install -q uv && uv tool install $(ls -t /vm/dist/scubiee-*.whl | head -1)"
step setup            "scubiee setup"
tty_step init_flask   "y\n" "cd /work/flask && scubiee init ."
step throughput       "cat /root/.scubiee/embed_throughput.json"
tty_step init_requests "y\n" "cd /work/requests && scubiee init ."
step throughput2      "cat /root/.scubiee/embed_throughput.json"
echo "== done"
