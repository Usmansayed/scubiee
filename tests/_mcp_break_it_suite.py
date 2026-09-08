#!/usr/bin/env python3
"""Adversarial / multi-agent MCP break-it suite (stdio JSON-RPC).

Simulates multiple Cursor agents hammering Scubiee MCP concurrently,
plus lifecycle chaos, malformed RPC, and CLI+MCP races.

Run:
  python tests/_mcp_break_it_suite.py

Logs: tests/_mcp_break_it_results.json
"""
from __future__ import annotations

import json
import os
import queue
import random
import string
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(os.environ.get("TEST_REPO", str(ROOT)))
SC = Path(
    os.environ.get(
        "SCUBIEE",
        r"C:\Users\usman\AppData\Roaming\uv\tools\scubiee\Scripts\scubiee.exe",
    )
)
MCP_BIN = SC.with_name("scubiee-mcp.exe")
PROJECT_ID = "ce_223fe983ee19e5629ce88102e6581038"
LOG_PATH = ROOT / "tests" / "_mcp_break_it_results.json"

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


@dataclass
class Case:
    name: str
    ok: bool
    ms: float
    detail: str = ""
    bugs: list[str] = field(default_factory=list)


RESULTS: list[Case] = []


def record(name: str, ok: bool, ms: float, detail: str = "", bugs: list[str] | None = None) -> None:
    RESULTS.append(Case(name, ok, ms, detail, bugs or []))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name} ({ms:.0f}ms) {detail}")


def health() -> dict:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=8) as r:
            return json.loads(r.read().decode())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def cli(*argv: str, timeout: float = 120) -> tuple[int, str]:
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
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -9, "TIMEOUT"
    except FileNotFoundError:
        return -2, f"missing {SC}"


class AgentSession:
    """One simulated Cursor agent MCP connection."""

    def __init__(self, agent_id: str, *, repo: str | None = None, extra_env: dict | None = None):
        self.agent_id = agent_id
        env = os.environ.copy()
        env.update(
            {
                "CTX_REPO": repo or str(REPO),
                "CTX_PROJECT_ID": PROJECT_ID,
                "CTX_ENGINE_URL": "http://127.0.0.1:8765",
                "CTX_MCP_SURFACE": "phase",
                "CTX_MCP_EXPERIMENT": "ship",
                "CTX_MCP_SESSION_ISOLATE": "1",
                "CTX_MCP_CLIENT": f"break-it-{agent_id}",
                "PYTHONUTF8": "1",
            }
        )
        if extra_env:
            env.update(extra_env)
        self.proc = subprocess.Popen(
            [str(MCP_BIN)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            creationflags=CREATE_NO_WINDOW,
        )
        self._rid = 0
        self._lock = threading.Lock()
        self._alive = True
        self._handshake()

    def _send(self, msg: dict) -> None:
        if not self.proc.stdin:
            raise RuntimeError("stdin closed")
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def _recv_line(self, timeout: float = 90) -> str | None:
        q: queue.Queue[str | None] = queue.Queue()

        def _read() -> None:
            try:
                assert self.proc.stdout is not None
                q.put(self.proc.stdout.readline())
            except Exception:  # noqa: BLE001
                q.put(None)

        t = threading.Thread(target=_read, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive() or q.empty():
            return None
        return q.get()

    def _handshake(self) -> None:
        self._send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": self.agent_id, "version": "1"},
                },
            }
        )
        line = self._recv_line(45)
        if not line:
            raise RuntimeError(f"{self.agent_id}: initialize timeout")
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        time.sleep(0.15)

    def call(self, tool: str, args: dict | None = None, *, timeout: float = 90) -> dict:
        with self._lock:
            self._rid += 1
            rid = self._rid
            t0 = time.perf_counter()
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "method": "tools/call",
                    "params": {"name": tool, "arguments": args or {}},
                }
            )
            line = self._recv_line(timeout)
            dt = time.perf_counter() - t0
        if line is None:
            return {"__timeout__": True, "__dt__": dt, "agent": self.agent_id}
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return {"__bad_json__": line[:200], "__dt__": dt, "agent": self.agent_id}
        if "error" in data:
            return {"__rpc_error__": data["error"], "__dt__": dt, "agent": self.agent_id}
        try:
            text = data["result"]["content"][0]["text"]
            body = json.loads(text)
            body["__dt__"] = dt
            body["__agent__"] = self.agent_id
            return body
        except (KeyError, IndexError, json.JSONDecodeError):
            return {"__parse_error__": True, "__raw__": str(data)[:300], "__dt__": dt}

    def send_raw(self, msg: dict) -> None:
        with self._lock:
            self._send(msg)

    def alive(self) -> bool:
        return self._alive and self.proc.poll() is None

    def close(self) -> None:
        self._alive = False
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass


def _map_ok(r: dict) -> bool:
    if r.get("__timeout__") or r.get("__rpc_error__") or r.get("error"):
        return False
    if r.get("ok") is False:
        return bool(r.get("should_retry"))
    return int(r.get("count") or 0) > 0 or bool(r.get("cards"))


def test_multi_agent_parallel_map() -> None:
    """6 independent MCP processes = 6 Cursor agents, 8 maps each."""
    t0 = time.perf_counter()
    agents = [AgentSession(f"agent-{i}") for i in range(6)]
    queries = [
        "lifecycle guard global stop init blocked",
        "rules_installer connect disconnect mcp merge",
        "wipe keep package tool shims",
        "daemon ensure_daemon open_repo bind",
        "mcp_locate map focus phase surface",
        "session store dedup expand workspace",
        "incremental sync dirty journal keeper",
        "hardware track fs_id moved folder",
    ]
    bugs: list[str] = []
    ok_count = 0
    total = 0
    crashes = 0

    def worker(agent_idx: int, q_idx: int) -> bool:
        nonlocal ok_count, total, crashes
        total += 1
        a = agents[agent_idx]
        if not a.alive():
            crashes += 1
            return False
        r = a.call("map", {"query": queries[q_idx % len(queries)]}, timeout=120)
        if not a.alive():
            crashes += 1
            bugs.append(f"agent-{agent_idx} crashed during map")
            return False
        if _map_ok(r):
            ok_count += 1
            return True
        if r.get("error") not in (None, "") and r.get("should_retry"):
            time.sleep(0.4)
            r2 = a.call("map", {"query": queries[q_idx % len(queries)]}, timeout=120)
            if _map_ok(r2):
                ok_count += 1
                return True
        bugs.append(f"agent-{agent_idx} map fail: {r.get('error', r.keys())}")
        return False

    try:
        with ThreadPoolExecutor(max_workers=12) as pool:
            futs = [
                pool.submit(worker, i % 6, j)
                for j in range(8)
                for i in range(6)
            ]
            list(as_completed(futs))
        record(
            "multi_agent_48x_map",
            crashes == 0 and ok_count >= total * 0.85,
            (time.perf_counter() - t0) * 1000,
            f"ok={ok_count}/{total} crashes={crashes}",
            bugs[:5],
        )
    finally:
        for a in agents:
            a.close()


def test_cross_tool_storm() -> None:
    """Single agent rapid mixed ship tool calls (map+pack+status+workspace)."""
    t0 = time.perf_counter()
    a = AgentSession("storm-1")
    ops = [
        ("status", {}),
        ("map", {"query": "pause resume lifecycle runtime"}),
        ("workspace", {"action": "show"}),
        ("gate", {}),
        ("map", {"query": "pack_context expand_context heatmap"}),
        ("status", {}),
        ("workspace", {"action": "show"}),
        ("gate", {}),
    ] * 3
    fails = 0
    bugs: list[str] = []
    try:
        for i, (tool, args) in enumerate(ops):
            r = a.call(tool, args, timeout=90)
            if not a.alive():
                bugs.append(f"crashed at op {i} {tool}")
                break
            if tool == "map":
                good = _map_ok(r) or r.get("should_retry")
            else:
                good = r.get("ok") is not False and not r.get("__timeout__") and not r.get("__rpc_error__")
            if not good:
                fails += 1
                if len(bugs) < 5:
                    bugs.append(f"{tool}@{i}: {r.get('error', 'bad')}")
        record(
            "cross_tool_storm_24ops",
            a.alive() and fails <= 2,
            (time.perf_counter() - t0) * 1000,
            f"fails={fails}/{len(ops)} alive={a.alive()}",
            bugs,
        )
    finally:
        a.close()


def test_cli_mcp_race() -> None:
    """CLI search/index while 4 MCP agents hammer map/status."""
    t0 = time.perf_counter()
    agents = [AgentSession(f"race-{i}") for i in range(4)]
    bugs: list[str] = []
    stop = threading.Event()

    def mcp_loop(agent: AgentSession) -> None:
        n = 0
        while not stop.is_set() and n < 6:
            tool = random.choice(["map", "status", "workspace"])
            if tool == "map":
                r = agent.call("map", {"query": f"pipeline daemon race {n}"}, timeout=60)
                if not _map_ok(r) and not r.get("should_retry") and r.get("error"):
                    bugs.append(f"{agent.agent_id} map: {r.get('error')}")
            elif tool == "workspace":
                agent.call("workspace", {"action": "show"}, timeout=30)
            else:
                agent.call("status", {}, timeout=30)
            n += 1

    def cli_loop() -> None:
        for q in ("lifecycle_guard", "wipe", "mcp_locate", "daemon ensure"):
            code, out = cli("search", str(REPO), q, timeout=120)
            if code not in (0, 1) and "hits" not in out:
                bugs.append(f"cli search exit={code}")

    try:
        threads = [threading.Thread(target=mcp_loop, args=(a,), daemon=True) for a in agents]
        threads.append(threading.Thread(target=cli_loop, daemon=True))
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=180)
        stop.set()
        crashes = sum(1 for a in agents if not a.alive())
        h = health()
        record(
            "cli_mcp_race",
            crashes == 0 and h.get("ok") is True,
            (time.perf_counter() - t0) * 1000,
            f"crashes={crashes} engine_ok={h.get('ok')} warm={h.get('warm')}",
            bugs[:5],
        )
    finally:
        stop.set()
        for a in agents:
            a.close()


def test_wrong_repo_agent() -> None:
    """Agent pinned to non-repo path must fail soft, not crash server."""
    t0 = time.perf_counter()
    fake = str(Path(os.environ.get("TEMP", "/tmp")) / "scubiee-not-a-repo-xyz")
    bugs: list[str] = []
    try:
        a = AgentSession("wrong-repo", repo=fake)
        r = a.call("map", {"query": "anything"}, timeout=30)
        r2 = a.call("grep", {"pattern": "x", "glob": "*.py"}, timeout=30)
        crashed = not a.alive()
        # Expect graceful errors, not crash
        soft = crashed is False and (
            r.get("ok") is False or r.get("error") or r.get("__rpc_error__") or r.get("hint")
        )
        if crashed:
            bugs.append("wrong-repo agent crashed MCP process")
        record(
            "wrong_repo_soft_fail",
            soft and not crashed,
            (time.perf_counter() - t0) * 1000,
            f"map_err={r.get('error','?')[:40]} alive={a.alive()}",
            bugs,
        )
        a.close()
    except Exception as exc:  # noqa: BLE001
        record("wrong_repo_soft_fail", False, (time.perf_counter() - t0) * 1000, str(exc), bugs)


def test_adversarial_bombardment() -> None:
    t0 = time.perf_counter()
    a = AgentSession("adversary")
    cases = [
        ("map", {"query": ""}),
        ("map", {"query": "x" * 15000}),
        ("pack_context", {"query": "x", "seed_file": "", "seed_symbol": ""}),
        ("expand_context", {"node": "..\\..\\..\\Windows\\System32\\drivers\\etc\\hosts"}),
        ("map", {"query": "'; DROP TABLE chunks; --"}),
        ("workspace", {"action": "drop_all"}),
        ("gate", {"root": "Z:\\definitely\\missing\\path"}),
        ("collect_hot_context", {"ids": "../../../etc/passwd"}),
    ]
    crashed = False
    for i, (tool, args) in enumerate(cases):
        a.call(tool, args, timeout=15)
        if not a.alive():
            crashed = True
            break
    h = health()
    record(
        "adversarial_10_payloads",
        not crashed and h.get("ok") is True,
        (time.perf_counter() - t0) * 1000,
        f"mcp_alive={not crashed} engine_ok={h.get('ok')}",
    )
    a.close()


def test_malformed_rpc() -> None:
    t0 = time.perf_counter()
    a = AgentSession("malformed")
    bugs: list[str] = []
    try:
        a.send_raw({"jsonrpc": "2.0", "id": 99, "method": "tools/call", "params": {"name": "map"}})
        time.sleep(0.2)
        a.send_raw("not json at all\n")
        time.sleep(0.2)
        a.send_raw({"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "nope_tool", "arguments": {}}})
        time.sleep(0.2)
        # valid call after garbage
        r = a.call("status", {}, timeout=30)
        ok = a.alive() and r.get("ok") is not False and not r.get("__timeout__")
        if not ok:
            bugs.append(f"recovery after malformed failed: {r}")
        record(
            "malformed_rpc_recovery",
            ok,
            (time.perf_counter() - t0) * 1000,
            f"alive={a.alive()} status_ok={r.get('ok')}",
            bugs,
        )
    finally:
        a.close()


def test_engine_kill_under_load() -> None:
    """Kill engine while agents are mid-flight; verify recovery."""
    t0 = time.perf_counter()
    agents = [AgentSession(f"kill-{i}") for i in range(3)]
    stop = threading.Event()
    bugs: list[str] = []

    def hammer(a: AgentSession) -> None:
        while not stop.is_set():
            a.call("map", {"query": "daemon engine health warm"}, timeout=45)

    threads = [threading.Thread(target=hammer, args=(a,), daemon=True) for a in agents]
    for t in threads:
        t.start()
    time.sleep(2)
    cli("engine", "stop", timeout=30)
    time.sleep(2)
    stop.set()
    for t in threads:
        t.join(timeout=5)
    mcp_crashes = sum(1 for a in agents if not a.alive())
    cli("engine", "start", str(REPO), timeout=60)
    time.sleep(5)
    h = health()
    # recovery probe
    a2 = AgentSession("recovery-probe")
    r = a2.call("map", {"query": "lifecycle guard"}, timeout=90)
    a2.close()
    for a in agents:
        a.close()
    recovered = h.get("ok") and (_map_ok(r) or r.get("should_retry"))
    record(
        "engine_kill_under_load",
        mcp_crashes == 0 and recovered,
        (time.perf_counter() - t0) * 1000,
        f"mcp_crashes={mcp_crashes} engine_ok={h.get('ok')} map_after={_map_ok(r)}",
        bugs,
    )


def test_session_isolation() -> None:
    """Two agents write workspace hints; should not bleed."""
    t0 = time.perf_counter()
    a1 = AgentSession("iso-a")
    a2 = AgentSession("iso-b")
    bugs: list[str] = []
    try:
        r1 = a1.call("workspace", {"action": "note", "text": "BREAKIT_AGENT_A_UNIQUE_TOKEN_XYZ"}, timeout=30)
        r2 = a2.call("workspace", {"action": "show"}, timeout=30)
        text = json.dumps(r2)
        leaked = "BREAKIT_AGENT_A_UNIQUE_TOKEN_XYZ" in text and r2.get("__agent__") == "iso-b"
        if leaked:
            bugs.append("agent B saw agent A workspace note")
        record(
            "session_isolation",
            not leaked and a1.alive() and a2.alive(),
            (time.perf_counter() - t0) * 1000,
            f"leaked={leaked}",
            bugs,
        )
    finally:
        a1.close()
        a2.close()


def test_parallel_map_inprocess() -> None:
    """8-thread in-process map (same as pytest stress)."""
    t0 = time.perf_counter()
    bugs: list[str] = []
    try:
        os.environ["CTX_REPO"] = str(REPO)
        os.environ["CTX_MCP_SURFACE"] = "phase"
        sys.path.insert(0, str(ROOT / "packages"))
        from pipeline.mcp_locate import create_mcp

        mcp = create_mcp(name="break-it-parallel")
        map_fn = mcp._tool_manager._tools["map"].fn
        queries = [
            "daemon watchdog force_restart",
            "session store dedup expand",
            "merkle incremental sync dirty",
            "embedder CodeRank batch",
            "mcp_locate map focus phase",
            "graphify AST extract build",
            "conductor RRF BM25 dense",
            "resource manager memory budget",
        ]

        def one(i: int) -> bool:
            try:
                raw = map_fn(query=queries[i], k=6, response_format="json", session_id=f"break-{i}")
                card = json.loads(raw)
                return bool(card.get("ok") and int(card.get("count") or 0) > 0)
            except Exception as exc:  # noqa: BLE001
                bugs.append(f"map-{i}: {exc}")
                return False

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(one, range(8)))
        ok = sum(results)
        record(
            "inprocess_parallel_map_x8",
            ok >= 7,
            (time.perf_counter() - t0) * 1000,
            f"ok={ok}/8",
            bugs,
        )
    except Exception as exc:  # noqa: BLE001
        record("inprocess_parallel_map_x8", False, (time.perf_counter() - t0) * 1000, str(exc)[:200], bugs)


def restore_connect() -> None:
    cli("connect", "--cursor", timeout=60)


def main() -> int:
    print("=" * 60)
    print("SCUBIEE MCP BREAK-IT SUITE")
    print(f"Repo: {REPO}")
    print(f"MCP:  {MCP_BIN}")
    h0 = health()
    print(f"Engine: ok={h0.get('ok')} warm={h0.get('warm')} repo={h0.get('repo')}")
    print("=" * 60)

    if not MCP_BIN.is_file():
        print(f"Missing {MCP_BIN}")
        return 2

    sections = [
        ("1. Multi-agent parallel map (6 agents x 8)", test_multi_agent_parallel_map),
        ("2. Cross-tool storm", test_cross_tool_storm),
        ("3. CLI + MCP race", test_cli_mcp_race),
        ("4. Wrong repo soft fail", test_wrong_repo_agent),
        ("5. Adversarial payloads", test_adversarial_bombardment),
        ("6. Malformed RPC recovery", test_malformed_rpc),
        ("7. Engine kill under load", test_engine_kill_under_load),
        ("8. Session isolation", test_session_isolation),
        ("9. In-process parallel map x8", test_parallel_map_inprocess),
    ]

    for title, fn in sections:
        print(f"\n--- {title} ---")
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            record(fn.__name__, False, 0, f"EXCEPTION: {exc}")

    print("\n--- Restore connect ---")
    restore_connect()

    passed = sum(1 for c in RESULTS if c.ok)
    failed = [c for c in RESULTS if not c.ok]
    print("\n" + "=" * 60)
    print(f"SUMMARY: {passed}/{len(RESULTS)} passed")
    all_bugs = [b for c in RESULTS for b in c.bugs]
    if failed:
        print("FAILURES:")
        for c in failed:
            print(f"  - {c.name}: {c.detail}")
    if all_bugs:
        print(f"BUG HINTS ({len(all_bugs)}):")
        for b in all_bugs[:15]:
            print(f"  * {b}")

    LOG_PATH.write_text(
        json.dumps({"passed": passed, "total": len(RESULTS), "cases": [asdict(c) for c in RESULTS]}, indent=2),
        encoding="utf-8",
    )
    print(f"Log: {LOG_PATH}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
