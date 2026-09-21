#!/usr/bin/env python3
"""Production Cursor-open battery — exit 0 only when every gate passes.

Simulates: Cursor starts → mcp_bridge (CTX_MCP_CLIENT=cursor) attaches →
soft/embedder ready → settle idle (no map) → first map ≤1s → pack/expand →
warm_contract idle hold → ship ladder.

Usage:
  python scripts/cursor_open_prod_battery.py
  python scripts/cursor_open_prod_battery.py --settle-s 30 --idle-s 60

Writes REPORT.md under docs/superpowers/plans/_preprod_<ver>_cursor_open/.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / "packages"
if str(PACKAGES) not in sys.path:
    sys.path.insert(0, str(PACKAGES))

UV_PY = (
    Path.home()
    / "AppData"
    / "Roaming"
    / "uv"
    / "tools"
    / "scubiee"
    / "Scripts"
    / "python.exe"
)


def _py() -> str:
    if UV_PY.is_file():
        return str(UV_PY)
    return sys.executable


def _run(
    cmd: list[str],
    *,
    log: Path,
    env: dict[str, str] | None = None,
    timeout: float = 600.0,
) -> dict[str, Any]:
    log.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    merged = os.environ.copy()
    if env:
        merged.update(env)
    # Prefer uv-tool scubiee package over conda/workspace fights.
    merged.setdefault("PYTHONUTF8", "1")
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=merged,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    wall = round((time.perf_counter() - t0) * 1000, 1)
    text = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    log.write_text(text, encoding="utf-8")
    return {
        "ok": proc.returncode == 0,
        "code": proc.returncode,
        "wall_ms": wall,
        "log": str(log),
        "tail": text[-2500:],
    }


def _check_mcp_pins() -> dict[str, Any]:
    path = ROOT / ".cursor" / "mcp.json"
    if not path.is_file():
        return {"ok": False, "error": "missing .cursor/mcp.json"}
    data = json.loads(path.read_text(encoding="utf-8"))
    srv = (data.get("mcpServers") or {}).get("scubiee") or {}
    env = srv.get("env") or {}
    checks = {
        "CTX_MCP_CLIENT": str(env.get("CTX_MCP_CLIENT") or "") == "cursor",
        "CTX_EMBED_KEEPALIVE": str(env.get("CTX_EMBED_KEEPALIVE") or "") in {"1", "true", "yes"},
        "CTX_EMBED_KEEPALIVE_S": str(env.get("CTX_EMBED_KEEPALIVE_S") or "") == "8",
        "CTX_EMBED_PREWARM": str(env.get("CTX_EMBED_PREWARM") or "") in {"1", "true", "yes"},
        "CTX_ENGINE_CPU_CAP_PCT": str(env.get("CTX_ENGINE_CPU_CAP_PCT") or "") in {"35", "35.0"},
        "build_0_3_97": str(env.get("CTX_SCUBIEE_BUILD") or "").startswith("0.3.97"),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "env_slice": {
            k: env.get(k)
            for k in (
                "CTX_MCP_CLIENT",
                "CTX_EMBED_KEEPALIVE",
                "CTX_EMBED_KEEPALIVE_S",
                "CTX_EMBED_PREWARM",
                "CTX_ENGINE_CPU_CAP_PCT",
                "CTX_SCUBIEE_BUILD",
            )
        },
    }


def _parse_host_sim_json(out_dir: Path) -> dict[str, Any]:
    reports = sorted(out_dir.glob("mcp-host-sim-*.json"), key=lambda p: p.stat().st_mtime)
    if not reports:
        return {}
    try:
        return json.loads(reports[-1].read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"path": str(reports[-1]), "parse_error": True}


def _write_report(out_dir: Path, summary: dict[str, Any]) -> Path:
    lines = [
        "# Cursor-open production battery — 0.3.97",
        "",
        f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "**Harness:** cold kill → Cursor-client Lane A settle → warm_contract → ship_check → mcp.json pins",
        "",
        f"**Verdict: {'PASS' if summary.get('ok') else 'FAIL'}**",
        "",
        "## Results",
        "",
        "| Step | Result | Key numbers |",
        "|------|--------|-------------|",
    ]
    for step in summary.get("steps") or []:
        key = step.get("key") or ""
        ok = "PASS" if step.get("ok") else "FAIL"
        detail = step.get("detail") or ""
        lines.append(f"| **{key}** | {ok} | {detail} |")
    lines.extend(["", "## Notes", ""])
    for n in summary.get("notes") or []:
        lines.append(f"- {n}")
    if summary.get("errors"):
        lines.extend(["", "## Errors", ""])
        for e in summary["errors"]:
            lines.append(f"- {e}")
    path = out_dir / "REPORT.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--settle-s", type=float, default=30.0)
    ap.add_argument("--idle-s", type=float, default=60.0)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT
        / "docs"
        / "superpowers"
        / "plans"
        / "_preprod_0_3_97_cursor_open",
    )
    args = ap.parse_args()
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    py = _py()
    steps: list[dict[str, Any]] = []
    errors: list[str] = []
    notes: list[str] = [
        "Lane A uses CTX_MCP_CLIENT=cursor (matches .cursor/mcp.json).",
        f"Settle idle after soft-ready: {args.settle_s:.0f}s (Cursor-open analogue).",
        "Settle requires embedder_loaded (or successful dense map) before map_first ≤1s (0.3.97).",
        "Engine + MCP procs are killed before Lane A and warm_contract cold legs.",
        "For close→unload→open loops use: python scripts/cursor_close_open_loop.py --rounds 5",
    ]

    # 0 — pins
    pins = _check_mcp_pins()
    steps.append(
        {
            "key": "mcp.json pins",
            "ok": pins.get("ok"),
            "detail": json.dumps(pins.get("env_slice") or pins),
        }
    )
    if not pins.get("ok"):
        errors.append(f"mcp.json pins: {pins}")
        # Attempt repair once
        repair = _run(
            ["scubiee", "connect", "--cursor", "--repo", str(ROOT)],
            log=out_dir / "connect_repair.log",
            timeout=120,
        )
        pins2 = _check_mcp_pins()
        steps.append(
            {
                "key": "mcp.json pins (after connect)",
                "ok": pins2.get("ok"),
                "detail": json.dumps(pins2.get("env_slice") or pins2),
            }
        )
        if not pins2.get("ok"):
            errors.append("mcp.json still wrong after scubiee connect --cursor")
        notes.append(f"connect repair ok={repair.get('ok')} code={repair.get('code')}")

    # 1 — cold_start (no hang past 15s)
    cold = _run(
        [py, str(ROOT / "scripts" / "cold_start_acceptance.py")],
        log=out_dir / "cold_start.log",
        timeout=180,
    )
    steps.append(
        {
            "key": "cold_start_acceptance",
            "ok": cold["ok"],
            "detail": f"exit={cold['code']} wall_ms={cold['wall_ms']}",
        }
    )
    if not cold["ok"]:
        errors.append("cold_start_acceptance failed — see cold_start.log")

    # 2 — Lane A Cursor settle
    host = _run(
        [
            py,
            str(ROOT / "scripts" / "mcp_host_sim.py"),
            "--lane",
            "a",
            "--live",
            "--skip-idle",
            "--settle-s",
            str(args.settle_s),
            "--mcp-client",
            "cursor",
            "--out-dir",
            str(out_dir),
        ],
        log=out_dir / "host_sim_lane_a_cursor_settle.log",
        env={"CTX_EMBED_KEEPALIVE_S": "8", "CTX_EMBED_KEEPALIVE": "1"},
        timeout=600,
    )
    hs = _parse_host_sim_json(out_dir)
    phase_bits = []
    for p in hs.get("phases") or []:
        phase_bits.append(
            f"{p.get('name')}={'ok' if p.get('ok') else p.get('code')} "
            f"{p.get('elapsed_ms')}ms"
        )
    steps.append(
        {
            "key": f"Lane A settle ({args.settle_s:.0f}s, client=cursor)",
            "ok": host["ok"] and bool(hs.get("ok", host["ok"])),
            "detail": (
                f"exit={host['code']}; scenario={hs.get('scenario')}; "
                + "; ".join(phase_bits[:8])
            ),
        }
    )
    if not (host["ok"] and hs.get("ok", host["ok"])):
        errors.append(
            "Lane A Cursor settle failed — see host_sim_lane_a_cursor_settle.log / mcp-host-sim-*.md"
        )

    # 3 — warm_contract against a fresh ensure (avoid kill_all mid-DML — that
    # leaves DirectML wedged so HTTP prewarm never finishes).
    ensure = _run(
        ["scubiee", "engine", "ensure", str(ROOT)],
        log=out_dir / "engine_ensure_before_warm.log",
        timeout=120,
    )
    time.sleep(2.0)
    warm = _run(
        [
            py,
            str(ROOT / "scripts" / "warm_contract_acceptance.py"),
            "--no-stop",
            "--idle-s",
            str(args.idle_s),
            "--deadline-ms",
            "90000",
        ],
        log=out_dir / "warm_contract.log",
        env={
            "CTX_EMBED_KEEPALIVE_S": "8",
            "CTX_EMBED_KEEPALIVE": "1",
            "CTX_WARM_DEADLINE_MS": "90000",
        },
        timeout=600,
    )
    steps.append(
        {
            "key": f"warm_contract (idle {args.idle_s:.0f}s)",
            "ok": warm["ok"] and ensure.get("ok", True),
            "detail": (
                f"ensure_exit={ensure['code']} warm_exit={warm['code']} "
                f"wall_ms={warm['wall_ms']}"
            ),
        }
    )
    if not warm["ok"]:
        errors.append("warm_contract_acceptance failed — see warm_contract.log")

    # 4 — ship_check (engine should still be up after warm -- without --no-stop it stops;
    # warm_contract default stops then restarts — leave engine; ship against live)
    ship = _run(
        [py, str(ROOT / "scripts" / "scubiee_mcp_ship_check.py")],
        log=out_dir / "ship_check.log",
        timeout=300,
    )
    steps.append(
        {
            "key": "ship_check",
            "ok": ship["ok"],
            "detail": f"exit={ship['code']} wall_ms={ship['wall_ms']}",
        }
    )
    if not ship["ok"]:
        errors.append("ship_check failed — see ship_check.log")

    summary = {
        "ok": all(bool(s.get("ok")) for s in steps) and not errors,
        "steps": steps,
        "errors": errors,
        "notes": notes,
        "settle_s": args.settle_s,
        "idle_s": args.idle_s,
        "host_sim": {
            "ok": hs.get("ok"),
            "scenario": hs.get("scenario"),
            "mcp_client": hs.get("mcp_client"),
            "phases": hs.get("phases"),
        },
    }
    report_path = _write_report(out_dir, summary)
    print(json.dumps({k: summary[k] for k in ("ok", "errors")}, indent=2))
    print("wrote", report_path)
    for s in steps:
        print(f"[{'PASS' if s.get('ok') else 'FAIL'}] {s.get('key')}: {s.get('detail')}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
