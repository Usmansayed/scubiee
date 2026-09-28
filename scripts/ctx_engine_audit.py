"""Deep audit of the Scubiee context engine through the real MCP bridge.

Beyond mcp_experiment.py: cross-tool consistency, cache invalidation after an
edit, map/pack corpus agreement, session isolation, argument edge cases, and
malformed inputs. Prints findings (FINDING: lines) plus a per-call log.

    python scripts/ctx_engine_audit.py [--json out.json]
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from mcp_stdio_client import McpStdioClient  # noqa: E402

PID = "ce_3536ac8e8e83bb8e4d888db37847729c"
REPO = str(ROOT).replace("\\", "/")
ROWS: list[dict] = []
FINDINGS: list[str] = []


def _client(session: str | None = None) -> McpStdioClient:
    cfg = json.loads((ROOT / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    e = cfg["mcpServers"]["scubiee"]
    env = {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"}
    env.update(e.get("env") or {})
    env.pop("PYTHONPATH", None)
    if session:
        env["CTX_MCP_SESSION_ID"] = session
    c = McpStdioClient(e["command"], e.get("args", []))
    c.env = env
    return c


def call(c, label, tool, **a):
    t0 = time.perf_counter()
    try:
        text = c.call_text(tool, **a)
        ms = round((time.perf_counter() - t0) * 1000, 1)
        try:
            o = json.loads(text)
        except json.JSONDecodeError:
            o = {"_text": text}
    except Exception as exc:  # noqa: BLE001
        ms = round((time.perf_counter() - t0) * 1000, 1)
        o = {"_error": repr(exc)}
    ROWS.append({"label": label, "tool": tool, "ms": ms, "args": a, "obj": o})
    print(f"[{ms:8.1f}ms] {label}", flush=True)
    return o


def finding(msg: str) -> None:
    FINDINGS.append(msg)
    print("  FINDING: " + msg, flush=True)


def warm(c):
    call(c, "gate", "gate", project_id=PID)
    for _ in range(30):
        s = call(c, "status warm-poll", "status", project_id=PID, detail="full")
        if s.get("embedder_loaded") or (s.get("warm_wait") or {}).get("done"):
            return s
        time.sleep(4)
    return {}


def seed_line(seed):
    loc = (seed or {}).get("loc") or ""
    m = re.search(r":(\d+)", loc)
    return int(m.group(1)) if m else 0


def main() -> int:
    print(f"repo={REPO}\n", flush=True)
    with _client() as c:
        s = warm(c)

        # 1) status shape: warm_deadline vs configured deadline (OBS-1 recheck)
        wd = s.get("warm_deadline_ms")
        cfg_deadline = os.environ.get("CTX_WARM_DEADLINE_MS")
        if wd is not None and cfg_deadline and str(wd) != str(cfg_deadline):
            finding(f"status.warm_deadline_ms={wd} != configured CTX_WARM_DEADLINE_MS={cfg_deadline} (OBS-1)")

        # 2) map on several queries; check every card loc is inside the file
        q1 = ("graph catch-up child process graph_merge_worker start_graph_merge commit "
              "keeper rename graph.json build_merge dedup export")
        m = call(c, "map A", "map", query=q1, project_id=PID, path=REPO)
        cards = m.get("cards") or []
        for card in cards:
            loc = card.get("loc") or ""
            mm = re.search(r":(\d+)-(\d+)$", loc)
            f = (loc.split(":")[0] if loc else "")
            if mm and f:
                fp = ROOT / f
                if fp.is_file():
                    n = sum(1 for _ in fp.open(encoding="utf-8", errors="ignore"))
                    if int(mm.group(2)) > n + 1:
                        finding(f"map card loc past EOF: {loc} but {f} has {n} lines")

        # 3) map suggested_seed -> pack MUST resolve it (corpus agreement)
        seeds = m.get("suggested_seeds") or []
        for sd in seeds[:2]:
            ln = seed_line(sd)
            p = call(c, f"pack seed {sd.get('symbol')}", "pack_context", query=q1,
                     project_id=PID, path=REPO, mode="lean",
                     seed_file=sd["file"], seed_symbol=sd.get("symbol") or "", seed_line=ln)
            if not p.get("ok"):
                finding(f"map suggested seed {sd['file']}::{sd.get('symbol')} but pack: {p.get('error')} "
                        "(map/pack corpus disagreement)")

        # 4) cache: repeat map -> should be a hit; edit -> next map must be fresh
        m2 = call(c, "map A repeat", "map", query=q1, project_id=PID, path=REPO)
        if m2.get("cache") not in ("hit", "last", "session"):
            finding(f"repeat map did not report a cache hit (cache={m2.get('cache')})")
        probe = ROOT / "packages" / "pipeline" / "zz_audit_cache_probe.py"
        tok = f"zzauditcache{int(time.time())}"
        try:
            probe.write_text(f'def {tok}_handler():\n    """{tok}"""\n    return 1\n', encoding="utf-8")
            gen0 = (call(c, "status pre-edit", "status", project_id=PID, detail="full")).get("generation")
            fresh_ok = False
            t0 = time.time()
            while time.time() - t0 < 40:
                mm = call(c, "map after edit", "map",
                          query=f"{tok}_handler audit cache probe function", project_id=PID, path=REPO)
                if any(tok in json.dumps(cd) for cd in (mm.get("cards") or [])):
                    fresh_ok = True
                    break
                time.sleep(3)
            if not fresh_ok:
                finding(f"map never returned the freshly-saved {tok}_handler within 40s "
                        f"(gen was {gen0}) — stale after edit or slow catch-up")
        finally:
            probe.unlink(missing_ok=True)

        # 5) argument edge cases
        call(c, "map missing query", "map", project_id=PID, path=REPO)
        call(c, "map empty query", "map", query="", project_id=PID, path=REPO)
        call(c, "map huge k", "map", query="engine warm contract", project_id=PID, path=REPO, k=9999)
        call(c, "map no path", "map", query="engine warm contract", project_id=PID)
        call(c, "pack missing query", "pack_context", seed_file="packages/pipeline/server.py",
             project_id=PID, path=REPO)
        call(c, "expand_context bad node", "expand_context", node="does/not/exist.py::nope",
             project_id=PID, path=REPO, query="x")
        call(c, "expand_context bad direction", "expand_context",
             node="packages/pipeline/server.py::EngineHTTPServer", direction="sideways",
             project_id=PID, path=REPO, query="x")
        call(c, "workspace bad action", "workspace", action="frobnicate", project_id=PID, path=REPO)
        call(c, "gate wrong project", "gate", project_id="ce_deadbeef")
        call(c, "status no project", "status", detail="full")

        # 6) workspace pin persistence + clear
        call(c, "workspace pin", "workspace", action="pin",
             path="packages/pipeline/fast_stat.py", project_id=PID)
        ws = call(c, "workspace show", "workspace", action="show", project_id=PID, path=REPO)
        if not (ws.get("pins") or []):
            finding("workspace pin did not appear in show")
        cl = call(c, "workspace clear", "workspace", action="clear", project_id=PID, path=REPO)
        ws2 = call(c, "workspace show after clear", "workspace", action="show", project_id=PID, path=REPO)
        if (ws2.get("pins") or []) and cl.get("ok"):
            finding("workspace clear did not drop pins")

    # 7) session isolation: a pin in session A must not leak into session B
    with _client(session="auditA") as ca:
        warm(ca)
        call(ca, "A pin", "workspace", action="pin", path="packages/pipeline/engine.py", project_id=PID)
        a_show = call(ca, "A show", "workspace", action="show", project_id=PID, path=REPO)
    with _client(session="auditB") as cb:
        warm(cb)
        b_show = call(cb, "B show", "workspace", action="show", project_id=PID, path=REPO)
        a_pins = {p.get("path") if isinstance(p, dict) else p for p in (a_show.get("pins") or [])}
        b_pins = {p.get("path") if isinstance(p, dict) else p for p in (b_show.get("pins") or [])}
        if a_pins and a_pins & b_pins:
            finding(f"session isolation leak: pins {a_pins & b_pins} visible in session B")

    print("\n\n=== FINDINGS ===", flush=True)
    if not FINDINGS:
        print("  (none)", flush=True)
    for f in FINDINGS:
        print("  - " + f, flush=True)
    if "--json" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--json") + 1])
        out.write_text(json.dumps({"rows": ROWS, "findings": FINDINGS}, indent=2, default=str), encoding="utf-8")
        print(f"\nwrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
