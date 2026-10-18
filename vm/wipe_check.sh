#!/usr/bin/env bash
# Live check of `scubiee wipe --all` with two enrolled repos, local wheel only.
#   powershell -File vm\run.ps1 wipe_check.sh
set -u
LOG=/vm/logs_wipe
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
for r in alpha beta; do
  mkdir -p /work/$r && cd /work/$r && git init -q
  for i in 1 2 3; do
    printf 'def %s_fn_%d(x):\n    """Return x plus %d."""\n    return x + %d\n' "$r" "$i" "$i" "$i" > "mod_$i.py"
  done
done

step install       "pip install -q uv && uv tool install $(ls -t /vm/dist/scubiee-*.whl | head -1)"
step setup         "scubiee setup"
tty_step init_alpha "y\n" "cd /work/alpha && scubiee init ."
tty_step init_beta  "y\n" "cd /work/beta && scubiee init ."
step list          "scubiee list"
tty_step wipe_all  ""     "cd /work/alpha && scubiee wipe --all --confirm --keep-package"
step leftovers     "ls -la /root/.scubiee /work/alpha/.scubiee /work/beta/.scubiee; for f in /root/.scubiee/*; do echo \"--- \$f\"; cat \"\$f\"; done; ps -eo pid,args | grep -i [s]cubiee"
step status_final  "cd /work/alpha && scubiee status ."
echo "== done"
