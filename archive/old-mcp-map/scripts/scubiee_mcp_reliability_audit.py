"""Scubiee MCP reliability audit (Cursor/engine/MCP races).

Exercises:
  1) HTTP /health signal matrix
  2) MCP stdio bridge: status → map → pack_context → expand_context
  3) Engine stop → map error clarity / latency
  4) Engine start → immediate map (cold-wake race)
  5) Burst map ×5 while ready
  6) Status field contradictions (warm vs soft_search_ready vs agent_ready vs ready)

Writes JSON + prints a short summary. Does not invent fixes — evidence only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(r"C:/Users/usman/Downloads/context-engine")
BRIDGE = Path(os.environ.get("SCUBIEE_MCP_BRIDGE", r"C:/Users/usman/.local/bin/scubiee-mcp-bridge.EXE"))
CURSOR_MCP = ROOT / ".cursor" / "mcp.json"
OUT = ROOT / "docs" / "superpowers" / "plans" / "2026-09-10-scubiee-mcp-reliability-probes.json"
ENGINE = "http://127.0.0.1:8765"
PROJECT_ID = "ce_2f9c289d2a885432f240969ea2889532"
QUERY = (
    "scubiee connect writes Cursor mcp.json autoApprove permissions.json "
    "mcpAllowlist via install_tool write_project_tool_surface "
    "apply_permissions_to_repo_tool_surface; write_project_gate_rules "
    "AGENTS.md GATE managed_gate_usage_short MCP-first BAN shell"
)


def _http_json(path: str, timeout: float = 8.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(ENGINE + path, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        return {"_error": f"{type(exc).__name__}: {exc}"}


def _scubiee(*args: str, timeout: float = 120.0) -> tuple[int, str]:
    env = os.environ.copy()
    env.setdefault("CTX_ENGINE_IDLE_S", "3600")
    env.setdefault("PYTHONUTF8", "1")
    p = subprocess.run(
        ["scubiee", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _load_cursor_env() -> dict[str, str]:
    data = json.loads(CURSOR_MCP.read_text(encoding="utf-8"))
    entry = (data.get("mcpServers") or {}).get("scubiee") or {}
    env = {str(k): str(v) for k, v in (entry.get("env") or {}).items()}
    env.setdefault("CTX_MCP_CLIENT", "cursor")
    env.setdefault("CTX_MCP_EXPERIMENT", "ship")
    env.setdefault("CTX_MCP_SURFACE", "phase")
    env.setdefault("CTX_REPO", str(ROOT).replace("\\", "/"))
    env.setdefault("CTX_PROJECT_ID", PROJECT_ID)
    env.setdefault("CTX_ENGINE_URL", ENGINE)
    # Keep engine alive during the audit itself.
    env["CTX_ENGINE_IDLE_S"] = "3600"
    return env


class McpStdioClient:
    def __init__(self, proc: subprocess.Popen[str]):
        self.proc = proc
        self._id = 0

    def _next(self) -> int:
        self._id += 1
        return self._id

    def request(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 90.0) -> dict[str, Any]:
        assert self.proc.stdin and self.proc.stdout
        msg_id = self._next()
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            payload["params"] = params
        self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = self.proc.stdout.readline()
            if not raw:
                if self.proc.poll() is not None:
                    raise RuntimeError(f"bridge exited early code={self.proc.returncode}")
                continue
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("id") != msg_id:
                continue
            if "error" in msg:
                raise RuntimeError(json.dumps(msg["error"]))
            return msg.get("result") or {}
        raise TimeoutError(f"timeout waiting for {method}")

    def call_tool(self, name: str, arguments: dict[str, Any], *, timeout: float = 120.0) -> Any:
        result = self.request(
            "tools/call",
            {"name": name, "arguments": arguments},
            timeout=timeout,
        )
        # FastMCP / bridge may wrap content
        content = result.get("content")
        if isinstance(content, list) and content:
            texts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(str(block.get("text") or ""))
            joined = "\n".join(texts).strip()
            if joined:
                try:
                    return json.loads(joined)
                except json.JSONDecodeError:
                    return {"_raw": joined, "_meta": result}
        return result


def probe(name: str, ok: bool, detail: Any, ms: float, probes: list[dict[str, Any]]) -> None:
    probes.append(
        {
            "name": name,
            "ok": bool(ok),
            "ms": round(ms, 1),
            "detail": detail,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    )
    flag = "PASS" if ok else "FAIL"
    print(f"[{flag}] {name} ({ms:.0f}ms)")


def main() -> int:
    probes: list[dict[str, Any]] = []
    session_issues: list[dict[str, Any]] = []

    # --- HTTP baseline ---
    t0 = time.perf_counter()
    health = _http_json("/health")
    probe(
        "http_health_baseline",
        isinstance(health, dict) and health.get("ok") is True and health.get("warm_state") == "ready",
        health,
        (time.perf_counter() - t0) * 1000,
        probes,
    )

    # --- Cursor MCP idle config ---
    env = _load_cursor_env()
    idle = str(env.get("CTX_ENGINE_IDLE_S") or "")
    probe(
        "cursor_mcp_idle_default_is_aggressive",
        # Document as ISSUE when idle is very short (evidence for report).
        # ok=False means "this config is a reliability risk".
        False if idle in {"", "15", "20", "25"} else True,
        {"CTX_ENGINE_IDLE_S_in_mcp_json": idle, "note": "15s idle kills indexing mid-flight"},
        0.0,
        probes,
    )
    if idle in {"", "15", "20", "25"}:
        session_issues.append(
            {
                "id": "IDLE-SWEEP-KILLS-INDEX",
                "severity": "P0",
                "summary": f"Cursor mcp.json sets CTX_ENGINE_IDLE_S={idle or '15'}; idle sweep retires engine during indexing",
            }
        )

    # --- MCP stdio happy path ---
    if not BRIDGE.exists():
        probe("mcp_bridge_exists", False, {"path": str(BRIDGE)}, 0.0, probes)
    else:
        proc = subprocess.Popen(
            [str(BRIDGE)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, **env},
            cwd=str(ROOT),
        )
        client = McpStdioClient(proc)
        try:
            t0 = time.perf_counter()
            init = client.request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "scubiee-reliability-audit", "version": "0.1"},
                },
                timeout=30,
            )
            # required notification
            assert client.proc.stdin
            client.proc.stdin.write(
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
            )
            client.proc.stdin.flush()
            probe("mcp_initialize", bool(init), {"server": (init or {}).get("serverInfo")}, (time.perf_counter() - t0) * 1000, probes)

            t0 = time.perf_counter()
            tools = client.request("tools/list", {}, timeout=30)
            names = {t.get("name") for t in (tools.get("tools") or []) if isinstance(t, dict)}
            need = {"gate", "map", "pack_context", "expand_context", "status"}
            probe(
                "mcp_tools_list",
                need.issubset(names),
                {"tools": sorted(names), "missing": sorted(need - names)},
                (time.perf_counter() - t0) * 1000,
                probes,
            )

            t0 = time.perf_counter()
            st = client.call_tool(
                "status",
                {"root": str(ROOT), "project_id": PROJECT_ID, "detail": "full"},
                timeout=60,
            )
            soft = bool((st.get("engine") or {}).get("soft_search_ready") or st.get("soft_search_ready"))
            warm = (st.get("engine") or {}).get("warm_state") or st.get("warm_state")
            agent_ready = st.get("agent_ready")
            ready = st.get("ready")
            contradiction = (warm == "ready" and soft is True) and (
                agent_ready in {"warming", "stale"} or ready is False
            )
            probe(
                "mcp_status_signal_coherence",
                not contradiction,
                {
                    "warm_state": warm,
                    "soft_search_ready": soft,
                    "agent_ready": agent_ready,
                    "ready": ready,
                    "sync_state": st.get("sync_state") or st.get("sync_status"),
                    "agent_ready_note": st.get("agent_ready_note"),
                    "contradiction": contradiction,
                },
                (time.perf_counter() - t0) * 1000,
                probes,
            )
            if contradiction:
                session_issues.append(
                    {
                        "id": "STATUS-SIGNAL-CONTRADICTION",
                        "severity": "P1",
                        "summary": "status reports warm/soft ready while agent_ready/ready disagree",
                        "detail": {
                            "warm_state": warm,
                            "soft_search_ready": soft,
                            "agent_ready": agent_ready,
                            "ready": ready,
                        },
                    }
                )

            t0 = time.perf_counter()
            mp = client.call_tool(
                "map",
                {"query": QUERY, "k": 8, "root": str(ROOT), "project_id": PROJECT_ID},
                timeout=120,
            )
            map_ok = bool(mp.get("ok")) and bool(mp.get("cards") or mp.get("suggested_seed"))
            probe(
                "mcp_map_happy",
                map_ok,
                {
                    "ok": mp.get("ok"),
                    "error": mp.get("error"),
                    "n_cards": len(mp.get("cards") or []),
                    "seed": mp.get("suggested_seed"),
                    "top": [(c.get("file"), c.get("symbol")) for c in (mp.get("cards") or [])[:3]],
                },
                (time.perf_counter() - t0) * 1000,
                probes,
            )

            seed = mp.get("suggested_seed") or {}
            seed_file = seed.get("file") or "packages/pipeline/rules_installer.py"
            seed_symbol = seed.get("symbol") or "write_project_gate_rules"
            t0 = time.perf_counter()
            pk = client.call_tool(
                "pack_context",
                {
                    "query": QUERY + f"; seed {seed_file}::{seed_symbol}",
                    "seed_file": seed_file,
                    "seed_symbol": seed_symbol,
                    "mode": "lean",
                    "k": 12,
                    "root": str(ROOT),
                    "project_id": PROJECT_ID,
                },
                timeout=120,
            )
            pack_ok = bool(pk.get("ok")) and bool(pk.get("heatmap"))
            probe(
                "mcp_pack_lean_happy",
                pack_ok,
                {
                    "ok": pk.get("ok"),
                    "error": pk.get("error"),
                    "n_heat": len(pk.get("heatmap") or []),
                    "top": [(h.get("id"), h.get("heat")) for h in (pk.get("heatmap") or [])[:5]],
                },
                (time.perf_counter() - t0) * 1000,
                probes,
            )

            t0 = time.perf_counter()
            ex = client.call_tool(
                "expand_context",
                {
                    "query": QUERY,
                    "seed_file": seed_file,
                    "seed_symbol": seed_symbol,
                    "root": str(ROOT),
                    "project_id": PROJECT_ID,
                },
                timeout=120,
            )
            expand_ok = bool(ex.get("ok")) or bool(ex.get("cards") or ex.get("heatmap") or ex.get("items"))
            probe(
                "mcp_expand_context",
                expand_ok,
                {
                    "ok": ex.get("ok"),
                    "error": ex.get("error"),
                    "keys": sorted(ex.keys())[:20] if isinstance(ex, dict) else type(ex).__name__,
                },
                (time.perf_counter() - t0) * 1000,
                probes,
            )

            # Burst map
            burst_fail = 0
            t0 = time.perf_counter()
            for i in range(5):
                b = client.call_tool(
                    "map",
                    {
                        "query": f"{QUERY} burst={i}",
                        "k": 5,
                        "root": str(ROOT),
                        "project_id": PROJECT_ID,
                    },
                    timeout=90,
                )
                if not (b.get("ok") and (b.get("cards") or b.get("suggested_seed"))):
                    burst_fail += 1
            probe(
                "mcp_burst_map_5x",
                burst_fail == 0,
                {"fail": burst_fail},
                (time.perf_counter() - t0) * 1000,
                probes,
            )
        except Exception as exc:  # noqa: BLE001
            probe("mcp_stdio_session", False, {"error": f"{type(exc).__name__}: {exc}"}, 0.0, probes)
            session_issues.append(
                {
                    "id": "MCP-STDIO-SESSION-FAIL",
                    "severity": "P0",
                    "summary": str(exc),
                }
            )
        finally:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass

    # --- Engine down clarity ---
    t0 = time.perf_counter()
    code, out = _scubiee("engine", "stop", timeout=60)
    stop_ms = (time.perf_counter() - t0) * 1000
    time.sleep(1.5)
    t0 = time.perf_counter()
    # Use a fresh bridge call is hard after kill; use CLI map for unreachable clarity
    code2, map_down = _scubiee("map", QUERY, "--k", "3", timeout=60)
    down_ms = (time.perf_counter() - t0) * 1000
    clear = any(
        s in map_down.lower()
        for s in ("unreachable", "refused", "not running", "engine stopped", "warming", "error")
    ) and down_ms < 45000
    probe(
        "cli_map_when_engine_stopped",
        clear,
        {
            "stop_code": code,
            "map_code": code2,
            "ms": round(down_ms, 1),
            "snippet": map_down[:400],
        },
        down_ms,
        probes,
    )

    # --- Cold wake race ---
    t0 = time.perf_counter()
    _scubiee("engine", "start", timeout=90)
    # Intentionally immediate — do not wait for ready
    code3, map_wake = _scubiee("map", QUERY, "--k", "5", timeout=90)
    wake_ms = (time.perf_counter() - t0) * 1000
    health2 = _http_json("/health")
    wake_ok = ("suggested_seed" in map_wake) or ('"cards"' in map_wake)
    probe(
        "cli_map_immediately_after_engine_start",
        wake_ok,
        {
            "map_ok": wake_ok,
            "health": health2,
            "snippet": map_wake[:400],
        },
        wake_ms,
        probes,
    )
    if not wake_ok:
        session_issues.append(
            {
                "id": "COLD-WAKE-MAP-RACE",
                "severity": "P1",
                "summary": "map right after engine start fails or returns non-ready error",
                "detail": {"health": health2, "snippet": map_wake[:300]},
            }
        )

    # Ensure ready for leftover state
    deadline = time.time() + 120
    while time.time() < deadline:
        h = _http_json("/health")
        if isinstance(h, dict) and h.get("warm_state") == "ready" and h.get("index_usable") is True:
            break
        time.sleep(2)
    _scubiee("engine", "ensure", str(ROOT), timeout=90)

    # Known session issues from live Cursor chat (always include)
    session_issues.extend(
        [
            {
                "id": "MCP-HOST-DISCONNECT-AFTER-KILL",
                "severity": "P0",
                "summary": "Killing scubiee-mcp / bridge during tool reinstall leaves Cursor MCP 'Not connected' / discovery error until host reload + mcp_auth",
                "evidence": "Cursor CallDynamicTool returned Not connected; namespaceStatus=error until user reloaded / mcp_auth",
            },
            {
                "id": "WARM-ERROR-DML-PROVIDER",
                "severity": "P0",
                "summary": "After wipe/reinstall, warm_state=error with DmlExecutionProvider missing until scubiee setup",
                "evidence": "status.engine.warm_error referenced provider:DmlExecutionProvider; map returned error=warming",
            },
            {
                "id": "CORRUPT-PUBLICATION-CHECKSUM",
                "severity": "P0",
                "summary": "doctor reported corrupt publication (checksum_mismatch); soft search stuck until scubiee rebuild",
                "evidence": "scubiee doctor repair_plan rebuild_index; indexing oscillated until rebuild completed",
            },
            {
                "id": "STATUS-SOFT-SEARCH-UNBOUND",
                "severity": "P1",
                "summary": "HTTP health can show ready while MCP status has soft_search_ready=false and project_id=null until engine ensure binds workspace",
                "evidence": "Observed after rebuild: warm_state ready but soft_search_ready false / project_id null",
            },
            {
                "id": "MAP-WINERROR-10061-RACE",
                "severity": "P0",
                "summary": "MCP map fails with WinError 10061 connection refused while parallel shell /health succeeds (engine flapping / idle retire)",
                "evidence": "Repeated in Cursor session 2026-09-10 during indexing",
            },
            {
                "id": "AGENT-READY-VOCAB-CONFUSING",
                "severity": "P2",
                "summary": "agent_ready values warming|stale|ready conflict with warm_state/index_usable; agents over-wait or over-retry",
                "evidence": "status full: warm_state=ready soft_search_ready=true but agent_ready=stale ready=false syncing=true",
            },
            {
                "id": "STATUS-TTL-STALE-AFTER-FLAP",
                "severity": "P2",
                "summary": "MCP status_age / status_ttl_s can report cached readiness while engine already down",
                "evidence": "map unreachable while status_age_s still under TTL from prior ready card",
            },
            {
                "id": "PYPI-INSTALL-FILE-LOCK",
                "severity": "P1",
                "summary": "uv tool install --force fails Access Denied while MCP bridge/python hold uv/tools/scubiee/Scripts",
                "evidence": "Install of 0.3.31 required killing scubiee-mcp processes",
            },
        ]
    )

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "version": "0.3.31",
        "project_id": PROJECT_ID,
        "probes": probes,
        "pass_count": sum(1 for p in probes if p["ok"]),
        "fail_count": sum(1 for p in probes if not p["ok"]),
        "session_issues": session_issues,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"WROTE {OUT} pass={payload['pass_count']} fail={payload['fail_count']} issues={len(session_issues)}")
    return 0 if payload["fail_count"] == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.TimeoutExpired as exc:
        print(f"TIMEOUT: {exc}", file=sys.stderr)
        raise SystemExit(2)
