"""End-to-end CLI smoke for installed scubiee (non-destructive)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 120) -> dict:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    parsed = None
    if out.startswith("{"):
        try:
            parsed = json.loads(out)
        except json.JSONDecodeError:
            parsed = None
    return {
        "cmd": " ".join(cmd),
        "exit": proc.returncode,
        "stdout_head": out[:400],
        "stderr_head": err[:400],
        "json_ok": parsed.get("ok") if isinstance(parsed, dict) else None,
    }


def main() -> int:
    scubiee = shutil.which("scubiee") or "scubiee"
    repo = Path(tempfile.mkdtemp(prefix="scubiee-smoke-"))
    (repo / "pkg").mkdir()
    (repo / "pkg" / "app.py").write_text(
        "def greet():\n    return 'hello from smoke test'\n",
        encoding="utf-8",
    )
    print(f"smoke repo: {repo}")

    cases: list[tuple[str, list[str], Path | None, int | None]] = [
        ("version", [scubiee, "--version"], None, 0),
        ("help", [scubiee, "--help"], None, 0),
        ("preflight", [scubiee, "preflight"], None, 0),
        ("setup_status", [scubiee, "setup", "--status"], None, 0),
        ("resources", [scubiee, "resources"], None, 0),
        ("list", [scubiee, "list"], None, 0),
        ("migrate_check", [scubiee, "migrate", "--check-all"], None, 0),
        ("diagnose", [scubiee, "diagnose", "--no-tests"], None, None),
        ("connect_dry", [scubiee, "connect", "--cursor", "--dry-run"], None, 0),
        ("disconnect_dry", [scubiee, "disconnect", "--cursor", "--dry-run"], None, 0),
        ("wipe_all_gate", [scubiee, "wipe", "--all"], None, 2),
        ("engine_status", [scubiee, "engine", "status"], None, 0),
        ("doctor", [scubiee, "doctor", str(repo)], repo, None),
        ("init_fast", [scubiee, "init", str(repo), "--fast", "--roots", "pkg", "--confirm"], repo, 0),
        ("status", [scubiee, "status", str(repo)], repo, 0),
        ("sync", [scubiee, "sync", str(repo), "--confirm"], repo, None),
        ("search", [scubiee, "search", str(repo), "greet"], repo, None),
        ("register_no_index", [scubiee, "register", str(repo), "--no-index"], repo, 0),
        ("certify", [scubiee, "certify", str(repo), "--skip-daemon"], repo, None),
        ("stop", [scubiee, "stop"], None, None),
    ]

    results: list[dict] = []
    failed = 0
    for name, cmd, cwd, expect in cases:
        row = run(cmd, cwd=cwd)
        row["name"] = name
        row["expect"] = expect
        if expect is not None and row["exit"] != expect:
            row["pass"] = False
            failed += 1
        elif expect is None:
            row["pass"] = row["exit"] in {0, 1, 2}
            if not row["pass"]:
                failed += 1
        else:
            row["pass"] = True
        results.append(row)
        mark = "PASS" if row["pass"] else "FAIL"
        print(f"[{mark}] {name}: exit={row['exit']} expect={expect}")

    report = {"repo": str(repo), "failed": failed, "total": len(results), "results": results}
    out_path = Path(__file__).resolve().parent / "_cli_smoke_report.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nreport: {out_path}")
    print(f"summary: {len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
