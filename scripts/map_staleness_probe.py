"""Issue 1: does ``map`` show an edit once the engine has published it?

Spawns the real MCP bridge the way Cursor does (``.cursor/mcp.json``,
PYTHONPATH stripped, so the uv-tool install runs) and, per run:

    map(Q)  -> append a function to a scratch file
            -> poll /health until ``generation`` moves
            -> map(Q) again: the new function must be in the cards within 1s
            -> map(Q) once more with no change: must be a cache hit

Each run's function carries freshly generated nonsense words and Q is built
from them, so no other chunk in the repo (this script included) can match Q
and before the edit no card can show it. A bump that does not carry our edit
(another publish) is recognised with a direct ``/v1/search`` and the probe
keeps waiting. When the engine search already has the edit but map does not,
map is serving a stale cache: that run fails.

Usage (installed engine on :8765, PYTHONPATH unset):
    python scripts/map_staleness_probe.py [runs] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from attach_pack_race import PID, _client  # noqa: E402

BASE = "http://127.0.0.1:8765"
PKG = ROOT / "packages" / "pipeline"
FRESH_SLA_MS = 1000.0
# Generous: a graph catch-up on the keeper can hold the edit's publish for
# 20-50s (issue 6). This probe measures map freshness after the bump.
BUMP_DEADLINE_S = 120.0
STALE_DEADLINE_S = 12.0
# Hot patches leave BM25 one generation behind (engine._patch_chunk_delta), so
# a fresh chunk ranks on dense only until the next full publish. The query must
# therefore be a sentence dense retrieval can match; the combination is drawn
# per run, so no chunk (this file included) contains it before the edit.
_VERB = ("calibrate", "polish", "harvest", "stack", "repaint", "weigh", "rotate", "fold", "sort", "inflate")
_ADJ = ("amber", "frosted", "crooked", "velvet", "hollow", "striped", "brass", "mossy", "tidal", "woolen")
_NOUN = ("lanterns", "kayaks", "violins", "pumpkins", "anchors", "teapots", "saddles", "kites", "barrels", "helmets")


def _post(path: str, body: dict, timeout: float = 60.0) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": repr(exc)}


def _health() -> dict:
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": repr(exc)}


def _touch() -> None:
    _post("/v1/client/touch", {"client_id": "mcp:map-staleness-probe", "kind": "mcp", "pid": os.getpid()}, 5.0)


def _words() -> list[str]:
    """A sentence no chunk contains until this run writes it."""
    return [
        random.choice(_VERB), "the", random.choice(_ADJ), random.choice(_NOUN),
        "beside", "the", random.choice(_ADJ), random.choice(_NOUN),
    ]


def _fn(token: str, words: list[str]) -> str:
    phrase = " ".join(words)
    return (
        f"\n\ndef {token}_handler(payload):\n"
        f'    """{phrase}."""\n'
        f'    return {{"token": "{token}", "words": "{phrase}", "payload": payload}}\n'
    )


def _query(token: str, words: list[str]) -> str:
    return f"{' '.join(words)} {token}_handler payload"


def _shows_edit(items: list, rel: str, token: str, new_start: int) -> bool:
    """A hit/card reflects the edit: it names the token or covers the appended lines.

    Small functions share one chunk and ``why`` is a 200-char preview, so the
    token can sit past the preview. Only a post-edit index has a chunk of
    ``rel`` that reaches past the old end of the file.
    """
    for h in items or []:
        if str(h.get("file") or "").replace("\\", "/") != rel:
            continue
        end = int(h.get("end_line") or 0)
        loc = str(h.get("loc") or "")  # lean map cards: "file:start-end"
        if not end and "-" in loc:
            try:
                end = int(loc.rsplit("-", 1)[1])
            except ValueError:
                end = 0
        if token in json.dumps(h) or end >= new_start:
            return True
    return False


def _engine_has(query: str, rel: str, token: str, new_start: int = 10**9) -> bool:
    """Ground truth: the published binder already returns the new function.

    top_k=8 mirrors map (tool_search_code clamps to 8).
    """
    s = _post("/v1/search", {"query": query, "top_k": 8, "path": str(ROOT)})
    return _shows_edit(s.get("hits") or [], rel, token, new_start)


def _card_has(resp: dict, token: str, rel: str, new_start: int) -> bool:
    return _shows_edit(resp.get("cards") or [], rel, token, new_start)


def _cache_tag(resp: dict) -> str:
    if resp.get("cache"):
        return str(resp["cache"])
    if resp.get("cached"):
        return "session"
    # Lean map responses drop the cache flag on older builds; a process-cache
    # hit is the only path that zeroes both embed and retrieve time.
    t = resp.get("timings") or {}
    if resp.get("ok") and t.get("embed_ms") == 0.0 and t.get("retrieve_ms") == 0.0:
        return "hit(inferred)"
    if resp.get("ok") and not t:
        return "session(inferred)"
    return "miss"


def _map(c, query: str) -> tuple[dict, float]:
    """One map through the bridge; retries while dense is still loading."""
    deadline = time.perf_counter() + 90.0
    while True:
        t0 = time.perf_counter()
        resp = c.call("map", query=query, k=10, project_id=PID)
        ms = round((time.perf_counter() - t0) * 1000, 1)
        if resp.get("ok") or time.perf_counter() > deadline:
            return resp, ms
        if not (resp.get("should_retry") or resp.get("warming") or "loading" in str(resp.get("error"))):
            return resp, ms
        time.sleep(float(resp.get("retry_after_s") or 2.0))


def run_once(c, idx: int, scratch: Path, rel: str) -> dict:
    token = f"zzmapstale{int(time.time())}r{idx}"
    words = _words()
    query = _query(token, words)
    row: dict = {"run": idx, "token": token, "words": " ".join(words)}
    first, ms = _map(c, query)
    row["map_before_ms"] = ms
    row["map_before_cache"] = _cache_tag(first)
    row["map_before_ok"] = bool(first.get("ok"))
    if not first.get("ok"):
        row["error"] = first.get("error")
        row["ok"] = False
        return row
    if _card_has(first, token, rel, 10**9):
        row["error"] = "token visible before the edit"
        row["ok"] = False
        return row
    h0 = _health()
    g0 = int(h0.get("generation") or 0)
    pid0 = h0.get("pid")
    # The appended def starts two blank lines past the current end of file.
    new_start = len(scratch.read_text(encoding="utf-8").splitlines()) + 3
    t_edit = time.perf_counter()
    with scratch.open("a", encoding="utf-8") as fh:
        fh.write(_fn(token, words))
    g_prev = g0
    found = False
    stale_since: float | None = None
    bumps: list[int] = []
    while time.perf_counter() - t_edit < BUMP_DEADLINE_S:
        _touch()
        g = int(_health().get("generation") or 0)
        if g != g_prev:
            t_bump = time.perf_counter()
            g_prev = g
            bumps.append(g)
            row["bump_at"] = time.strftime("%H:%M:%S")
            resp, ms = _map(c, query)
            if _card_has(resp, token, rel, new_start):
                row.update(
                    edit_to_bump_ms=round((t_bump - t_edit) * 1000),
                    fresh_ms=round((time.perf_counter() - t_bump) * 1000, 1),
                    fresh_map_ms=ms,
                    fresh_cache=_cache_tag(resp),
                )
                found = True
                break
            if _engine_has(query, rel, token, new_start):
                # The engine serves the edit; map does not. Keep asking to
                # measure how long the stale answer survives.
                stale_since = t_bump
                row["edit_to_bump_ms"] = round((t_bump - t_edit) * 1000)
                row["stale_cache"] = _cache_tag(resp)
                row["stale_map_ms"] = ms
                while time.perf_counter() - stale_since < STALE_DEADLINE_S:
                    time.sleep(0.25)
                    resp, ms = _map(c, query)
                    if _card_has(resp, token, rel, new_start):
                        row["fresh_ms"] = round((time.perf_counter() - stale_since) * 1000, 1)
                        row["fresh_cache"] = _cache_tag(resp)
                        found = True
                        break
                break
        time.sleep(0.1)
    row["generations"] = [g0, *bumps]
    row["found"] = found
    if stale_since is not None and not found:
        row["stale_for_s"] = f">{STALE_DEADLINE_S:.0f}"
    if found:
        again, ms = _map(c, query)
        row["repeat_ms"] = ms
        row["repeat_server_ms"] = again.get("elapsed_ms")
        row["repeat_cache"] = _cache_tag(again)
        row["repeat_has_token"] = _card_has(again, token, rel, new_start)
    row["same_pid"] = _health().get("pid") == pid0
    row["ok"] = bool(
        found
        and float(row.get("fresh_ms") or 1e9) <= FRESH_SLA_MS
        and str(row.get("repeat_cache") or "miss") != "miss"
        and row.get("repeat_has_token")
        and row["same_pid"]
    )
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="?", type=int, default=5)
    ap.add_argument("--json", default="")
    ap.add_argument("--bridge-log", default="", help="Append the bridge/worker stderr here.")
    args = ap.parse_args()
    for leftover in PKG.glob("zz_mapstale_*.py"):
        leftover.unlink(missing_ok=True)
    stamp = str(int(time.time()))
    scratch = PKG / f"zz_mapstale_{stamp}.py"
    rel = f"packages/pipeline/{scratch.name}"
    rows: list[dict] = []
    h0 = _health()
    print(f"engine pid={h0.get('pid')} generation={h0.get('generation')} version={h0.get('version')}", flush=True)
    try:
        client = _client("mapstale")
        client.stderr_path = args.bridge_log or None
        with client as c:
            c.call_text("gate", project_id=PID)
            base, base_words = f"zzmapbase{stamp}", _words()
            scratch.write_text('"""Map staleness probe scratch module."""\n' + _fn(base, base_words), encoding="utf-8")
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < BUMP_DEADLINE_S and not _engine_has(
                _query(base, base_words), rel, base
            ):
                _touch()
                time.sleep(0.5)
            print(f"scratch indexed in {round((time.perf_counter() - t0) * 1000)} ms", flush=True)
            time.sleep(2.0)
            for i in range(args.runs):
                row = run_once(c, i, scratch, rel)
                rows.append(row)
                print(json.dumps(row), flush=True)
                time.sleep(1.5)
    finally:
        scratch.unlink(missing_ok=True)
    ok = sum(1 for r in rows if r.get("ok"))
    print(f"\nSUMMARY {ok}/{len(rows)} fresh within {FRESH_SLA_MS:.0f}ms of the generation bump, repeat = cache hit")
    for r in rows:
        print(
            f"  run {r['run']}: edit->bump {r.get('edit_to_bump_ms')} ms  fresh {r.get('fresh_ms')} ms "
            f"(cache={r.get('fresh_cache', r.get('stale_cache'))})  repeat {r.get('repeat_ms')} ms "
            f"server {r.get('repeat_server_ms')} ms cache={r.get('repeat_cache')}  "
            f"same_pid={r.get('same_pid')} ok={r.get('ok')}"
        )
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0 if ok == len(rows) and rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
