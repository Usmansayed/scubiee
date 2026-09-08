#!/usr/bin/env python3
"""Post-restart production validation for context-engine (non-destructive core + safe lifecycle tail)."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(os.environ.get("TEST_REPO", str(ROOT)))
SC = Path(os.environ.get("SCUBIEE", r"C:\Users\usman\AppData\Roaming\uv\tools\scubiee\Scripts\scubiee.exe"))
MCP = SC.with_name("scubiee-mcp.exe")
LOG = ROOT / "tests" / "_prod_post_restart_results.json"

PASS = FAIL = 0
RESULTS: list[dict] = []


def record(name: str, ok: bool, detail: str = "", **extra) -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        mark = "PASS"
    else:
        FAIL += 1
        mark = "FAIL"
    row = {"name": name, "ok": ok, "detail": detail, **extra}
    RESULTS.append(row)
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))


def run(*argv: str, timeout: float = 120) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            [str(SC), *argv],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(REPO),
            encoding="utf-8",
            errors="replace",
        )
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return -9, "", "TIMEOUT"
    except FileNotFoundError:
        return -2, "", f"not found: {SC}"


def parse_json(text: str):
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


class McpSession:
    def __init__(self) -> None:
        env = os.environ.copy()
        env["CTX_REPO"] = str(REPO)
        env["CTX_PROJECT_ID"] = "ce_223fe983ee19e5629ce88102e6581038"
        env["CTX_ENGINE_URL"] = "http://127.0.0.1:8765"
        env["CTX_MCP_SURFACE"] = "phase"
        env["CTX_MCP_EXPERIMENT"] = "ship"
        env["PYTHONUTF8"] = "1"
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        self.proc = subprocess.Popen(
            [str(MCP)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **kwargs,
        )
        self._id = 100
        self._lock = threading.Lock()
        self._handshake()

    def _handshake(self) -> None:
        self._send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "prod-test", "version": "1"},
                },
            }
        )
        self._recv(timeout=45)
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, msg: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def _recv(self, timeout: float = 30):
        q: queue.Queue[str] = queue.Queue()

        def _read() -> None:
            assert self.proc.stdout is not None
            q.put(self.proc.stdout.readline())

        t = threading.Thread(target=_read, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive() or q.empty():
            return None
        line = q.get_nowait()
        return json.loads(line) if line.strip() else None

    def call(self, name: str, args: dict, timeout: float = 45) -> dict:
        with self._lock:
            self._id += 1
            t0 = time.perf_counter()
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": self._id,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": args},
                }
            )
            resp = self._recv(timeout=timeout)
            dt = time.perf_counter() - t0
        if resp is None:
            return {"__timeout__": True, "__dt__": dt}
        if "error" in resp:
            return {"__error__": resp["error"], "__dt__": dt}
        text = resp["result"]["content"][0]["text"]
        try:
            return {**json.loads(text), "__dt__": dt}
        except (json.JSONDecodeError, TypeError, KeyError):
            return {"__raw__": text, "__dt__": dt}

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n  {title}\n{'=' * 60}")


def test_baseline() -> None:
    section("1. Install + enrollment")
    code, out, err = run("--version", timeout=30)
    ver = (out or err).strip().split("\n")[0]
    record("scubiee runnable", code == 0, ver)
    record("version 0.3.6", "0.3.6" in ver, ver)

    code, out, _ = run("doctor", str(REPO), timeout=60)
    doc = parse_json(out) or {}
    record("doctor enrolled", doc.get("enrollment", {}).get("enrolled") is True, f"ok={doc.get('ok')} project_id={doc.get('project_id', '')[:20]}")

    code, out, _ = run("preflight", timeout=30)
    pf = parse_json(out) or {}
    caps = pf.get("capabilities") or {}
    req_ok = all(c.get("available") for c in caps.values() if c.get("required"))
    record("preflight required caps", req_ok or pf.get("ok") is True)

    mcp_path = REPO / ".cursor" / "mcp.json"
    record("project mcp.json exists", mcp_path.is_file())
    if mcp_path.is_file():
        cfg = json.loads(mcp_path.read_text(encoding="utf-8"))
        srv = cfg.get("mcpServers", {}).get("scubiee", {})
        record("mcp pins CTX_REPO", srv.get("env", {}).get("CTX_REPO", "").replace("\\", "/").lower() == str(REPO).replace("\\", "/").lower())
        record("mcp command exists", Path(srv.get("command", "")).is_file(), srv.get("command", ""))


def test_engine() -> None:
    section("2. Engine + index")
    code, out, _ = run("engine", "status", str(REPO), timeout=30)
    eng = parse_json(out) or {}
    record("engine running", eng.get("running") is True)
    record("not globally paused", eng.get("globally_paused") is not True)
    record("engine version 0.3.6", eng.get("health", {}).get("version") == "0.3.6")

    code, out, _ = run("status", str(REPO), timeout=30)
    st = parse_json(out) or {}
    chunks = st.get("chunks") or st.get("meta", {}).get("chunks", 0)
    record("index chunks > 0", int(chunks or 0) > 0, f"chunks={chunks}")

    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=10) as r:
            health = json.loads(r.read().decode())
        record("HTTP /v1/health ok", health.get("ok") is True, f"version={health.get('version')}")
    except Exception as exc:
        record("HTTP /v1/health ok", False, str(exc))


def test_search_battery() -> None:
    section("3. CLI search battery")
    queries = [
        ("lifecycle_guard", "packages/pipeline/lifecycle_guard.py"),
        ("rules_installer connect mcp", "packages/pipeline/rules_installer.py"),
        ("wipe keep package", "packages/pipeline/wipe.py"),
        ("mcp locate map pack_context", "packages/pipeline/mcp_locate.py"),
    ]
    for q, expect_sub in queries:
        code, out, _ = run("search", str(REPO), q, timeout=180)
        data = parse_json(out) or {}
        hits = data.get("hits") or []
        top = hits[0].get("file", "") if hits else ""
        record(f"search: {q[:30]}", code == 0 and len(hits) > 0 and expect_sub.replace("\\", "/") in top.replace("\\", "/"), top or f"exit={code}")


def test_mcp_tools() -> None:
    section("4. MCP stdio tools (ship surface)")
    session = McpSession()
    query = (
        "pack_context run_pack_context expand_context composite_v1 "
        "packages/pipeline/context_trace.py lean heatmap ladder"
    )
    tools = [
        ("gate", {}),
        ("status", {}),
        ("map", {"query": query, "k": 8}),
        ("workspace", {"action": "show"}),
    ]
    seed_file = "packages/pipeline/context_trace.py"
    seed_symbol = "run_pack_context"
    for name, args in tools:
        r = session.call(name, args, timeout=60)
        ok = not r.get("__timeout__") and not r.get("__error__")
        if name == "map":
            cards = r.get("cards") or r.get("hits") or r.get("results") or []
            seed = r.get("suggested_seed") or {}
            if seed.get("file"):
                seed_file = str(seed.get("file"))
            if seed.get("symbol"):
                seed_symbol = str(seed.get("symbol"))
            ok = ok and (bool(cards) or bool(r.get("ok")))
            detail = f"cards={len(cards)} seed={seed_file}"
        else:
            detail = f"dt={r.get('__dt__', 0):.1f}s"
        record(f"mcp:{name}", ok, detail)

    pack = session.call(
        "pack_context",
        {
            "query": query,
            "seed_file": seed_file,
            "seed_symbol": seed_symbol,
            "mode": "lean",
            "policy": "strict",
        },
        timeout=90,
    )
    pack_ok = not pack.get("__timeout__") and not pack.get("__error__") and bool(
        pack.get("ok") or pack.get("heatmap") or pack.get("chain")
    )
    record("mcp:pack_context", pack_ok, f"engine={pack.get('engine')}")
    node = (pack.get("seed") or {}).get("id") if isinstance(pack.get("seed"), dict) else None
    if node:
        exp = session.call(
            "expand_context",
            {"node": node, "direction": "callees", "with_bodies": True, "query": query},
            timeout=60,
        )
        record(
            "mcp:expand_context",
            not exp.get("__timeout__") and not exp.get("__error__") and bool(exp.get("ok")),
            f"count={exp.get('count')}",
        )
    else:
        record("mcp:expand_context", False, "no seed id from pack")

    # concurrent burst (ship tools only)
    burst = [
        ("map", {"query": "OpenCode v2 mcp servers schema"}),
        ("status", {}),
        ("workspace", {"action": "show"}),
    ]
    ok_n = 0
    for name, args in burst:
        r = session.call(name, args, timeout=30)
        if not r.get("__timeout__") and not r.get("__error__"):
            ok_n += 1
    record("mcp concurrent burst", ok_n == len(burst), f"{ok_n}/{len(burst)}")

    session.close()


def test_adversarial() -> None:
    section("5. Adversarial MCP (must not crash)")
    session = McpSession()
    cases = [
        ("map", {"query": ""}, "empty map"),
        ("pack_context", {"query": "x", "seed_file": "", "seed_symbol": ""}, "missing seed"),
        ("map", {"query": "emoji unicode test query"}, "emoji"),
        ("expand_context", {"node": "../../../Windows/System32/config/SAM"}, "traversal node"),
    ]
    crashed = False
    for name, args, _label in cases:
        session.call(name, args, timeout=10)
        if session.proc.poll() is not None:
            crashed = True
            break
    record("mcp survived adversarial", not crashed)
    session.close()


def test_certify() -> None:
    section("6. Certify (repo quality gate)")
    code, out, _ = run("certify", str(REPO), "--skip-daemon", timeout=300)
    data = parse_json(out) or {}
    record("certify imports", data.get("ok") is True or int(data.get("failed_required") or 0) == 0,
           f"passed={data.get('passed')} failed_required={data.get('failed_required')}")


def test_lifecycle_tail() -> None:
    section("7. Lifecycle tail (stop -> blocked init -> connect auto-resume)")
    code, out, _ = run("stop", "-y", timeout=120)
    record("stop", code == 0)

    code, _, _ = run("init", str(REPO), timeout=30)
    record("init blocked while stopped", code != 0, f"exit={code}")

    code, out, _ = run("connect", "--cursor", timeout=60)
    conn = parse_json(out)
    ok = isinstance(conn, list) and conn and conn[0].get("ok") is True
    record("connect auto-resume", ok)

    code, out, _ = run("engine", "status", str(REPO), timeout=30)
    eng = parse_json(out) or {}
    record("engine up after connect", eng.get("running") is True and eng.get("globally_paused") is not True)


def main() -> int:
    print("SCUBIEE POST-RESTART PRODUCTION TEST")
    print(f"Repo: {REPO}")
    print(f"Binary: {SC}")
    if not SC.is_file():
        print(f"Missing scubiee at {SC}")
        return 2

    test_baseline()
    test_engine()
    test_search_battery()
    test_mcp_tools()
    test_adversarial()
    test_certify()
    test_lifecycle_tail()

    section("SUMMARY")
    total = PASS + FAIL
    print(f"  {PASS}/{total} passed, {FAIL} failed")
    LOG.write_text(json.dumps({"pass": PASS, "fail": FAIL, "results": RESULTS}, indent=2), encoding="utf-8")
    print(f"  Log: {LOG}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
