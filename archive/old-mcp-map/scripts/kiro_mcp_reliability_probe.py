"""Kiro↔Scubiee MCP reliability probe (stdio JSON-RPC, no Kiro login required).

Launches the same bridge binary + env that Kiro uses, then:
  1) initialize
  2) tools/list  (must include gate, map, pack_context, expand_context)
  3) tools/call gate
  4) tools/call map → pack_context(lean)

Exit 0 only if all checks pass. Writes a JSON report.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(r"C:/Users/usman/Downloads/context-engine")
BRIDGE = Path(os.environ.get("SCUBIEE_MCP_BRIDGE", r"C:/Users/usman/.local/bin/scubiee-mcp-bridge.EXE"))
KIRO_MCP = ROOT / ".kiro" / "settings" / "mcp.json"
OUT = ROOT / "docs" / "superpowers" / "plans" / "2026-09-05-kiro-mcp-reliability.json"

REQUIRED_TOOLS = {
    "gate",
    "map",
    "pack_context",
    "expand_context",
    "collect_hot_context",
    "status",
    "workspace",
    "expand",
}

# Ship surface must NOT expose lab/classic locate extras by default.
FORBIDDEN_SHIP_TOOLS = {
    "pinpoint",
    "plate",
    "focus",
    "grep",
    "glob",
    "pack_poly_embed",
    "pack_semantic",
    "map_context",
}


def _load_kiro_env() -> dict[str, str]:
    data = json.loads(KIRO_MCP.read_text(encoding="utf-8"))
    entry = (data.get("mcpServers") or {}).get("scubiee") or {}
    env = {str(k): str(v) for k, v in (entry.get("env") or {}).items()}
    # Ensure composite + client identity
    env.setdefault("CTX_TRACE_ENGINE", "composite_v1")
    env.setdefault("CTX_MCP_CLIENT", "kiro")
    env.setdefault("CTX_MCP_EXPERIMENT", "ship")
    env.setdefault("CTX_MCP_SURFACE", "phase")
    env.setdefault("CTX_REPO", str(ROOT).replace("\\", "/"))
    env.setdefault("CTX_PROJECT_ID", "ce_d9cb766c3820091ed9ffbc64ef33063c")
    env.setdefault("CTX_ENGINE_URL", "http://127.0.0.1:8765")
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
        payload = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            payload["params"] = params
        line = json.dumps(payload, ensure_ascii=False)
        self.proc.stdin.write(line + "\n")
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
                # notifications / other ids — ignore for this probe
                continue
            if "error" in msg:
                raise RuntimeError(f"{method} error: {msg['error']}")
            return msg.get("result") or {}
        raise TimeoutError(f"{method} timed out after {timeout}s")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        assert self.proc.stdin
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()


def _content_text(result: dict[str, Any]) -> str:
    parts = result.get("content") or []
    texts: list[str] = []
    for p in parts:
        if isinstance(p, dict) and p.get("type") == "text":
            texts.append(str(p.get("text") or ""))
        elif isinstance(p, str):
            texts.append(p)
    return "\n".join(texts)


def main() -> int:
    report: dict[str, Any] = {
        "ok": False,
        "bridge": str(BRIDGE),
        "kiro_mcp": str(KIRO_MCP),
        "checks": {},
        "errors": [],
    }
    if not BRIDGE.is_file():
        report["errors"].append(f"bridge missing: {BRIDGE}")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 2
    if not KIRO_MCP.is_file():
        report["errors"].append(f"kiro mcp.json missing: {KIRO_MCP}")
        OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 2

    env = os.environ.copy()
    env.update(_load_kiro_env())
    report["env"] = {
        "CTX_TRACE_ENGINE": env.get("CTX_TRACE_ENGINE"),
        "CTX_MCP_CLIENT": env.get("CTX_MCP_CLIENT"),
        "CTX_REPO": env.get("CTX_REPO"),
        "CTX_SCUBIEE_BUILD": env.get("CTX_SCUBIEE_BUILD"),
    }

    t0 = time.perf_counter()
    proc = subprocess.Popen(
        [str(BRIDGE)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(ROOT),
    )
    client = McpStdioClient(proc)
    try:
        # 1) initialize
        init = client.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "kiro-reliability-probe", "version": "0.1"},
            },
            timeout=60,
        )
        report["checks"]["initialize"] = {
            "ok": True,
            "server": (init.get("serverInfo") or {}).get("name"),
            "version": (init.get("serverInfo") or {}).get("version"),
        }
        client.notify("notifications/initialized")

        # 2) tools/list
        listed = client.request("tools/list", {}, timeout=60)
        names = {t.get("name") for t in (listed.get("tools") or []) if t.get("name")}
        missing = sorted(REQUIRED_TOOLS - names)
        forbidden = sorted(FORBIDDEN_SHIP_TOOLS & names)
        report["checks"]["tools_list"] = {
            "ok": not missing and not forbidden,
            "count": len(names),
            "missing": missing,
            "forbidden_present": forbidden,
            "has_required": sorted(REQUIRED_TOOLS & names),
            "experiment": env.get("CTX_MCP_EXPERIMENT"),
        }
        if missing:
            report["errors"].append(f"missing tools: {missing}")
        if forbidden:
            report["errors"].append(f"ship surface leaked lab/classic tools: {forbidden}")

        # 3) gate
        gate = client.request(
            "tools/call",
            {
                "name": "gate",
                "arguments": {"project_id": env["CTX_PROJECT_ID"]},
            },
            timeout=60,
        )
        gate_text = _content_text(gate)
        gate_ok = "1:ce_" in gate_text or "ce_d9cb766c3820091ed9ffbc64ef33063c" in gate_text
        report["checks"]["gate"] = {"ok": gate_ok, "preview": gate_text[:200]}
        if not gate_ok:
            report["errors"].append(f"gate unexpected: {gate_text[:300]}")

        # 4) map
        map_res = client.request(
            "tools/call",
            {
                "name": "map",
                "arguments": {
                    "query": (
                        "pack_context run_pack_context expand_context composite_v1 "
                        "packages/pipeline/context_trace.py lean ladder"
                    ),
                    "k": 8,
                    "project_id": env["CTX_PROJECT_ID"],
                },
            },
            timeout=120,
        )
        map_text = _content_text(map_res)
        try:
            map_json = json.loads(map_text)
        except json.JSONDecodeError:
            map_json = {"raw": map_text[:500]}
        map_ok = bool(map_json.get("ok")) and bool(map_json.get("cards") or map_json.get("count"))
        report["checks"]["map"] = {
            "ok": map_ok,
            "count": map_json.get("count"),
            "top_file": ((map_json.get("cards") or [{}])[0] or {}).get("file"),
        }
        if not map_ok:
            report["errors"].append(f"map failed: {map_text[:400]}")

        # 5) pack_context lean
        pack_res = client.request(
            "tools/call",
            {
                "name": "pack_context",
                "arguments": {
                    "query": (
                        "Trace run_pack_context lean mode chain bodies expand_context "
                        "with_bodies policy broad composite_v1"
                    ),
                    "seed_file": "packages/pipeline/context_trace.py",
                    "seed_symbol": "run_pack_context",
                    "mode": "lean",
                    "policy": "strict",
                    "project_id": env["CTX_PROJECT_ID"],
                },
            },
            timeout=180,
        )
        pack_text = _content_text(pack_res)
        try:
            pack_json = json.loads(pack_text)
        except json.JSONDecodeError:
            pack_json = {"raw": pack_text[:500]}
        # Lean MCP pack is heatmap-only by default (no bodies / may omit engine).
        heatmap = pack_json.get("heatmap") or []
        read = pack_json.get("read") if isinstance(pack_json.get("read"), dict) else {}
        pack_ok = bool(pack_json.get("ok")) and (
            bool(heatmap)
            or pack_json.get("engine") in {"composite_v1", "polytrace", "system"}
            or bool(pack_json.get("pack") or pack_json.get("chain"))
        )
        report["checks"]["pack_context"] = {
            "ok": pack_ok,
            "engine": pack_json.get("engine"),
            "mode": pack_json.get("mode"),
            "policy": pack_json.get("policy"),
            "heatmap_n": len(heatmap) if heatmap else pack_json.get("count"),
            "read_top": read.get("top"),
            "packed": pack_json.get("packed"),
            "has_next_actions": bool(pack_json.get("next_actions")),
            "seed": (pack_json.get("seed") or {}).get("id")
            if isinstance(pack_json.get("seed"), dict)
            else None,
        }
        if not pack_json.get("ok"):
            report["errors"].append(f"pack failed: {pack_text[:400]}")
        elif not pack_ok:
            report["errors"].append(
                f"pack ok but empty heatmap/engine: keys={sorted(pack_json.keys())[:20]}"
            )

        # 6) expand_context follow-up
        seed_id = ((pack_json.get("seed") or {}) if isinstance(pack_json, dict) else {}).get("id")
        if seed_id:
            exp = client.request(
                "tools/call",
                {
                    "name": "expand_context",
                    "arguments": {
                        "node": seed_id,
                        "direction": "callees",
                        "with_bodies": True,
                        "project_id": env["CTX_PROJECT_ID"],
                    },
                },
                timeout=120,
            )
            exp_text = _content_text(exp)
            try:
                exp_json = json.loads(exp_text)
            except json.JSONDecodeError:
                exp_json = {"raw": exp_text[:300]}
            report["checks"]["expand_context"] = {
                "ok": bool(exp_json.get("ok")),
                "direction": exp_json.get("direction"),
                "delta": exp_json.get("count"),
                "bodies": exp_json.get("bodies"),
            }
            if not exp_json.get("ok"):
                report["errors"].append(f"expand failed: {exp_text[:300]}")
        else:
            report["checks"]["expand_context"] = {"ok": False, "error": "no seed id from pack"}
            report["errors"].append("no seed id from pack")

    except Exception as exc:  # noqa: BLE001
        report["errors"].append(str(exc))
        report["checks"]["exception"] = {"ok": False, "error": str(exc)}
    finally:
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            proc.kill()
        err = ""
        try:
            if proc.stderr:
                err = proc.stderr.read()[-2000:]
        except Exception:  # noqa: BLE001
            pass
        report["stderr_tail"] = err
        report["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    oks = [c.get("ok") for c in report["checks"].values() if isinstance(c, dict) and "ok" in c]
    report["ok"] = bool(oks) and all(oks) and not report["errors"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("ok", "checks", "errors", "env", "elapsed_ms")}, indent=2))
    print("wrote", OUT)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
