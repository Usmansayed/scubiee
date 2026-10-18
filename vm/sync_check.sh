#!/usr/bin/env bash
# Live check: `scubiee sync .` returns only after the edit is searchable.
#   powershell -File vm\run.ps1 sync_check.sh
set -u
LOG=/vm/logs_sync
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
for i in 1 2 3 4 5; do
  printf 'def compute_total_%d(items):\n    """Sum item prices for order %d."""\n    return sum(i.price for i in items)\n' "$i" "$i" > "src/orders_$i.py"
done

step install        "pip install -q uv && uv tool install $(ls -t /vm/dist/scubiee-*.whl | head -1)"
step setup          "scubiee setup"
tty_step init       "y\n" "cd $R && scubiee init ."
step edit_sync      "cd $R && printf '\n\ndef refund_penguin_voucher(order):\n    \"\"\"Issue a penguin voucher refund.\"\"\"\n    return order.total * 0.1\n' >> src/orders_2.py && scubiee sync ."
step search_edit    "cd $R && scubiee search 'refund_penguin_voucher penguin voucher refund' ."
step newfile_sync   "cd $R && printf 'def schedule_walrus_delivery(slot):\n    \"\"\"Book a walrus delivery slot.\"\"\"\n    return slot\n' > src/delivery.py && scubiee sync ."
step search_newfile "cd $R && scubiee search 'schedule_walrus_delivery walrus delivery slot' ."
tty_step tty_sync   "" "cd $R && printf '\n\ndef audit_otter_ledger():\n    return 1\n' >> src/orders_3.py && scubiee sync ."
step search_tty     "cd $R && scubiee search 'audit_otter_ledger otter ledger audit' ."
step noop_sync      "cd $R && scubiee sync ."
step engine_log     "grep -E 'keeper|hot' /root/.scubiee/engine.log | tail -40"
echo "== done"
