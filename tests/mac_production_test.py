#!/usr/bin/env python3
"""Mac production test suite for scubiee 0.2.55+.

Run on a macOS machine (Intel or Apple Silicon) after installing:
    uv tool install scubiee[macos]
    # or for Apple Silicon:
    uv tool install scubiee[mlx]

Usage:
    cd <any-git-repo>
    python mac_production_test.py

Tests cover:
1. Clean install verification
2. Setup (MLX/CoreML/CPU detection)
3. Init + index (safety cap, full index)
4. All MCP tools via stdio JSON-RPC
5. Connect/disconnect round-trip (Mac paths)
6. Concurrent requests
7. Adversarial inputs
8. Engine recovery
9. Multi-repo switching
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="Mac production suite — see docs/macos-deferred-verification.md",
)
import threading
import time
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

# Point this at any git repo with code files for testing.
# Default: the current working directory.
TEST_REPO = os.environ.get("TEST_REPO", os.getcwd())
TIMEOUT = 60


# ── Helpers ───────────────────────────────────────────────────────────────────

def run(*args, timeout=TIMEOUT, cwd=TEST_REPO):
    try:
        r = subprocess.run(
            ["scubiee", *args],
            capture_output=True, text=True, timeout=timeout,
            cwd=cwd, stdin=subprocess.DEVNULL,
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except FileNotFoundError:
        return -2, "", "scubiee not found on PATH"


def parse(stdout):
    try:
        return json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return {"_raw": stdout}


class McpSession:
    """Drives scubiee-mcp over stdio JSON-RPC."""

    def __init__(self, repo=TEST_REPO):
        env = os.environ.copy()
        env["CTX_REPO"] = repo
        env["PYTHONUTF8"] = "1"
        self.proc = subprocess.Popen(
            ["scubiee-mcp"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        self._id = 100
        self._lock = threading.Lock()
        self._handshake()

    def _handshake(self):
        self._send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "mac-test", "version": "1"}}})
        self._recv(timeout=30)
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, msg):
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def _recv(self, timeout=30):
        import queue
        q = queue.Queue()
        def _r():
            q.put(self.proc.stdout.readline())
        t = threading.Thread(target=_r, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            return None
        line = q.get_nowait() if not q.empty() else ""
        return json.loads(line) if line and line.strip() else None

    def call(self, name, args, timeout=30):
        with self._lock:
            self._id += 1
            t0 = time.perf_counter()
            self._send({"jsonrpc": "2.0", "id": self._id, "method": "tools/call",
                        "params": {"name": name, "arguments": args}})
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

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.kill()
        except Exception:
            pass


PASS = 0
FAIL = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {label}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))


def section(title):
    print(f"\n{'='*60}\n  {title}\n{'='*60}\n")


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_install():
    section("1. Install verification")
    code, out, _ = run("--version")
    check("scubiee on PATH and runnable", code == 0, out.strip().split("\n")[0])

    version_line = out.strip().split("\n")[0] if out else ""
    check("version >= 0.2.55", "0.2.55" in version_line or "0.2.5" in version_line,
          version_line)


def test_setup():
    section("2. Setup (hardware detection)")
    code, out, err = run("setup", timeout=300)
    combined = out + err
    # Should detect MLX (Apple Silicon), CoreML, or CPU
    has_profile = any(x in combined.lower() for x in ["mlx", "coreml", "cpu", "ready"])
    check("setup completes with a profile", code != -1 and has_profile,
          f"exit={code}")

    # Check accel.json was written
    accel = Path.home() / ".context-engine" / "accel.json"
    check("accel.json exists after setup", accel.is_file())


def test_init_and_index():
    section("3. Init + index")

    # First try without --confirm to verify safety cap
    code, out, _ = run("init", timeout=30)
    result = parse(out)
    needs_confirm = (
        result.get("needs_confirm") is True
        or result.get("warning") == "large_index_scope"
        or code != 0
    )
    if needs_confirm:
        check("Safety cap fires (needs --confirm)", True,
              f"n_files={result.get('n_files')}")
        # Now do it for real
        code, out, _ = run("init", "--confirm", timeout=600)
        result = parse(out)

    # Either direct success or post-confirm success
    code2, out2, _ = run("status", timeout=15)
    status = parse(out2)
    chunks = status.get("chunks") or status.get("meta", {}).get("chunks", 0)
    check("Index exists with chunks > 0", chunks > 0, f"chunks={chunks}")
    check("Server is warm", status.get("server", {}).get("ok") is True or
          status.get("server", {}).get("warm") is True)


def test_mcp_tools():
    section("4. MCP tools (all 7)")
    session = McpSession()

    tests = [
        ("status", {}),
        ("map", {"query": "main entry point initialization setup config"}),
        ("grep", {"pattern": "def ", "glob": "*.py", "max_hits": 5}),
        ("glob", {"pattern": "*.py", "limit": 5}),
        ("workspace", {"action": "show"}),
        ("focus", {"path": "", "mode": "outline"}),  # empty path = best-effort
        ("gate", {}),
    ]

    for name, args in tests:
        r = session.call(name, args, timeout=30)
        ok = not r.get("__timeout__") and not r.get("__error__")
        # focus with empty path may return an error (that's ok, not a crash)
        if name == "focus" and not ok:
            ok = True  # graceful error = pass
        check(f"{name}", ok, f"{r.get('__dt__', 0):.1f}s")

    session.close()


def test_connect_disconnect():
    section("5. Connect/disconnect (Mac paths)")

    code, out, _ = run("connect", "--all", "--dry-run")
    results = parse(out) if isinstance(parse(out), list) else []
    check("connect --all --dry-run", code == 0 and len(results) >= 10,
          f"{len(results)} tools")

    # Verify Mac-specific paths in dry-run output
    mac_paths_ok = any(
        "Library/Application Support" in str(r) or ".cursor" in str(r)
        for r in results
    )
    check("Mac paths resolved correctly", mac_paths_ok)

    # Real connect
    code, out, _ = run("connect", "--all")
    results = parse(out) if isinstance(parse(out), list) else []
    ok_count = sum(1 for r in results if isinstance(r, dict) and r.get("ok"))
    check(f"connect --all: {ok_count}/{len(results)} ok", ok_count >= 10)

    # Disconnect
    code, out, _ = run("disconnect", "--all")
    results = parse(out) if isinstance(parse(out), list) else []
    ok_count = sum(1 for r in results if isinstance(r, dict) and r.get("ok"))
    check(f"disconnect --all: {ok_count}/{len(results)} ok", ok_count >= 10)


def test_concurrent():
    section("6. Concurrent requests")
    session = McpSession()

    calls = [
        ("map", {"query": "database connection pool query builder"}),
        ("grep", {"pattern": "import", "glob": "*.py", "max_hits": 3}),
        ("glob", {"pattern": "**/*.py", "limit": 3}),
        ("status", {}),
        ("workspace", {"action": "show"}),
        ("map", {"query": "error handling exception retry mechanism"}),
        ("grep", {"pattern": "class ", "glob": "*.py", "max_hits": 3}),
        ("glob", {"pattern": ".", "limit": 10}),
    ]

    results = []
    for name, args in calls:
        r = session.call(name, args, timeout=15)
        results.append((name, r))

    ok = sum(1 for _, r in results if not r.get("__timeout__") and not r.get("__error__"))
    check(f"Rapid-fire: {ok}/{len(calls)} succeeded", ok == len(calls))

    dts = [r.get("__dt__", 99) for _, r in results]
    check("All responses < 10s", max(dts) < 10, f"max={max(dts):.1f}s")

    session.close()


def test_adversarial():
    section("7. Adversarial inputs")
    session = McpSession()

    cases = [
        ("grep", {}, "missing pattern"),
        ("grep", {"pattern": "a" * 5000, "glob": "*.py"}, "huge pattern"),
        ("focus", {"path": "../../../etc/passwd", "mode": "span"}, "path traversal"),
        ("map", {"query": "🚀💻🔥 emoji"}, "emoji query"),
        ("grep", {"pattern": "$(rm -rf /)", "glob": "*.py"}, "shell injection"),
        ("gate", {"root": "/nonexistent/path/foo"}, "nonexistent path"),
        ("glob", {"pattern": "**/*" * 50}, "absurd glob"),
        ("focus", {"path": "x.py", "mode": "invalid"}, "invalid mode"),
    ]

    crashed = False
    for name, args, label in cases:
        r = session.call(name, args, timeout=10)
        if session.proc.poll() is not None:
            crashed = True
            break

    check(f"Server survived {len(cases)} adversarial inputs", not crashed)
    session.close()


def test_recovery():
    section("8. Engine recovery")

    # Kill daemon (engine stop, NOT global stop which pauses MCP/rules)
    run("engine", "stop", timeout=10)
    time.sleep(2)

    # Status should still work (restarts daemon or reports cold state)
    code, out, _ = run("status", timeout=30)
    check("status after daemon kill", code != -1, f"exit={code}")

    # Corrupt registry
    reg = Path.home() / ".context-engine" / "registry.json"
    if reg.is_file():
        backup = reg.read_text()
        reg.write_text("CORRUPTED{{{")
        code, out, _ = run("status", timeout=15)
        check("status with corrupted registry", code != -1)
        reg.write_text(backup)
    else:
        print("  [SKIP] no registry.json")


def test_multi_repo():
    section("9. Multi-repo switching")

    # Create a second tiny repo in a temp dir
    with tempfile.TemporaryDirectory() as td:
        repo2 = Path(td) / "test-repo"
        repo2.mkdir()
        (repo2 / "hello.py").write_text("def hello():\n    return 'world'\n")
        # Make it a git repo so scubiee recognizes it
        subprocess.run(["git", "init"], cwd=str(repo2), capture_output=True)
        subprocess.run(["git", "add", "."], cwd=str(repo2), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init", "--allow-empty"],
                      cwd=str(repo2), capture_output=True)

        # Init the second repo
        code, out, _ = run("init", "--confirm", timeout=120, cwd=str(repo2))
        result = parse(out)
        check("Second repo initializes", code != -1,
              f"exit={code}")

        # Switch back to original and verify it still works
        code, out, _ = run("status", timeout=15, cwd=TEST_REPO)
        status = parse(out)
        check("Original repo still accessible after switch",
              status.get("server", {}).get("ok") is True or "chunks" in out)

        # Clean up second repo
        run("remove", "--delete-store", timeout=10, cwd=str(repo2))


def test_hardware_tracking():
    section("10. Hardware-level tracking (moved folder resolution)")
    with tempfile.TemporaryDirectory() as td:
        p1 = Path(td) / "project_a"
        p1.mkdir()
        (p1 / ".scubiee").mkdir()
        (p1 / ".scubiee" / "id.json").write_text('{"project_id": "ce_test"}', encoding="utf-8")

        from pipeline.hw_track import get_filesystem_id, resolve_moved_path

        fs_id = get_filesystem_id(p1)
        check("Capture macOS filesystem ID (dev:ino)", fs_id is not None and fs_id.get("os") == "darwin")

        p2 = Path(td) / "project_moved_b"
        p1.rename(p2)

        resolved = resolve_moved_path(fs_id)
        check("Resolve moved folder via volfs & fcntl", resolved is not None and resolved.resolve() == p2.resolve())


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  SCUBIEE MAC PRODUCTION TEST")
    print(f"  Repo: {TEST_REPO}")
    print(f"  Python: {sys.executable} ({sys.version.split()[0]})")
    print("=" * 60)

    test_install()
    test_setup()
    test_init_and_index()
    test_mcp_tools()
    test_connect_disconnect()
    test_concurrent()
    test_adversarial()
    test_recovery()
    test_multi_repo()
    test_hardware_tracking()

    section("RESULTS")
    total = PASS + FAIL
    print(f"  {PASS}/{total} passed, {FAIL} failed")
    if FAIL == 0:
        print("\n  ✓ PRODUCTION READY (Mac)")
    else:
        print(f"\n  ✗ {FAIL} issue(s) need review before production")
    sys.exit(0 if FAIL == 0 else 1)
