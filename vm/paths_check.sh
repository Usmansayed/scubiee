#!/usr/bin/env bash
# Live check: every path connect/resume reports must exist on disk.
#   powershell -File vm\run.ps1 paths_check.sh
set -u
LOG=/vm/logs_paths
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

step install          "pip install -q uv && uv tool install $(ls -t /vm/dist/scubiee-*.whl | head -1)"
step setup            "scubiee setup"
step connect_pre_init "cd /tmp && scubiee connect --cursor"
tty_step init         "y\n" "cd $R && scubiee init ."
step connect_in_repo  "cd $R && scubiee connect --cursor"
step connect_from_root "cd / && scubiee connect --cursor"
step dry_run_from_root "cd / && scubiee connect --cursor --dry-run"
step stop             "scubiee stop --yes"
step resume_from_root "cd / && scubiee resume"

python3 - "$LOG" <<'PY'
import json, os, sys, glob
log = sys.argv[1]

def blob(path):
    text = open(path, encoding="utf-8", errors="replace").read()
    i = text.find("{")
    if i < 0:
        return None
    dec = json.JSONDecoder()
    while i >= 0:
        try:
            return dec.raw_decode(text[i:])[0]
        except ValueError:
            i = text.find("{", i + 1)
    return None

def tool_reports(obj):
    if isinstance(obj, dict):
        if "mcp_paths" in obj and "rule_paths" in obj and "slug" in obj:
            yield obj
        for v in obj.values():
            yield from tool_reports(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from tool_reports(v)

all_ok = True
for name in ("connect_pre_init", "connect_in_repo", "connect_from_root",
             "dry_run_from_root", "resume_from_root"):
    path = next(iter(glob.glob(f"{log}/*_{name}.log")), None)
    obj = blob(path) if path else None
    reps = list(tool_reports(obj)) if obj else []
    dry = name.startswith("dry_run")
    for r in reps:
        paths = [r.get("mcp_path"), r.get("rule_path")] + list(r.get("mcp_paths") or []) + list(r.get("rule_paths") or [])
        paths = [p for p in paths if p]
        missing = [p for p in paths if not os.path.exists(p)]
        outside = [p for p in paths if not p.startswith("/work/app/")]
        ok = not outside and (dry or not missing)
        if name == "connect_pre_init":
            ok = ok and not paths
        else:
            ok = ok and bool(r.get("mcp_path")) and bool(r.get("rule_path"))
        all_ok &= ok
        print(f"{name:20s} ok={ok} mcp_path={r.get('mcp_path')} rule_path={r.get('rule_path')} "
              f"n_mcp={len(r.get('mcp_paths') or [])} n_rules={len(r.get('rule_paths') or [])} "
              f"missing={missing} outside={outside}")
    if not reps:
        all_ok = False
        print(f"{name:20s} ok=False (no tool report found)")
print("ALL_OK", all_ok)
PY
echo "== done"
