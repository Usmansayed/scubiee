"""Real CLI: mock Figma neighbor + scubiee connect/disconnect for all 13 tools."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

NEIGHBOR = "figma"
SERVER = "scubiee"
LOG_PATH = Path(__file__).resolve().parent / "_mcp_merge_cli_results.txt"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("CTX_HOME", None)
    parts: list[str] = []
    if platform.system() == "Windows":
        appdata = env.get("APPDATA", "")
        profile = env.get("USERPROFILE", "")
        parts.extend([f"{appdata}\\uv\\tools\\scubiee\\Scripts", f"{profile}\\.local\\bin"])
    else:
        home = env.get("HOME", str(Path.home()))
        parts.append(f"{home}/.local/bin")
    parts.append(env.get("Path", env.get("PATH", "")))
    env["Path"] = ";".join(parts) if platform.system() == "Windows" else ":".join(parts)
    if platform.system() != "Windows":
        env["PATH"] = env["Path"]
    return env


def log(msg: str) -> None:
    line = msg.rstrip()
    print(line)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(repo: Path, cmd: list[str]) -> None:
    r = subprocess.run(cmd, cwd=repo, env=_env(), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd} exit {r.returncode}\n{(r.stderr or r.stdout)[:600]}")


def vjson(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def vtoml(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            if "[mcp_servers." not in raw:
                raise ValueError(f"not valid codex mcp toml: {path}") from None
            return
    try:
        tomllib.loads(raw)
    except TypeError:
        tomllib.loads(raw.encode("utf-8"))


def vyaml(path: Path) -> None:
    try:
        import yaml  # type: ignore
    except ImportError:
        # minimal check: file exists and has mcpServers
        text = path.read_text(encoding="utf-8")
        if "mcpServers" not in text:
            raise ValueError(f"no mcpServers in {path}")
        return
    yaml.safe_load(path.read_text(encoding="utf-8"))


def _roundtrip_json_mcp(
    repo: Path,
    slug: str,
    path: Path,
    key: str,
    seed: dict[str, Any],
    *,
    nested_key: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")
    vjson(path)
    run(repo, ["scubiee", "connect", f"--{slug}"])
    vjson(path)
    data = vjson(path)
    bucket = data[nested_key] if nested_key else data[key]
    assert NEIGHBOR in bucket and SERVER in bucket, f"{slug} after connect: {list(bucket)}"
    run(repo, ["scubiee", "disconnect", f"--{slug}"])
    vjson(path)
    data = vjson(path)
    bucket = data[nested_key] if nested_key else data[key]
    assert NEIGHBOR in bucket and SERVER not in bucket, f"{slug} after disconnect: {list(bucket)}"
    log(f"{slug} OK  {path}")


def test_cursor(repo: Path) -> None:
    _roundtrip_json_mcp(
        repo,
        "cursor",
        repo / ".cursor" / "mcp.json",
        "mcpServers",
        {
            "mcpServers": {
                NEIGHBOR: {
                    "url": "https://mcp.figma.com/mcp",
                    "headers": {"Authorization": "Bearer MOCK"},
                }
            }
        },
    )


def test_claude_code(repo: Path) -> None:
    _roundtrip_json_mcp(
        repo,
        "claude-code",
        repo / ".mcp.json",
        "mcpServers",
        {"mcpServers": {NEIGHBOR: {"command": "npx", "args": ["-y", "figma-mcp"]}}},
    )


def test_pi(repo: Path) -> None:
    _roundtrip_json_mcp(
        repo,
        "pi",
        repo / ".mcp.json",
        "mcpServers",
        {"mcpServers": {NEIGHBOR: {"command": "npx", "args": ["-y", "figma-mcp"]}}},
    )


def test_kiro(repo: Path) -> None:
    _roundtrip_json_mcp(
        repo,
        "kiro",
        repo / ".kiro" / "settings" / "mcp.json",
        "mcpServers",
        {"mcpServers": {NEIGHBOR: {"command": "node", "args": ["figma.js"]}}},
    )


def test_devin(repo: Path) -> None:
    _roundtrip_json_mcp(
        repo,
        "devin-desktop",
        repo / ".devin" / "mcp_config.json",
        "mcpServers",
        {"mcpServers": {NEIGHBOR: {"command": "node", "args": ["figma.js"]}}},
    )


def test_cline(repo: Path) -> None:
    _roundtrip_json_mcp(
        repo,
        "cline",
        repo / ".cline" / "mcp.json",
        "mcpServers",
        {"mcpServers": {NEIGHBOR: {"command": "node", "args": ["figma.js"]}}},
    )


def test_roo(repo: Path) -> None:
    _roundtrip_json_mcp(
        repo,
        "roo-code",
        repo / ".roo" / "mcp.json",
        "mcpServers",
        {"mcpServers": {NEIGHBOR: {"command": "node", "args": ["figma.js"]}}},
    )


def test_zed(repo: Path) -> None:
    _roundtrip_json_mcp(
        repo,
        "zed",
        repo / ".zed" / "settings.json",
        "context_servers",
        {"context_servers": {NEIGHBOR: {"command": "node", "args": ["figma.js"]}}},
    )


def test_amp(repo: Path) -> None:
    _roundtrip_json_mcp(
        repo,
        "amp",
        repo / ".amp" / "settings.json",
        "amp.mcpServers",
        {"amp.mcpServers": {NEIGHBOR: {"command": "node", "args": ["figma.js"]}}},
        nested_key="amp.mcpServers",
    )


def test_opencode(repo: Path) -> None:
    _roundtrip_json_mcp(
        repo,
        "opencode",
        repo / "opencode.json",
        "mcp",
        {
            "$schema": "https://opencode.ai/config.json",
            "mcp": {
                NEIGHBOR: {
                    "type": "local",
                    "enabled": True,
                    "command": ["npx", "-y", "figma-mcp"],
                }
            },
        },
    )


def test_copilot(repo: Path) -> None:
    vscode = repo / ".vscode" / "mcp.json"
    root = repo / ".mcp.json"
    vscode.parent.mkdir(parents=True, exist_ok=True)
    vscode.write_text(
        json.dumps(
            {"servers": {NEIGHBOR: {"type": "stdio", "command": "node", "args": ["figma.js"]}}},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    root.write_text(
        json.dumps({"mcpServers": {NEIGHBOR: {"command": "node", "args": ["figma.js"]}}}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    vjson(vscode)
    vjson(root)
    run(repo, ["scubiee", "connect", "--copilot"])
    vjson(vscode)
    vjson(root)
    vs = vjson(vscode)["servers"]
    rm = vjson(root)["mcpServers"]
    assert NEIGHBOR in vs and SERVER in vs
    assert NEIGHBOR in rm and SERVER in rm
    run(repo, ["scubiee", "disconnect", "--copilot"])
    vjson(vscode)
    vjson(root)
    vs = vjson(vscode)["servers"]
    rm = vjson(root)["mcpServers"]
    assert NEIGHBOR in vs and SERVER not in vs
    assert NEIGHBOR in rm and SERVER not in rm
    log(f"copilot OK  {vscode} + {root}")


def test_codex(repo: Path) -> None:
    path = repo / ".codex" / "config.toml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        '[model]\nname = "gpt-4"\n\n[mcp_servers.figma]\ncommand = "npx"\nargs = ["figma-mcp"]\n',
        encoding="utf-8",
    )
    vtoml(path)
    run(repo, ["scubiee", "connect", "--codex"])
    vtoml(path)
    text = path.read_text(encoding="utf-8")
    assert "mcp_servers.figma" in text and "mcp_servers.scubiee" in text
    run(repo, ["scubiee", "disconnect", "--codex"])
    vtoml(path)
    text = path.read_text(encoding="utf-8")
    assert "mcp_servers.figma" in text and "mcp_servers.scubiee" not in text
    log(f"codex OK  {path}")


def test_continue(repo: Path) -> None:
    neighbor = repo / ".continue" / "mcpServers" / f"{NEIGHBOR}.yaml"
    scubiee_path = repo / ".continue" / "mcpServers" / "scubiee.yaml"
    neighbor.parent.mkdir(parents=True, exist_ok=True)
    neighbor.write_text(
        "name: Figma\nversion: 0.0.1\nschema: v1\nmcpServers:\n"
        "  - name: figma\n    command: npx\n    args: [figma-mcp]\n",
        encoding="utf-8",
    )
    vyaml(neighbor)
    run(repo, ["scubiee", "connect", "--continue"])
    assert scubiee_path.is_file()
    vyaml(scubiee_path)
    assert neighbor.is_file()
    run(repo, ["scubiee", "disconnect", "--continue"])
    assert not scubiee_path.is_file()
    vyaml(neighbor)
    log(f"continue OK  {neighbor} (neighbor kept, scubiee.yaml removed)")


TESTS: list[tuple[str, Callable[[Path], None]]] = [
    ("cursor", test_cursor),
    ("claude-code", test_claude_code),
    ("codex", test_codex),
    ("kiro", test_kiro),
    ("devin-desktop", test_devin),
    ("copilot", test_copilot),
    ("cline", test_cline),
    ("roo-code", test_roo),
    ("continue", test_continue),
    ("zed", test_zed),
    ("opencode", test_opencode),
    ("amp", test_amp),
    ("pi", test_pi),
]


def main() -> int:
    repo = Path(".").resolve()
    LOG_PATH.write_text(
        f"=== MCP merge CLI (mock {NEIGHBOR}) {datetime.now(timezone.utc).isoformat()} ===\n"
        f"Repo: {repo}\n",
        encoding="utf-8",
    )
    if not (repo / ".scubiee" / "id.json").is_file():
        log("[setup] enrolling repo...")
        run(repo, ["scubiee", "setup", "--repair"])
        run(repo, ["scubiee", "init", "."])

    passed: list[str] = []
    failed: list[str] = []
    for name, fn in TESTS:
        log(f"\n--- {name} ---")
        try:
            fn(repo)
            passed.append(name)
        except Exception as exc:
            log(f"FAIL {name}: {exc!r}")
            failed.append(name)

    log(f"\n=== SUMMARY: {len(passed)}/{len(TESTS)} passed ===")
    for n in passed:
        log(f"  PASS {n}")
    for n in failed:
        log(f"  FAIL {n}")
    log(f"Log: {LOG_PATH}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
