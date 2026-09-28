#!/usr/bin/env python3
"""Live MCP stdio bug-bounty: call every ship tool over scubiee-mcp JSON-RPC."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 90


class McpSession:
    def __init__(self, repo: Path) -> None:
        env = os.environ.copy()
        env["CTX_REPO"] = str(repo).replace("\\", "/")
        env["CTX_MCP_SURFACE"] = "phase"
        env["CTX_MCP_EXPERIMENT"] = "ship"
        env["PYTHONUTF8"] = "1"
        env["CTX_ENGINE_IDLE_S"] = "15"
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        self.proc = subprocess.Popen(
            ["scubiee-mcp"],
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
        self._handshake()

    def _send(self, msg: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def _recv(self, timeout: float = 30) -> dict | None:
        assert self.proc.stdout is not None
        q: queue.Queue[str] = queue.Queue()

        def _r() -> None:
            q.put(self.proc.stdout.readline())

        t = threading.Thread(target=_r, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            return None
        line = q.get_nowait() if not q.empty() else ""
        return json.loads(line) if line and line.strip() else None

    def _handshake(self) -> None:
        self._send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "bb-stdio", "version": "1"},
                },
            }
        )
        self._recv(timeout=60)
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call(self, name: str, args: dict, timeout: float = TIMEOUT) -> dict:
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
        except (json.JSONDecodeError, TypeError):
            return {"__raw__": text, "__dt__": dt}

    def list_tools(self) -> list[str]:
        self._id += 1
        self._send({"jsonrpc": "2.0", "id": self._id, "method": "tools/list", "params": {}})
        resp = self._recv(timeout=30)
        if not resp or "result" not in resp:
            return []
        return [t["name"] for t in resp["result"].get("tools", [])]

    def close(self) -> None:
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


def main() -> int:
    repo = ROOT
    failed: list[str] = []
    passed = 0

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
            print(f"  PASS  {name}" + (f" — {detail}" if detail else ""))
        else:
            failed.append(f"{name}: {detail}")
            print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))

    print("=== MCP stdio ship tools ===")
    mcp = McpSession(repo)
    try:
        tools = set(mcp.list_tools())
        required = {
            "gate",
            "map",
            "pack_context",
            "expand_context",
            "collect_hot_context",
            "workspace",
            "expand",
            "status",
        }
        check("tools_registered", required <= tools, f"missing={sorted(required - tools)}")
        check("no_forbidden", not (tools & {"grep", "glob", "pinpoint"}), str(tools & {"grep", "glob", "pinpoint"}))

        # Adversarial empty / junk
        for label, args in (
            ("map_empty", {"query": ""}),
            ("map_whitespace", {"query": "   "}),
            ("pack_no_seed", {"query": "lifecycle_runtime idle_seconds", "mode": "lean"}),
        ):
            if label.startswith("map"):
                out = mcp.call("map", args, timeout=60)
            else:
                out = mcp.call("pack_context", args, timeout=90)
            check(f"{label}_no_crash", "__timeout__" not in out and "__error__" not in out, str(out)[:160])

        # Happy path ladder
        st = mcp.call("status", {}, timeout=60)
        check("status_ok", st.get("ok") is True, str(st)[:200])
        check("status_engine_healthy", (st.get("engine") or {}).get("healthy") is True, str(st.get("engine")))

        gate = mcp.call("gate", {"root": str(repo)}, timeout=30)
        # gate may return plain string line
        gate_ok = ("__error__" not in gate) and ("__timeout__" not in gate)
        check("gate_ok", gate_ok, str(gate)[:120])

        q = (
            "lifecycle_runtime idle_seconds apply_idle_policy enter_standby "
            "adopt_installed_package_on_connect memory_governor embed_idle_demote"
        )
        mp = mcp.call("map", {"query": q, "k": 10}, timeout=90)
        check("map_ok", mp.get("ok") is True, str(mp)[:200])
        cards = mp.get("cards") or mp.get("results") or []
        seed_file = None
        seed_symbol = None
        if isinstance(cards, list) and cards:
            c0 = cards[0]
            seed_file = c0.get("file")
            seed_symbol = c0.get("symbol")
        suggested = mp.get("suggested_seed") or {}
        if isinstance(suggested, dict) and suggested.get("file"):
            seed_file = suggested.get("file") or seed_file
            seed_symbol = suggested.get("symbol") or seed_symbol

        pack_args = {"query": q, "mode": "lean"}
        if seed_file:
            pack_args["seed_file"] = seed_file
        if seed_symbol:
            pack_args["seed_symbol"] = seed_symbol
        pk = mcp.call("pack_context", pack_args, timeout=120)
        check("pack_ok", pk.get("ok") is True, str(pk)[:220])
        heatmap = pk.get("heatmap") or []
        check("pack_heatmap", bool(heatmap), f"n={len(heatmap) if isinstance(heatmap, list) else 0}")

        seed = pk.get("seed") if isinstance(pk.get("seed"), dict) else {}
        node = seed.get("id") if seed else None
        if not node and isinstance(heatmap, list) and heatmap:
            node = (heatmap[0] or {}).get("id")
        if node:
            ex = mcp.call(
                "expand_context",
                {"node": node, "direction": "callees", "query": q},
                timeout=90,
            )
            check("expand_ok", ex.get("ok") is True, str(ex)[:200])
            hot = mcp.call("collect_hot_context", {"ids": str(node)}, timeout=90)
            check("collect_hot_ok", hot.get("ok") is True, str(hot)[:200])
        else:
            check("expand_ok", False, "no seed node")
            check("collect_hot_ok", False, "no seed node")

        ws = mcp.call("workspace", {"action": "show"}, timeout=60)
        check("workspace_ok", ws.get("ok") is True, str(ws)[:200])

        # expand (session) should not crash
        exp = mcp.call("expand", {}, timeout=60)
        check("expand_session_no_crash", "__timeout__" not in exp and "__error__" not in exp, str(exp)[:160])
    finally:
        mcp.close()

    print(f"\npassed={passed} failed={len(failed)}")
    for item in failed:
        print(f"  - {item}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
