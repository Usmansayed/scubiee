"""End-to-end check that a Cursor mcp.json entry actually serves this repo.

Spawns the configured server exactly as Cursor would, speaks MCP over stdio and
reports the advertised tools plus the repo that `status` claims.

    python scripts/verify_mcp_stdio.py --config .cursor/mcp.json --server context-engine
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _rpc(proc: subprocess.Popen, method: str, params: dict, mid: int | None) -> dict:
    msg: dict = {"jsonrpc": "2.0", "method": method, "params": params}
    if mid is not None:
        msg["id"] = mid
    assert proc.stdin
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    if mid is None:
        return {}
    assert proc.stdout
    while True:
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("server closed stdout before replying")
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue  # server logged to stdout; ignore non-JSON noise
        if obj.get("id") == mid:
            return obj


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=str(ROOT / ".cursor" / "mcp.json"))
    ap.add_argument("--server", default="context-engine")
    ap.add_argument("--expect-repo", default=str(ROOT))
    ap.add_argument("--expect-tools", default="map,focus,workspace,recall,expand,status")
    args = ap.parse_args(argv)

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    entry = (cfg.get("mcpServers") or {}).get(args.server)
    if not entry:
        print(f"server '{args.server}' not found in {args.config}", file=sys.stderr)
        return 2

    env = {**os.environ, **(entry.get("env") or {})}
    proc = subprocess.Popen(
        [entry["command"], *entry.get("args", [])],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    try:
        _rpc(
            proc,
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "verify", "version": "0"},
            },
            1,
        )
        _rpc(proc, "notifications/initialized", {}, None)
        listed = _rpc(proc, "tools/list", {}, 2)
        tools = sorted(t["name"] for t in listed.get("result", {}).get("tools", []))
        called = _rpc(proc, "tools/call", {"name": "status", "arguments": {}}, 3)
        content = called.get("result", {}).get("content") or [{}]
        status = json.loads(content[0].get("text") or "{}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    repo = str(status.get("repo") or "")
    want_tools = sorted(t.strip() for t in args.expect_tools.split(",") if t.strip())
    repo_ok = Path(repo).resolve() == Path(args.expect_repo).resolve() if repo else False
    tools_ok = tools == want_tools

    print(json.dumps({"tools": tools, "repo": repo, "engine": status.get("engine")}, indent=2))
    print(
        f"\ntools_ok={tools_ok} (want {want_tools})\n"
        f"repo_ok={repo_ok} (want {args.expect_repo})\n"
        f"=> {'PASS' if tools_ok and repo_ok else 'FAIL'}",
        file=sys.stderr,
    )
    return 0 if (tools_ok and repo_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
