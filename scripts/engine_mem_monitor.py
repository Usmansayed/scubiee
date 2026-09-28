"""Every 2s append engine pid/generation/RSS/private bytes and system free RAM as JSONL.

Usage: python scripts/engine_mem_monitor.py <out.jsonl>   (run in the background; Ctrl+C to stop)
A pid change or a run of health_err rows is an engine death/restart.
"""
import json
import sys
import time
import urllib.request

import psutil

out = open(sys.argv[1], "a", encoding="utf-8")
while True:
    row = {"t": time.strftime("%H:%M:%S"), "avail_mb": int(psutil.virtual_memory().available / 2**20)}
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=5) as r:
            h = json.loads(r.read().decode())
        pid = int(h.get("pid") or 0)
        row.update(pid=pid, gen=h.get("generation"), chunks=h.get("chunks"))
        try:
            p = psutil.Process(pid)
            mi = p.memory_info()
            row.update(rss_mb=int(mi.rss / 2**20), private_mb=int(getattr(mi, "private", 0) / 2**20))
        except Exception as exc:  # noqa: BLE001
            row["proc_err"] = repr(exc)
    except Exception as exc:  # noqa: BLE001
        row["health_err"] = type(exc).__name__
    out.write(json.dumps(row) + "\n")
    out.flush()
    time.sleep(2)
