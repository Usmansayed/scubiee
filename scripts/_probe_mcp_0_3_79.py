"""One-shot Cursor-env MCP bridge probe for 0.3.79 attach warm."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(r"C:/Users/usman/Downloads/context-engine")
PYW = Path(r"C:/Users/usman/AppData/Roaming/uv/tools/scubiee/Scripts/pythonw.exe")
PY = Path(r"C:/Users/usman/AppData/Roaming/uv/tools/scubiee/Scripts/python.exe")


def main() -> int:
    mcp = json.loads((ROOT / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    entry = (mcp.get("mcpServers") or {}).get("scubiee") or {}
    env = os.environ.copy()
    env.update({str(k): str(v) for k, v in (entry.get("env") or {}).items()})
    env["CTX_MCP_ATTACH_WARM"] = "1"
    env["CTX_WARM_DEADLINE_MS"] = "10000"
    env["CTX_SCUBIEE_BUILD"] = "0.3.79-probe"
    env["CTX_REPO"] = str(ROOT).replace("\\", "/")
    env["CTX_PROJECT_ID"] = "ce_d20c8c9f855635cf43ea2440f0acd86d"
    env["CTX_MCP_CLIENT"] = "cursor"
    env["PYTHONUTF8"] = "1"

    ver = subprocess.check_output(
        [str(PY), "-c", "import importlib.metadata as m; print(m.version('scubiee'))"],
        text=True,
        env=env,
    ).strip()
    print("installed_via_tool_python:", ver)

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

    class Client:
        def __init__(self, p: subprocess.Popen[str]):
            self.p = p
            self.i = 0

        def req(self, method: str, params: dict[str, Any] | None = None, timeout: float = 120.0) -> dict[str, Any]:
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

        def tool(self, name: str, arguments: dict[str, Any], timeout: float = 180.0) -> Any:
            r = self.req("tools/call", {"name": name, "arguments": arguments}, timeout=timeout)
            content = r.get("content") if isinstance(r, dict) else None
            if isinstance(content, list) and content:
                text = content[0].get("text") if isinstance(content[0], dict) else None
                if isinstance(text, str):
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return {"raw": text[:2000]}
            return r

    c = Client(proc)
    t_boot = time.perf_counter()
    init = c.req(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "cursor-probe", "version": "0.3.79"},
        },
    )
    c.notify("notifications/initialized")
    print("initialize_server:", init.get("serverInfo") or {})
    print("boot_ms:", round((time.perf_counter() - t_boot) * 1000, 1))

    time.sleep(2.0)
    rows: list[dict[str, Any]] = []
    for i in range(10):
        t0 = time.perf_counter()
        st = c.tool("status", {}, timeout=60)
        wall = round((time.perf_counter() - t0) * 1000, 1)
        row = {
            "i": i,
            "wall_ms": wall,
            "warm_ready": st.get("warm_ready"),
            "warm_ready_map": st.get("warm_ready_map"),
            "warm_phase": st.get("warm_phase"),
            "warm_elapsed_ms": st.get("warm_elapsed_ms"),
            "embedder_loaded": st.get("embedder_loaded"),
            "agent_ready": st.get("agent_ready"),
            "warming": st.get("warming"),
            "ok": st.get("ok"),
            "error": st.get("error"),
        }
        rows.append(row)
        print("status", row)
        if st.get("warm_ready_map") or st.get("embedder_loaded"):
            break
        time.sleep(1.0)

    q = (
        "pipeline mcp_lifecycle start_attach_warm_pipeline warm_contract warm_ready "
        "mcp_bridge register_client pack_context map_context hydrate_ast_bundle "
        "ensure_embedder_ready DirectML prewarm join_attach_warm"
    )
    t0 = time.perf_counter()
    m1 = c.tool("map", {"query": q, "k": 12}, timeout=180)
    w1 = round((time.perf_counter() - t0) * 1000, 1)
    print(
        "map1",
        {
            "wall_ms": w1,
            "ok": m1.get("ok"),
            "warming": m1.get("warming"),
            "error": m1.get("error"),
            "elapsed_ms": m1.get("elapsed_ms"),
            "cache": m1.get("cache"),
            "top": ((m1.get("cards") or [{}])[0].get("file") if isinstance(m1.get("cards"), list) else None),
            "count": m1.get("count"),
        },
    )
    if m1.get("warming") or m1.get("error") == "engine_warming":
        time.sleep(float(m1.get("retry_after_s") or 3))
        t0 = time.perf_counter()
        m1 = c.tool("map", {"query": q, "k": 12}, timeout=180)
        w1 = round((time.perf_counter() - t0) * 1000, 1)
        print(
            "map1_retry",
            {
                "wall_ms": w1,
                "ok": m1.get("ok"),
                "warming": m1.get("warming"),
                "error": m1.get("error"),
                "elapsed_ms": m1.get("elapsed_ms"),
                "top": ((m1.get("cards") or [{}])[0].get("file") if isinstance(m1.get("cards"), list) else None),
            },
        )

    t0 = time.perf_counter()
    m2 = c.tool("map", {"query": q, "k": 12}, timeout=120)
    w2 = round((time.perf_counter() - t0) * 1000, 1)
    print(
        "map2_same_query",
        {
            "wall_ms": w2,
            "ok": m2.get("ok"),
            "elapsed_ms": m2.get("elapsed_ms"),
            "cache": m2.get("cache") or ((m2.get("timing") or {}).get("cache")),
            "cached": m2.get("cached"),
        },
    )

    out = ROOT / "docs" / "architecture" / "_mcp_0_3_79_probe.json"
    slim = {
        "version": ver,
        "status_polls": rows,
        "map1_summary": {
            "wall_ms": w1,
            "ok": m1.get("ok"),
            "elapsed_ms": m1.get("elapsed_ms"),
            "warming": m1.get("warming"),
            "error": m1.get("error"),
            "count": m1.get("count"),
            "top": ((m1.get("cards") or [{}])[0].get("file") if isinstance(m1.get("cards"), list) else None),
        },
        "map2_summary": {
            "wall_ms": w2,
            "ok": m2.get("ok"),
            "elapsed_ms": m2.get("elapsed_ms"),
            "cache": m2.get("cache") or ((m2.get("timing") or {}).get("cache")),
            "cached": m2.get("cached"),
        },
    }
    out.write_text(json.dumps(slim, indent=2), encoding="utf-8")
    print("wrote", out)

    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
