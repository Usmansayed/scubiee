"""Post-restart thorough SYNC battery against the live engine.

Covers: new-file add, modify, partial edit (content removed), delete (+ grep-gone),
rapid churn, and newcomer discovery via sync-now (BUG-1 path, must NOT be oversize).
Writes a JSON verdict so a shell timeout can't lose the result.

Design (lessons from prior sessions):
  - drive the hot lane via /v1/dirty then /v1/sync, with settle gaps (debounce 1000ms)
  - poll /v1/grep (rg-backed) for visibility with a bounded budget
  - use files under scripts/perf/_battery/ (a real indexed source root)
  - clean up every temp file at the end
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8765"
REPO = Path(__file__).resolve().parents[2]
STAMP = int(time.time())
WORK = REPO / "scripts" / "perf" / "_battery"
OUT = REPO / "scripts" / "perf" / f"_battery_result_{STAMP}.json"


def _post(path, body, timeout=60):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        return json.loads(r.read().decode())


def _get(path, timeout=30):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:  # noqa: S310
        return json.loads(r.read().decode())


def _rel(p: Path) -> str:
    return p.relative_to(REPO).as_posix()


def dirty_sync(rel: str, reason: str):
    _post("/v1/dirty", {"paths": [rel], "reason": reason, "path": str(REPO)})
    time.sleep(1.3)  # clear the 1000ms debounce
    return _post("/v1/sync", {"path": str(REPO)})


def grep_visible(token: str, budget_s: float = 45.0, want: bool = True) -> float | None:
    """Poll grep until token is present (want=True) or absent (want=False).
    Returns elapsed seconds when the condition is met, else None."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < budget_s:
        try:
            g = _post(
                "/v1/grep",
                {"pattern": token, "path": str(REPO), "glob": "scripts/perf/**/*.py", "max_hits": 5},
            )
            present = bool(g.get("hits"))
            if present == want:
                return time.perf_counter() - t0
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.0)
    return None


def main() -> int:
    res: dict = {"stamp": STAMP, "cases": {}}
    WORK.mkdir(parents=True, exist_ok=True)
    h0 = _get("/health")
    res["health_start"] = {k: h0.get(k) for k in ("version", "chunks", "generation", "warm")}

    created: list[Path] = []
    try:
        # ---- CASE 3: new file add -> searchable ----
        tok_new = f"BATTERY_NEW_{STAMP}"
        f_new = WORK / f"new_{STAMP}.py"
        f_new.write_text(f"def {tok_new.lower()}():\n    return {tok_new!r}\n", encoding="utf-8")
        created.append(f_new)
        s = dirty_sync(_rel(f_new), "battery_new")
        vis = grep_visible(tok_new)
        res["cases"]["new_file"] = {
            "sync_strategy": s.get("strategy"),
            "sync_error": s.get("error"),
            "visible_s": round(vis, 1) if vis is not None else None,
            "pass": vis is not None and not s.get("error"),
        }

        # ---- CASE 4: modify existing file -> new content in, old gone ----
        tok_old = f"BATTERY_OLD_{STAMP}"
        tok_mod = f"BATTERY_MOD_{STAMP}"
        f_mod = WORK / f"mod_{STAMP}.py"
        f_mod.write_text(f"def {tok_old.lower()}():\n    return {tok_old!r}\n", encoding="utf-8")
        created.append(f_mod)
        dirty_sync(_rel(f_mod), "battery_mod_init")
        grep_visible(tok_old)
        # now rewrite it
        f_mod.write_text(f"def {tok_mod.lower()}():\n    return {tok_mod!r}\n", encoding="utf-8")
        dirty_sync(_rel(f_mod), "battery_mod_edit")
        new_vis = grep_visible(tok_mod)
        old_gone = grep_visible(tok_old, budget_s=30.0, want=False)
        res["cases"]["modify"] = {
            "new_visible_s": round(new_vis, 1) if new_vis is not None else None,
            "old_gone_s": round(old_gone, 1) if old_gone is not None else None,
            "pass": new_vis is not None and old_gone is not None,
        }

        # ---- CASE 5a: partial edit (remove part of a file) ----
        tok_keep = f"BATTERY_KEEP_{STAMP}"
        tok_drop = f"BATTERY_DROP_{STAMP}"
        f_part = WORK / f"part_{STAMP}.py"
        f_part.write_text(
            f"def {tok_keep.lower()}():\n    return {tok_keep!r}\n\n"
            f"def {tok_drop.lower()}():\n    return {tok_drop!r}\n",
            encoding="utf-8",
        )
        created.append(f_part)
        dirty_sync(_rel(f_part), "battery_part_init")
        grep_visible(tok_drop)
        # remove the drop function
        f_part.write_text(
            f"def {tok_keep.lower()}():\n    return {tok_keep!r}\n", encoding="utf-8"
        )
        dirty_sync(_rel(f_part), "battery_part_edit")
        drop_gone = grep_visible(tok_drop, budget_s=30.0, want=False)
        keep_still = grep_visible(tok_keep, budget_s=10.0, want=True)
        res["cases"]["partial_edit"] = {
            "dropped_gone_s": round(drop_gone, 1) if drop_gone is not None else None,
            "kept_still_visible": keep_still is not None,
            "pass": drop_gone is not None and keep_still is not None,
        }

        # ---- CASE 5b: delete file -> grep-gone ----
        tok_del = f"BATTERY_DEL_{STAMP}"
        f_del = WORK / f"del_{STAMP}.py"
        f_del.write_text(f"def {tok_del.lower()}():\n    return {tok_del!r}\n", encoding="utf-8")
        dirty_sync(_rel(f_del), "battery_del_init")
        grep_visible(tok_del)
        rel_del = _rel(f_del)
        f_del.unlink()
        dirty_sync(rel_del, "battery_del_remove")
        del_gone = grep_visible(tok_del, budget_s=30.0, want=False)
        res["cases"]["delete"] = {
            "deleted_gone_s": round(del_gone, 1) if del_gone is not None else None,
            "pass": del_gone is not None,
        }

        # ---- CASE 6: rapid churn + sync-now newcomer discovery (BUG-1) ----
        churn_tokens = []
        for i in range(5):
            t = f"BATTERY_CHURN_{STAMP}_{i}"
            fc = WORK / f"churn_{STAMP}_{i}.py"
            fc.write_text(f"def {t.lower()}():\n    return {t!r}\n", encoding="utf-8")
            created.append(fc)
            churn_tokens.append((t, _rel(fc)))
            _post("/v1/dirty", {"paths": [_rel(fc)], "reason": "battery_churn", "path": str(REPO)})
        time.sleep(1.3)
        churn_sync = _post("/v1/sync", {"path": str(REPO)})
        # settle, then confirm all churn files visible
        time.sleep(2.0)
        churn_vis = sum(1 for t, _ in churn_tokens if grep_visible(t, budget_s=20.0) is not None)
        res["cases"]["rapid_churn"] = {
            "sync_strategy": churn_sync.get("strategy"),
            "sync_error": churn_sync.get("error"),
            "files": len(churn_tokens),
            "visible": churn_vis,
            "pass": churn_vis == len(churn_tokens) and not churn_sync.get("error"),
        }

        h1 = _get("/health")
        res["health_end"] = {k: h1.get(k) for k in ("version", "chunks", "generation", "warm")}
    finally:
        # cleanup
        for p in created:
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass
        # dirty the deletions so the index drops them
        for p in created:
            try:
                _post("/v1/dirty", {"paths": [_rel(p)], "reason": "battery_cleanup", "path": str(REPO)})
            except Exception:  # noqa: BLE001
                pass
        try:
            if WORK.exists() and not any(WORK.iterdir()):
                WORK.rmdir()
        except OSError:
            pass
        OUT.write_text(json.dumps(res, indent=2), encoding="utf-8")
        print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
