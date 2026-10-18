#!/usr/bin/env bash
# Live check: stop → resume brings the engine back quickly and reports honestly.
#   powershell -File vm\run.ps1 resume_check.sh
set -u
LOG=/vm/logs_resume
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
R=/work/app
mkdir -p $R/src && cd $R && git init -q
for i in 1 2 3; do
  printf 'def handle_%d(x):\n    """Handle case %d."""\n    return x + %d\n' "$i" "$i" "$i" > "src/m_$i.py"
done

step install        "pip install -q uv && uv tool install $(ls -t /vm/dist/scubiee-*.whl | head -1)"
step setup          "scubiee setup"
tty_step init       "y\n" "cd $R && scubiee init ."
step connect        "cd $R && scubiee connect --cursor"
step stop           "scubiee stop --yes"
step status_stopped "cd $R && scubiee status ."
step resume         "scubiee resume"
step health         "python3 -c \"import urllib.request as u; print(u.urlopen('http://127.0.0.1:8765/health', timeout=3).read()[:300].decode())\""
step search         "cd $R && scubiee search 'handle case two' ."
step stop2          "scubiee stop --yes"
tty_step resume_tty "" "scubiee resume"
step health2        "python3 -c \"import urllib.request as u; print(u.urlopen('http://127.0.0.1:8765/health', timeout=3).read()[:300].decode())\""
echo "== done"
