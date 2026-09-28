"""Real-editor path: plain disk writes, no /v1/dirty. Times until search reflects each change.

Nothing in Cursor/Kiro/Copilot calls /v1/dirty, so this is how real saves reach
the engine: the keeper's 1s disk poll. Each round: new file, a second save to
the same file, a new ~1600-line file, an edit to it, a new file in a new folder,
a delete, and a revert. Only the round's first step waits for an idle keeper.

Usage (installed engine running on :8765, PYTHONPATH unset):
    python scripts/disk_save_probe.py <repo> [rounds]
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(sys.argv[1]).resolve()
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
BASE = "http://127.0.0.1:8765"
SLA_S = 5.0
DEADLINE_S = 60.0


def post(path, body, timeout=60.0):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": repr(exc)}


def get(path, timeout=30.0):
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": repr(exc)}


def touch():
    post("/v1/client/touch", {"client_id": "mcp:disk-save-probe", "kind": "mcp", "pid": os.getpid()})


def busy():
    s = post("/v1/status", {"path": str(REPO)})
    keeper = s.get("keeper") or s.get("sync_status") or {}
    paths = ((keeper.get("dirty") or {}).get("paths")) or (((s.get("sync") or {}).get("dirty") or {}).get("paths")) or {}
    return [p for p, e in paths.items() if str((e or {}).get("state")) in {"queued", "due", "processing"}]


def idle(timeout=120):
    end = time.time() + timeout
    quiet = 0
    while time.time() < end:
        touch()
        if not busy():
            quiet += 1
            if quiet >= 2:
                return True
        else:
            quiet = 0
        time.sleep(1.5)
    return False


def hits(query):
    s = post("/v1/search", {"query": query, "top_k": 10, "path": str(REPO)})
    return s.get("hits") or []


def has(query, rel=None, token=None):
    for h in hits(query):
        f = str(h.get("file") or "").replace("\\", "/")
        if rel and f != rel:
            continue
        if token and token not in json.dumps(h):
            continue
        return True
    return False


def wait(pred):
    t0 = time.perf_counter()
    pid0 = get("/health").get("pid")
    while time.perf_counter() - t0 < DEADLINE_S:
        if pred():
            ms = (time.perf_counter() - t0) * 1000
            return round(ms), get("/health").get("pid") == pid0
        touch()
        time.sleep(0.2)
    return None, get("/health").get("pid") == pid0


def src(token):
    return f'"""Disk save probe."""\n\n\ndef {token}_handler(payload):\n    """Unique probe symbol {token}."""\n    return {{"token": "{token}", "payload": payload}}\n'


def main():
    results = []
    # A throwaway copy of a large real module: never edit tracked source, so a
    # killed run cannot leave junk in it or clobber someone's concurrent edits.
    big_source = (REPO / "packages" / "pipeline" / "sync_loop.py").read_bytes()
    try:
        for rnd in range(ROUNDS):
            stamp = f"{int(time.time())}{rnd}"
            t_new = f"zzdsnew{stamp}"
            t_edit = f"zzdsedit{stamp}"
            t_base = f"zzdsbase{stamp}"
            t_big = f"zzdsbig{stamp}"
            t_sub = f"zzdssub{stamp}"
            rel_new = f"packages/pipeline/zz_disksave_{stamp}.py"
            rel_big = f"packages/pipeline/zz_dsbig_{stamp}.py"
            big = REPO / rel_big
            original = big_source + f"\n\ndef {t_base}_handler(payload):\n    \"\"\"Unique probe symbol {t_base}.\"\"\"\n    return payload\n".encode()
            sub_dir = f"packages/pipeline/zz_dsdir_{stamp}"
            rel_sub = f"{sub_dir}/mod_{stamp}.py"

            def step(name, action, pred):
                # Agents edit back to back; only the round's first save lands on an idle keeper.
                if name == "new_file" and not idle():
                    print(f"  [{name}] keeper never went idle: {busy()[:3]}")
                time.sleep(1.0)
                action()
                ms, same_pid = wait(pred)
                ok = ms is not None and ms <= SLA_S * 1000 and same_pid
                results.append({"round": rnd, "step": name, "ms": ms, "same_pid": same_pid, "ok": ok})
                print(f"round {rnd} {name:<12} {ms if ms is not None else 'TIMEOUT':>7} ms  same_pid={same_pid}  ok={ok}", flush=True)

            step("new_file", lambda: (REPO / rel_new).write_text(src(t_new), encoding="utf-8"),
                 lambda: has(f"{t_new}_handler disk save probe", rel=rel_new))
            step("edit_small", lambda: (REPO / rel_new).write_text(src(t_new) + "\n\n" + src(t_edit).split("\n", 3)[3], encoding="utf-8"),
                 lambda: has(f"{t_edit}_handler disk save probe", rel=rel_new, token=t_edit))
            step("new_big", lambda: big.write_bytes(original),
                 lambda: has(f"{t_base}_handler unique probe symbol", rel=rel_big, token=t_base))
            step("edit_big", lambda: big.write_bytes(original + f"\n\ndef {t_big}_handler(payload):\n    \"\"\"Unique probe symbol {t_big}.\"\"\"\n    return payload\n".encode()),
                 lambda: has(f"{t_big}_handler unique probe symbol", rel=rel_big, token=t_big))
            step("new_subdir", lambda: ((REPO / sub_dir).mkdir(), (REPO / rel_sub).write_text(src(t_sub), encoding="utf-8")),
                 lambda: has(f"{t_sub}_handler disk save probe", rel=rel_sub))
            step("delete", lambda: (REPO / rel_new).unlink(),
                 lambda: not has(f"{t_new}_handler disk save probe", rel=rel_new) and not has(f"{t_edit}_handler disk save probe", rel=rel_new))
            step("restore_big", lambda: big.write_bytes(original),
                 lambda: not has(f"{t_big}_handler unique probe symbol", rel=rel_big, token=t_big))
            shutil.rmtree(REPO / sub_dir, ignore_errors=True)
            big.unlink(missing_ok=True)
    finally:
        for pattern in ("zz_disksave_*.py", "zz_dsbig_*.py"):
            for p in (REPO / "packages" / "pipeline").glob(pattern):
                p.unlink(missing_ok=True)
        for p in (REPO / "packages" / "pipeline").glob("zz_dsdir_*"):
            shutil.rmtree(p, ignore_errors=True)
    ok = sum(r["ok"] for r in results)
    print(f"\nSUMMARY {ok}/{len(results)} within {SLA_S:.0f}s")
    by = {}
    for r in results:
        by.setdefault(r["step"], []).append(r["ms"])
    for k, v in by.items():
        print(f"  {k:<12} {v}")
    print(json.dumps(results))
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
