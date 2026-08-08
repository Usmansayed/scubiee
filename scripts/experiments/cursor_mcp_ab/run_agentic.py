"""Cursor-side (no OpenCode) A/B: D_search-only vs R_plan+nav.

Measures wall time, tool calls, and *agent-useful* payload chars
(hits + span text only — strips keeper/timings bloat).

Usage:
  .\\.venv\\Scripts\\python.exe -u scripts\\experiments\\cursor_mcp_ab\\run_agentic.py
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "out" / "experiments" / "cursor_mcp_ab"
REPO = ROOT / "testdata" / "frontend-mcp"
SOAK_S = float(os.environ.get("CURSOR_AB_SOAK_S", "300"))  # ~5 min default

MISSION = [
    {
        "id": "T1",
        "query": "agent guidance browser session vanished unreachable what to do",
        "must_touch": ["agent_guidance.py"],
        "ident": "attach_guidance",
    },
    {
        "id": "T2",
        "query": "MCP tool callable binding registry executor dispatch",
        "must_touch": ["dispatch_registry.py"],
        "ident": "DispatchRegistry",
    },
    {
        "id": "T3",
        "query": "browser session lease queue perception tools share browser",
        "must_touch": ["browser_session_manager.py"],
        "ident": "BrowserSessionManager",
    },
]


def _client():
    from pipeline.client import EngineClient

    return EngineClient()


def _restart(mode: str) -> None:
    from pipeline.daemon import force_restart_daemon
    from pipeline.client import EngineClient

    os.environ["CTX_RETRIEVE"] = mode
    force_restart_daemon(REPO)
    c = EngineClient()
    opened = c.open_repo(str(REPO), wait=True)
    print({"mode": mode, "open": opened.get("ok"), "warm": opened.get("warm_state")})


def _useful_chars(obj: Any) -> int:
    """Count only what an agent would keep in context (not keeper/timings)."""
    if not isinstance(obj, dict):
        return len(json.dumps(obj, default=str))
    parts: list[str] = []
    for h in obj.get("hits") or []:
        if isinstance(h, dict):
            parts.append(str(h.get("path") or ""))
            parts.append(str(h.get("why") or ""))
            parts.append(str(h.get("preview") or h.get("text") or "")[:400])
    for s in obj.get("spans") or []:
        if isinstance(s, dict):
            parts.append(str(s.get("path") or ""))
            parts.append(str(s.get("text") or "")[:800])
    span = obj.get("span")
    if isinstance(span, dict):
        parts.append(str(span.get("path") or ""))
        parts.append(str(span.get("text") or "")[:800])
    if obj.get("hint"):
        parts.append(str(obj["hint"]))
    # fallback if empty structured payload
    if not parts:
        slim = {k: obj[k] for k in ("ok", "query", "ident", "from", "seeds") if k in obj}
        return len(json.dumps(slim, default=str))
    return sum(len(p) for p in parts)


def _score(paths: list[str], must: list[str]) -> bool:
    blob = " ".join(paths).replace("\\", "/").lower()
    return all(m.lower() in blob for m in must)


def arm_d_only(c) -> dict[str, Any]:
    tools = 0
    chars = 0
    turns = []
    t0 = time.perf_counter()
    for m in MISSION:
        r = c.search(m["query"], top_k=8, path=str(REPO))
        tools += 1
        uc = _useful_chars(r)
        chars += uc
        paths = [str(h.get("path") or "") for h in (r.get("hits") or [])]
        turns.append(
            {
                "id": m["id"],
                "ok": _score(paths, m["must_touch"]),
                "paths": paths[:5],
                "useful_chars": uc,
                "raw_chars": len(json.dumps(r, default=str)),
                "retrieve_mode": (r.get("timings") or {}).get("retrieve_mode"),
            }
        )
        print(f"  D {m['id']} ok={turns[-1]['ok']} mode={turns[-1]['retrieve_mode']} top={paths[:3]}")
    return {
        "arm": "d_search_only",
        "tools": tools,
        "chars": chars,
        "wall_ms": round((time.perf_counter() - t0) * 1000, 1),
        "rubric_pass": sum(1 for t in turns if t["ok"]),
        "rubric_total": len(turns),
        "turns": turns,
    }


def arm_nav(c) -> dict[str, Any]:
    tools = 0
    chars = 0
    turns = []
    t0 = time.perf_counter()
    known: list[str] = []

    def call(_name: str, fn, **kw):
        nonlocal tools, chars
        out = fn(**kw)
        tools += 1
        chars += _useful_chars(out)
        return out

    for m in MISSION:
        paths_seen: list[str] = []
        r = call("search", c.search, query=m["query"], top_k=6, path=str(REPO))
        hits = r.get("hits") or []
        for h in hits[:4]:
            p = str(h.get("path") or "")
            if p:
                paths_seen.append(p)

        seed = None
        for need in m["must_touch"]:
            for p in paths_seen:
                if need.lower() in p.replace("\\", "/").lower():
                    seed = p
                    break
            if seed:
                break

        # Class/def locate if search missed the must-touch file
        if not seed:
            g = call(
                "grep_ident",
                c.grep_ident,
                ident=m["ident"],
                keep=4,
                max_chars=500,
                path=str(REPO),
            )
            for s in g.get("spans") or []:
                p = str(s.get("path") or "")
                if p:
                    paths_seen.append(p)
                    if any(need.lower() in p.replace("\\", "/").lower() for need in m["must_touch"]):
                        seed = p
                        break
            if not seed and paths_seen:
                seed = paths_seen[0]

        if seed:
            hit0 = next((h for h in hits if str(h.get("path")) == seed), {}) or {}
            sl = int(hit0.get("start_line") or 1)
            el = int(hit0.get("end_line") or 0) or (sl + 40)
            call(
                "read_span",
                c.read_span,
                file_path=seed,
                start_line=sl,
                end_line=el,
                max_chars=700,
                repo=str(REPO),
            )
            paths_seen.append(seed)
            neigh = call(
                "graph_neighbors",
                c.graph_neighbors,
                paths=[seed],
                query=m["query"],
                keep=3,
                cap=12,
                max_chars=400,
                repo=str(REPO),
            )
            for s in neigh.get("spans") or []:
                p = str(s.get("path") or "")
                if p:
                    paths_seen.append(p)
            fi = call(
                "follow_imports",
                c.follow_imports,
                file_path=seed,
                query=m["query"],
                keep=4,
                max_chars=400,
                repo=str(REPO),
            )
            for s in fi.get("spans") or []:
                p = str(s.get("path") or "")
                if p:
                    paths_seen.append(p)
            known.append(seed)

        ok = _score(paths_seen, m["must_touch"])
        turns.append(
            {
                "id": m["id"],
                "ok": ok,
                "paths": list(dict.fromkeys(paths_seen))[:8],
                "retrieve_mode": (r.get("timings") or {}).get("retrieve_mode"),
            }
        )
        print(f"  NAV {m['id']} ok={ok} seed={seed} paths={turns[-1]['paths'][:4]}")

    if known:
        call(
            "reopen_anchors",
            c.reopen_anchors,
            prefer=[Path(p).stem for p in known[:3]],
            max_files=3,
            max_chars=400,
            path=str(REPO),
        )
        call("session_anchors", c.session_anchors, path=str(REPO))

    wiring_q = "how agent_guidance connects to browser_session_manager and dispatch_registry"
    r = call("search", c.search, query=wiring_q, top_k=8, path=str(REPO))
    for h in (r.get("hits") or [])[:3]:
        p = str(h.get("path") or "")
        if not p:
            continue
        call(
            "read_span",
            c.read_span,
            file_path=p,
            start_line=int(h.get("start_line") or 1),
            end_line=int(h.get("end_line") or 40),
            max_chars=500,
            repo=str(REPO),
        )
        call(
            "follow_imports",
            c.follow_imports,
            file_path=p,
            query=wiring_q,
            keep=3,
            max_chars=350,
            repo=str(REPO),
        )

    return {
        "arm": "ce_nav",
        "tools": tools,
        "chars": chars,
        "wall_ms": round((time.perf_counter() - t0) * 1000, 1),
        "rubric_pass": sum(1 for t in turns if t["ok"]),
        "rubric_total": len(turns),
        "turns": turns,
    }


def soak(c, seconds: float) -> dict[str, Any]:
    """Paced CE traffic to stretch wall clock; metrics kept separate from winner chars."""
    print(f"=== soak (~{int(seconds)}s paced probes) ===")
    t0 = time.perf_counter()
    tools = 0
    chars = 0
    queries = [
        "vanished unreachable browser session agent guidance",
        "DispatchRegistry handlers tool name callable",
        "BrowserSessionManager acquire release lease",
        "attach_guidance degraded error envelope",
        "perception tools share one chromium lock",
    ]
    i = 0
    while time.perf_counter() - t0 < seconds:
        q = queries[i % len(queries)]
        i += 1
        r = c.search(q, top_k=4, path=str(REPO))
        tools += 1
        chars += _useful_chars(r)
        hits = r.get("hits") or []
        if hits:
            h = hits[0]
            p = str(h.get("path") or "")
            if p:
                s = c.read_span(
                    file_path=p,
                    start_line=int(h.get("start_line") or 1),
                    end_line=int(h.get("end_line") or 25),
                    max_chars=350,
                    repo=str(REPO),
                )
                tools += 1
                chars += _useful_chars(s)
        # ~1 probe pair / 2.5s → ~120 tools over 5 min, not thousands
        time.sleep(2.5)
        if i % 10 == 0:
            print(f"  soak {i} tools={tools} elapsed={time.perf_counter()-t0:.0f}s")
    return {"tools": tools, "chars": chars, "wall_s": round(time.perf_counter() - t0, 1)}


def main() -> int:
    os.environ.pop("CTX_HOME", None)
    os.environ.pop("CTX_ENGINE_URL", None)
    os.environ["PYTHONPATH"] = str(ROOT / "packages")
    OUT.mkdir(parents=True, exist_ok=True)
    t_all = time.perf_counter()

    print("=== arm D (CTX_RETRIEVE=D) ===")
    _restart("D")
    c = _client()
    d = arm_d_only(c)

    print("=== arm NAV (CTX_RETRIEVE=R_plan + nav tools) ===")
    _restart("R_plan")
    c = _client()
    n = arm_nav(c)

    soak_stats = soak(c, SOAK_S)

    wall = time.perf_counter() - t_all
    # Winner by mission useful-chars (soak excluded)
    pool = [x for x in (d, n) if x["rubric_pass"] >= 2] or [d, n]
    winner = sorted(pool, key=lambda x: x["chars"])[0]["arm"]
    report = {
        "title": "Cursor (no OpenCode) CE A/B — D vs nav",
        "repo": str(REPO),
        "wall_s": round(wall, 1),
        "primary_metric": "useful_chars (hits+spans; no keeper/timings)",
        "arms": [d, n],
        "soak": soak_stats,
        "winner": winner,
        "savings_vs_d": {
            "chars_d": d["chars"],
            "chars_nav": n["chars"],
            "delta": d["chars"] - n["chars"],
            "pct": round(100 * (d["chars"] - n["chars"]) / max(d["chars"], 1), 1),
        },
        "note": "Live Cursor MCP multi-hop also exercised in-session (search→span→nav).",
    }
    out = OUT / f"report_{int(time.time())}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "report_latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\n=== RESULT ===")
    print(json.dumps({k: report[k] for k in ("wall_s", "winner", "savings_vs_d", "soak")}, indent=2))
    for a in (d, n):
        print(
            a["arm"],
            f"pass={a['rubric_pass']}/{a['rubric_total']}",
            f"tools={a['tools']}",
            f"useful_chars={a['chars']}",
            f"wall_ms={a['wall_ms']}",
        )
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
