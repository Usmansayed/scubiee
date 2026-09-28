"""Full MCP reliability probe: status → map → pack → idle → map2 → pack2."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(r"C:/Users/usman/Downloads/context-engine")
PYW = Path(r"C:/Users/usman/AppData/Roaming/uv/tools/scubiee/Scripts/pythonw.exe")
OUT = ROOT / "docs" / "architecture" / "_mcp_reliability_full_probe.json"

QUERY = (
    "pipeline mcp_lifecycle start_attach_warm_pipeline warm_contract warm_ready "
    "mcp_bridge register_client pack_context map_context hydrate_ast_bundle "
    "ensure_embedder_ready DirectML prewarm join_attach_warm composite_v1"
)


def _parse_tool(result: dict[str, Any]) -> dict[str, Any]:
    content = result.get("content") if isinstance(result, dict) else None
    if isinstance(content, list) and content:
        text = content[0].get("text") if isinstance(content[0], dict) else None
        if isinstance(text, str):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw": text[:3000]}
    return result if isinstance(result, dict) else {"raw": result}


class Client:
    def __init__(self, proc: subprocess.Popen[str]):
        self.p = proc
        self.i = 0

    def req(self, method: str, params: dict[str, Any] | None = None, timeout: float = 180.0) -> dict[str, Any]:
        self.i += 1
        mid = self.i
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": mid, "method": method}
        if params is not None:
            msg["params"] = params
        assert self.p.stdin and self.p.stdout
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = self.p.stdout.readline()
            if not raw:
                if self.p.poll() is not None:
                    err = self.p.stderr.read() if self.p.stderr else ""
                    raise RuntimeError(f"exited {self.p.returncode}: {err[-2000:]}")
                continue
            raw = raw.strip()
            if not raw:
                continue
            try:
                m = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if m.get("id") != mid:
                continue
            if "error" in m:
                raise RuntimeError(json.dumps(m["error"]))
            return m.get("result") or {}
        raise TimeoutError(method)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        assert self.p.stdin
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def tool(self, name: str, arguments: dict[str, Any], timeout: float = 180.0) -> dict[str, Any]:
        return _parse_tool(self.req("tools/call", {"name": name, "arguments": arguments}, timeout=timeout))


def main() -> int:
    mcp = json.loads((ROOT / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    entry = (mcp.get("mcpServers") or {}).get("scubiee") or {}
    env = os.environ.copy()
    env.update({str(k): str(v) for k, v in (entry.get("env") or {}).items()})
    env["CTX_MCP_ATTACH_WARM"] = "1"
    env["CTX_WARM_DEADLINE_MS"] = "10000"
    env["CTX_REPO"] = str(ROOT).replace("\\", "/")
    env["CTX_PROJECT_ID"] = "ce_d20c8c9f855635cf43ea2440f0acd86d"
    env["CTX_MCP_CLIENT"] = "cursor"
    env["CTX_ENGINE_IDLE_S"] = "3600"
    env["PYTHONUTF8"] = "1"

    proc = subprocess.Popen(
        [str(PYW), "-u", "-m", "pipeline.mcp_bridge"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
        env=env,
    )
    c = Client(proc)
    report: dict[str, Any] = {"checks": []}

    def check(name: str, ok: bool, detail: Any = None) -> None:
        report["checks"].append({"check": name, "ok": bool(ok), "detail": detail})
        print(("PASS" if ok else "FAIL"), name, detail if detail is not None else "")

    try:
        t0 = time.perf_counter()
        init = c.req(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "reliability-probe", "version": "0.3.79"},
            },
        )
        c.notify("notifications/initialized")
        boot_ms = round((time.perf_counter() - t0) * 1000, 1)
        ver = (init.get("serverInfo") or {}).get("version")
        check("initialize", bool(ver) and str(ver).startswith("0.3."), {"version": ver, "boot_ms": boot_ms})

        # Poll until warm_ready_map or 15s
        st = {}
        ready_ms = None
        t_ready = time.perf_counter()
        for i in range(20):
            t1 = time.perf_counter()
            st = c.tool("status", {"detail": "summary", "project_id": env["CTX_PROJECT_ID"]}, timeout=60)
            wall = round((time.perf_counter() - t1) * 1000, 1)
            print(
                "status",
                {
                    "i": i,
                    "wall_ms": wall,
                    "warm_ready_map": st.get("warm_ready_map"),
                    "embedder_loaded": st.get("embedder_loaded"),
                    "agent_ready": st.get("agent_ready"),
                    "warming": st.get("warming"),
                    "error": st.get("error") or (st.get("engine") or {}).get("warm_error"),
                },
            )
            if st.get("warm_ready_map") and st.get("embedder_loaded"):
                ready_ms = round((time.perf_counter() - t_ready) * 1000, 1)
                break
            if st.get("ok") and not st.get("warming") and st.get("embedder_loaded"):
                ready_ms = round((time.perf_counter() - t_ready) * 1000, 1)
                break
            time.sleep(0.75)
        check(
            "warm_ready_within_15s",
            ready_ms is not None and ready_ms <= 15000,
            {"ready_ms": ready_ms, "warm_ready_map": st.get("warm_ready_map"), "embedder_loaded": st.get("embedder_loaded")},
        )

        def map_once(label: str) -> tuple[dict[str, Any], float]:
            t1 = time.perf_counter()
            m = c.tool(
                "map",
                {"query": QUERY, "k": 12, "project_id": env["CTX_PROJECT_ID"]},
                timeout=180,
            )
            if m.get("warming") or m.get("error") == "engine_warming":
                time.sleep(float(m.get("retry_after_s") or 3))
                t1 = time.perf_counter()
                m = c.tool(
                    "map",
                    {"query": QUERY, "k": 12, "project_id": env["CTX_PROJECT_ID"]},
                    timeout=180,
                )
            wall = round((time.perf_counter() - t1) * 1000, 1)
            print(label, {"wall_ms": wall, "ok": m.get("ok"), "elapsed_ms": m.get("elapsed_ms"), "error": m.get("error"), "top": ((m.get("cards") or [{}])[0].get("file") if isinstance(m.get("cards"), list) and m.get("cards") else None)})
            return m, wall

        m1, w1 = map_once("map1")
        check("map1_ok", bool(m1.get("ok")) and not m1.get("warming"), {"wall_ms": w1, "elapsed_ms": m1.get("elapsed_ms")})

        seed = m1.get("suggested_seed") or {}
        seeds = m1.get("suggested_seeds") or ([seed] if seed else [])
        pack_args: dict[str, Any] = {
            "query": QUERY + " " + " ".join(
                f"{s.get('file')}::{s.get('symbol')}" for s in seeds[:3] if isinstance(s, dict)
            ),
            "mode": "lean",
            "project_id": env["CTX_PROJECT_ID"],
        }
        if isinstance(seed, dict) and seed.get("file"):
            pack_args["seed_file"] = seed.get("file")
            pack_args["seed_symbol"] = seed.get("symbol") or ""
        if len(seeds) > 1 and isinstance(seeds[1], dict) and seeds[1].get("file"):
            pack_args["seed2_file"] = seeds[1].get("file")
            pack_args["seed2_symbol"] = seeds[1].get("symbol") or ""

        t1 = time.perf_counter()
        p1 = c.tool("pack_context", pack_args, timeout=180)
        pw1 = round((time.perf_counter() - t1) * 1000, 1)
        print("pack1", {"wall_ms": pw1, "ok": p1.get("ok"), "elapsed_ms": p1.get("elapsed_ms"), "thin": p1.get("thin"), "error": p1.get("error")})
        check("pack1_ok", bool(p1.get("ok")), {"wall_ms": pw1, "elapsed_ms": p1.get("elapsed_ms"), "thin": p1.get("thin")})

        print("idle 5s (client still connected)...")
        time.sleep(5.0)
        m2, w2 = map_once("map2_after_idle")
        check(
            "map2_steady_ms",
            bool(m2.get("ok")) and w2 <= 2000,
            {"wall_ms": w2, "elapsed_ms": m2.get("elapsed_ms"), "cache": m2.get("cache") or m2.get("cached")},
        )

        t1 = time.perf_counter()
        p2 = c.tool("pack_context", pack_args, timeout=180)
        pw2 = round((time.perf_counter() - t1) * 1000, 1)
        print("pack2", {"wall_ms": pw2, "ok": p2.get("ok"), "elapsed_ms": p2.get("elapsed_ms"), "thin": p2.get("thin")})
        check("pack2_steady", bool(p2.get("ok")) and pw2 <= 8000, {"wall_ms": pw2, "elapsed_ms": p2.get("elapsed_ms")})

    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    failed = [c for c in report["checks"] if not c["ok"]]
    report["failed"] = len(failed)
    report["passed"] = sum(1 for c in report["checks"] if c["ok"])
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("wrote", OUT)
    print(f"SUMMARY passed={report['passed']} failed={report['failed']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
