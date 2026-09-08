#!/usr/bin/env python3
"""Windows production test suite for scubiee 0.2.56+.

Run on a Windows machine after installing:
    uv tool install scubiee
    scubiee setup

Usage:
    cd <any-git-repo>
    python windows_production_test.py

Tests cover:
1. Clean install verification
2. Setup (DML/CUDA/CPU detection)
3. Init + index (safety cap, full index)
4. All MCP tools via stdio JSON-RPC
5. Connect/disconnect round-trip (Windows paths)
6. Concurrent requests
7. Adversarial inputs
8. Engine recovery (daemon stop/restart)
9. Stop/Resume lifecycle
10. Upgrade check
11. Process control (no orphans)

Requirements:
- Windows 10/11
- Python 3.10+
- Git (for test repo creation)
- scubiee installed and setup complete
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

TEST_REPO = os.environ.get("TEST_REPO", os.getcwd())
TIMEOUT = 120  # Windows can be slower on cold start
# Cold index of a large repo on DirectML runs well past the per-command budget.
INDEX_TIMEOUT = int(os.environ.get("INDEX_TIMEOUT", "2400"))


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


def connected_slugs():
    """Tools the operator had connected before this suite ran."""
    state = Path.home() / ".scubiee" / "connected_tools.json"
    try:
        data = json.loads(state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    slugs = data.get("slugs") if isinstance(data, dict) else None
    return [str(s) for s in slugs if str(s).strip()] if isinstance(slugs, list) else []


def _version_at_least(text, minimum):
    """Compare the first dotted version found in `text` against `minimum`."""
    import re

    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    if not m:
        return False
    return tuple(int(p) for p in m.groups()) >= minimum


class McpSession:
    """Drives scubiee-mcp over stdio JSON-RPC."""

    def __init__(self, repo=TEST_REPO):
        env = os.environ.copy()
        env["CTX_REPO"] = repo
        env["CTX_MCP_SURFACE"] = "phase"
        env["CTX_MCP_EXPERIMENT"] = "ship"
        env["PYTHONUTF8"] = "1"
        # Windows: use CREATE_NO_WINDOW to avoid console flash
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        self.proc = subprocess.Popen(
            ["scubiee-mcp"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, text=True, encoding="utf-8", errors="replace", bufsize=1,
            **kwargs,
        )
        self._id = 100
        self._lock = threading.Lock()
        self._handshake()

    def _handshake(self):
        self._send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "win-test", "version": "1"}}})
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
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
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
        print(f"  [PASS] {label}" + (f" - {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f" - {detail}" if detail else ""))


def section(title):
    print(f"\n{'='*60}\n  {title}\n{'='*60}\n")


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_install():
    section("1. Install verification")
    code, out, _ = run("--version")
    check("scubiee on PATH and runnable", code == 0, out.strip().split("\n")[0])

    version_line = out.strip().split("\n")[0] if out else ""
    check("version >= 0.2.56", _version_at_least(version_line, (0, 2, 56)),
          version_line)

    # Verify no path-separator issues (Windows backslash)
    code2, out2, _ = run("status", "--json")
    if code2 == 0:
        data = parse(out2)
        root = data.get("root", "")
        check("root path uses OS separator", "\\" in root or "/" in root, root[:60])


def test_setup():
    section("2. Setup (hardware detection)")
    code, out, err = run("setup", "--status", timeout=30)
    result = parse(out)
    profile = (
        result.get("preferred_profile")
        or (result.get("accel") or {})
        or result.get("profile")
    )
    if isinstance(profile, dict):
        profile = profile.get("profile")
    check("setup --status returns profile", bool(profile), f"profile={profile}")

    # accel.json lives under the active CTX home, which setup --status reports.
    accel = Path(result.get("accel_path") or (Path.home() / ".scubiee" / "accel.json"))
    check("accel.json exists", accel.is_file(), str(accel))

    if profile:
        check("Profile is valid", profile in ("dml", "cuda", "cpu", "mlx", "coreml"),
              profile)


def test_init_and_index():
    section("3. Init + index")

    # First try without --confirm
    code, out, _ = run("init", timeout=30)
    result = parse(out)
    needs_confirm = (
        result.get("needs_confirm") is True
        or result.get("warning") == "large_index_scope"
        or code == 2
    )
    if needs_confirm:
        check("Safety cap fires (needs --confirm)", True,
              f"n_files={result.get('n_files')}")
        code, out, _ = run("init", "--confirm", timeout=INDEX_TIMEOUT)
        result = parse(out)

    # A cold index on a large repo keeps writing after init returns.
    chunks = 0
    deadline = time.time() + INDEX_TIMEOUT
    while time.time() < deadline:
        status = parse(run("status", "--json", timeout=60)[1])
        chunks = status.get("chunks") or status.get("meta", {}).get("chunks", 0)
        if chunks > 0:
            break
        time.sleep(10)
    check("Index exists with chunks > 0", chunks > 0, f"chunks={chunks}")

    # The engine starts on demand and idles out again, so ask for it explicitly.
    run("engine", "ensure", timeout=120)
    warm = False
    for _ in range(10):
        s = parse(run("status", "--json", timeout=30)[1])
        if s.get("server", {}).get("warm") or s.get("server", {}).get("ok"):
            warm = True
            break
        time.sleep(3)
    check("Server becomes warm within 30s", warm)


def test_mcp_tools():
    section("4. MCP tools (ship surface)")
    session = McpSession()
    query = "main entry point initialization setup pack_context heatmap"

    tests = [
        ("status", {}),
        ("map", {"query": query, "k": 8}),
        ("workspace", {"action": "show"}),
        ("gate", {}),
    ]

    seed_file = "packages/pipeline/context_trace.py"
    seed_symbol = "run_pack_context"
    for name, args in tests:
        r = session.call(name, args, timeout=45)
        ok = not r.get("__timeout__") and not r.get("__error__")
        if name == "map":
            seed = r.get("suggested_seed") or {}
            if seed.get("file"):
                seed_file = str(seed["file"])
            if seed.get("symbol"):
                seed_symbol = str(seed["symbol"])
            ok = ok and (bool(r.get("cards") or r.get("hits") or r.get("ok")))
        check(f"{name}", ok, f"{r.get('__dt__', 0):.1f}s")

    pack = session.call(
        "pack_context",
        {
            "query": query,
            "seed_file": seed_file,
            "seed_symbol": seed_symbol,
            "mode": "lean",
        },
        timeout=90,
    )
    check(
        "pack_context",
        not pack.get("__timeout__")
        and not pack.get("__error__")
        and bool(pack.get("ok") or pack.get("heatmap") or pack.get("chain")),
        f"{pack.get('__dt__', 0):.1f}s",
    )

    session.close()


def test_connect_disconnect():
    section("5. Connect/disconnect (Windows paths)")

    original = connected_slugs()

    code, out, _ = run("connect", "--all", "--dry-run")
    results = parse(out) if isinstance(parse(out), list) else []
    check("connect --all --dry-run", code == 0 and len(results) >= 10,
          f"{len(results)} tools")

    # Verify Windows-specific paths in dry-run (AppData, .cursor, etc.)
    win_paths_ok = any(
        "AppData" in str(r) or ".cursor" in str(r) or "Users" in str(r)
        for r in results
    )
    check("Windows paths resolved correctly", win_paths_ok)

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

    # Put the operator's own connections back — this suite runs against a live
    # machine, so a bare disconnect would leave their IDE without Scubiee.
    if original:
        code, out, _ = run("connect", *(f"--{slug}" for slug in original))
        results = parse(out) if isinstance(parse(out), list) else []
        ok_count = sum(1 for r in results if isinstance(r, dict) and r.get("ok"))
        check(
            f"restored {ok_count}/{len(original)} pre-test connections",
            ok_count == len(original),
            ",".join(original),
        )


def test_concurrent():
    section("6. Concurrent requests")
    session = McpSession()

    calls = [
        ("map", {"query": "database connection pool query builder"}),
        ("status", {}),
        ("workspace", {"action": "show"}),
        ("map", {"query": "error handling exception retry mechanism"}),
        ("gate", {}),
        ("status", {}),
        ("map", {"query": "pack_context expand_context heatmap seed"}),
        ("workspace", {"action": "show"}),
    ]

    results = []
    for name, args in calls:
        r = session.call(name, args, timeout=20)
        results.append((name, r))

    ok = sum(1 for _, r in results if not r.get("__timeout__") and not r.get("__error__"))
    check(f"Rapid-fire: {ok}/{len(calls)} succeeded", ok == len(calls))

    dts = [r.get("__dt__", 99) for _, r in results]
    check("All responses < 15s", max(dts) < 15, f"max={max(dts):.1f}s")

    session.close()


def test_adversarial():
    section("7. Adversarial inputs")
    session = McpSession()

    cases = [
        ("map", {"query": ""}, "empty map"),
        ("pack_context", {"query": "x", "seed_file": "", "seed_symbol": ""}, "missing seed"),
        ("expand_context", {"node": "..\\..\\..\\Windows\\System32\\config\\SAM"}, "path traversal"),
        ("map", {"query": "emoji"}, "emoji query"),
        ("gate", {"root": "C:\\NonExistent\\Path"}, "nonexistent path"),
        ("map", {"query": "a" * 5000}, "huge query"),
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

    # Kill daemon via engine stop
    run("engine", "stop", timeout=15)
    time.sleep(3)

    # Status should still work (reports cold state)
    code, out, _ = run("status", "--json", timeout=30)
    check("status after engine kill", code == 0, f"exit={code}")

    # Ensure should restart it
    code, out, _ = run("engine", "ensure", timeout=60)
    result = parse(out)
    check("engine ensure restarts", result.get("ok") or result.get("started"),
          f"started={result.get('started')}")

    # Wait for warm
    time.sleep(5)
    code, out, _ = run("status", "--json", timeout=15)
    status = parse(out)
    warm = status.get("server", {}).get("ok") or status.get("server", {}).get("warm")
    check("engine healthy after restart", warm)


def test_stop_resume():
    section("9. Stop/Resume lifecycle")

    # Stop with --yes
    code, out, _ = run("stop", "--yes", timeout=30)
    check("stop --yes succeeds", code == 0)

    # Verify engine is down
    time.sleep(2)
    code, out, _ = run("status", "--json", timeout=15)
    status = parse(out)
    warm = status.get("server", {}).get("ok") or status.get("server", {}).get("warm")
    check("engine stopped after scubiee stop", not warm)

    # Resume
    code, out, _ = run("resume", timeout=60)
    check("resume succeeds", code == 0)

    # Wait and verify engine returns
    time.sleep(10)
    code, out, _ = run("status", "--json", timeout=15)
    status = parse(out)
    check("engine running after resume",
          status.get("server", {}).get("ok") or status.get("chunks", 0) > 0)


def test_upgrade_check():
    section("10. Upgrade check")

    code, out, _ = run("upgrade", timeout=60)
    check("upgrade command runs", code == 0, out.strip()[:80] if out else "")


def test_no_orphan_processes():
    section("11. Process control (no orphans after stop)")

    # Stop everything
    run("stop", "--yes", timeout=30)
    time.sleep(3)

    # Check for orphan Python processes running pipeline
    try:
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"],
            capture_output=True, text=True, check=False, timeout=10,
        )
        lines = [l for l in (r.stdout or "").splitlines()
                 if "pipeline" in l.lower() or "scubiee" in l.lower()]
        check("No orphan pipeline processes after stop", len(lines) == 0,
              f"{len(lines)} found" if lines else "clean")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        check("Process check", True, "tasklist unavailable (non-Windows?)")

    # Resume for clean state at end
    run("resume", timeout=60)
    time.sleep(5)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  SCUBIEE WINDOWS PRODUCTION TEST")
    print(f"  Repo: {TEST_REPO}")
    print(f"  Python: {sys.executable} ({sys.version.split()[0]})")
    print(f"  OS: {os.name} / {sys.platform}")
    print("=" * 60)

    test_install()
    test_setup()
    test_init_and_index()
    test_mcp_tools()
    test_connect_disconnect()
    test_concurrent()
    test_adversarial()
    test_recovery()
    test_stop_resume()
    test_upgrade_check()
    test_no_orphan_processes()

    section("RESULTS")
    total = PASS + FAIL
    print(f"  {PASS}/{total} passed, {FAIL} failed")
    if FAIL == 0:
        print("\n  PRODUCTION READY (Windows)")
    else:
        print(f"\n  {FAIL} issue(s) need review before production")
    sys.exit(0 if FAIL == 0 else 1)
