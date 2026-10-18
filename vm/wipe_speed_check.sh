#!/usr/bin/env bash
# Live check: `wipe --all` run from a big home folder — PyPI 0.3.154 vs local wheel.
#   powershell -File vm\run.ps1 wipe_speed_check.sh
set -u
LOG=/vm/logs_wipe_speed
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
pip install -q uv

# A realistic "big" home: a JS project with a deep node_modules tree.
python3 - <<'PY'
import os
root = "/root/Downloads/webapp/node_modules"
n = 0
for a in range(300):
    for b in range(40):
        d = f"{root}/pkg{a}/lib/sub{b}"
        os.makedirs(d, exist_ok=True)
        for c in range(25):
            open(f"{d}/f{c}.js", "w").close()
            n += 1
print("seeded files:", n)
PY

R=/work/app
mkdir -p $R/src && cd $R && git init -q
for i in 1 2 3; do
  printf 'def handle_%d(x):\n    """Handle case %d."""\n    return x + %d\n' "$i" "$i" "$i" > "src/m_$i.py"
done

WHEEL=$(ls -t /vm/dist/scubiee-*.whl | head -1)

# --- Before: published 0.3.154 (skip with SKIP_OLD=1) ---------------------
if [ -z "${SKIP_OLD:-}" ]; then
step  old_install  "uv tool install scubiee==0.3.154 --index-url https://pypi.org/simple"
step  old_setup    "scubiee setup"
tty_step old_init  "y\n" "cd $R && scubiee init ."
step  old_connect  "cd $R && scubiee connect --cursor"
step  old_wipe_from_home "cd /root && timeout 300 scubiee wipe --all --confirm"
step  old_reset    "pkill -f '[s]cubiee engine|[p]ipeline engine' ; uv tool uninstall scubiee ; rm -rf /root/.scubiee /root/.cache/fastembed /root/.local/bin/scubiee* /root/.local/share/uv/tools/scubiee* $R/.scubiee; true"
fi

# --- After: local wheel ----------------------------------------------------
step  new_install  "uv tool install $WHEEL"
step  new_setup    "scubiee setup"
tty_step new_init  "y\n" "cd $R && scubiee init ."
step  new_connect  "cd $R && scubiee connect --cursor"
tty_step new_wipe_from_home "" "cd /root && scubiee wipe --all --confirm"
step  new_state_right_after "ls -d /root/.scubiee /root/.cache/fastembed $R/.scubiee 2>&1; command -v scubiee || echo 'scubiee: not on PATH'; ls -d /root/.scubiee.trash-* /root/.cache/fastembed.trash-* 2>/dev/null | sed 's/^/trash: /'"
step  new_trash_drained "for i in \$(seq 1 150); do ls -d /root/.scubiee.trash-* /root/.cache/fastembed.trash-* >/dev/null 2>&1 || { echo drained; exit 0; }; sleep 0.2; done; echo NOT_DRAINED; exit 1"
step  new_reinstall "uv tool install $WHEEL"
step  new_resetup  "scubiee setup"
step  new_ps_leftovers "ps -eo pid,args | grep -E 'scubiee|pipeline' | grep -v grep || echo none"
echo "== done"
