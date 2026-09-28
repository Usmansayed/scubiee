#!/usr/bin/env python3
"""Run mock upgrade scenarios against the real ``scubiee upgrade`` CLI.

Seeds stale state per scenario, runs ``scubiee upgrade --check`` then
``scubiee upgrade``, and verifies post-conditions.

Usage:
  python scripts/simulate_upgrade_matrix.py --list
  python scripts/simulate_upgrade_matrix.py --scenario stale_mcp_pins
  python scripts/simulate_upgrade_matrix.py --all
  python scripts/simulate_upgrade_matrix.py --all --dry-run   # plan only

Requires an enrolled repo (default: cwd) and ``scubiee`` on PATH.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "packages") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages"))


def _find_scubiee() -> str:
    exe = shutil.which("scubiee")
    if exe:
        return exe
    for candidate in (
        Path(os.environ.get("APPDATA", "")) / "uv" / "tools" / "scubiee" / "Scripts" / "scubiee.exe",
        Path.home() / ".local" / "bin" / "scubiee",
    ):
        if candidate.is_file():
            return str(candidate)
    raise SystemExit("scubiee CLI not found on PATH")


def _run_cli(scubiee: str, args: list[str], *, cwd: Path) -> tuple[int, dict | None, str]:
    cmd = [scubiee, *args]
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    payload: dict | None = None
    stripped = combined.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
    if payload is None:
        for line in reversed(combined.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    payload = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
    if payload is None:
        start = combined.find("{")
        end = combined.rfind("}")
        if start != -1 and end > start:
            try:
                payload = json.loads(combined[start : end + 1])
            except json.JSONDecodeError:
                payload = None
    return proc.returncode, payload, combined


def _project_id(repo: Path) -> str:
    id_path = repo / ".scubiee" / "id.json"
    if not id_path.is_file():
        raise SystemExit(f"Not enrolled: missing {id_path}")
    data = json.loads(id_path.read_text(encoding="utf-8"))
    pid = data.get("project_id")
    if not pid:
        raise SystemExit(f"Invalid id.json at {id_path}")
    return str(pid)


def _installed_version(scubiee: str) -> str:
    proc = subprocess.run(
        [scubiee, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    out = (proc.stdout or proc.stderr or "").strip()
    return out.split()[-1] if out else "unknown"


def run_scenario(
    scenario_id: str,
    *,
    repo: Path,
    scubiee: str,
    dry_run: bool,
    use_temp_home: bool,
) -> dict:
    from pipeline.upgrade_scenarios import apply_stale_state, get_scenario, verify_post_upgrade

    scenario = get_scenario(scenario_id)
    pid = _project_id(repo)
    version = _installed_version(scubiee)
    report: dict = {
        "scenario": scenario_id,
        "label": scenario.label,
        "repo": str(repo),
        "version": version,
        "ok": False,
    }

    temp_home: Path | None = None
    prev_home = os.environ.get("CTX_HOME")
    if use_temp_home:
        temp_home = Path(tempfile.mkdtemp(prefix="scubiee-upgrade-scenario-"))
        os.environ["CTX_HOME"] = str(temp_home)
        os.environ["CTX_ALLOW_TEST_HOME"] = "1"
        # Copy real home essentials so daemon health can still work when not isolated
        real_home = Path(prev_home) if prev_home else Path.home() / ".scubiee"
        if real_home.is_dir():
            for name in ("registry.json", "connected_tools.json", "accel.json", "projects"):
                src = real_home / name
                if src.exists():
                    dest = temp_home / name
                    if src.is_dir():
                        shutil.copytree(src, dest, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dest)

    try:
        seed = apply_stale_state(scenario_id, repo, project_id=pid, version=version)
        report["seed"] = seed

        check_args = ["upgrade", "--check"]
        if scenario.upgrade_flags.get("repair"):
            check_args.append("--repair")
        if scenario.upgrade_flags.get("reindex"):
            check_args.append("--reindex")

        rc, check_json, check_text = _run_cli(scubiee, check_args, cwd=repo)
        report["check_rc"] = rc
        report["check_output_tail"] = check_text[-2000:]
        if check_json:
            report["check_plan"] = check_json.get("plan")

        if dry_run:
            report["ok"] = rc == 0
            report["skipped_apply"] = True
            return report

        apply_args = ["upgrade"]
        if scenario.upgrade_flags.get("repair"):
            apply_args.append("--repair")
        if scenario.upgrade_flags.get("reindex"):
            apply_args.append("--reindex")

        rc, upgrade_json, upgrade_text = _run_cli(scubiee, apply_args, cwd=repo)
        report["upgrade_rc"] = rc
        report["upgrade_output_tail"] = upgrade_text[-4000:]
        if upgrade_json:
            report["upgrade"] = {
                k: upgrade_json.get(k)
                for k in ("ok", "error", "phases", "plan", "rebind", "migration", "embeddings", "health")
            }

        verify = verify_post_upgrade(
            scenario_id,
            repo,
            project_id=pid,
            version=version,
            report=upgrade_json,
        )
        report["verify"] = verify
        health_flake = bool(verify.get("health_flake"))
        report["health_flake"] = health_flake
        report["ok"] = verify.get("ok") is True
        return report
    finally:
        if temp_home is not None:
            if prev_home is None:
                os.environ.pop("CTX_HOME", None)
            else:
                os.environ["CTX_HOME"] = prev_home
            os.environ.pop("CTX_ALLOW_TEST_HOME", None)
            shutil.rmtree(temp_home, ignore_errors=True)


def _safe_print(line: str) -> None:
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", errors="replace").decode("ascii"))


def _accel_ready() -> bool:
    sys.path.insert(0, str(ROOT / "packages"))
    from pipeline.upgrade_scenarios import _embed_rebuild_ready

    return _embed_rebuild_ready()


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate scubiee upgrade scenarios")
    parser.add_argument("--list", action="store_true", help="List scenarios")
    parser.add_argument("--scenario", action="append", dest="scenarios", default=[])
    parser.add_argument("--all", action="store_true", help="Run all scenarios")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Managed repo root")
    parser.add_argument("--dry-run", action="store_true", help="Only run upgrade --check")
    parser.add_argument(
        "--pause-between",
        type=float,
        default=20.0,
        help="Seconds to wait between full-upgrade scenarios (daemon cooldown)",
    )
    parser.add_argument(
        "--isolate-home",
        action="store_true",
        help="Use temp CTX_HOME (copies registry/projects from real home)",
    )
    args = parser.parse_args()

    from pipeline.upgrade_scenarios import list_scenarios

    if args.list:
        for s in list_scenarios():
            flags = ",".join(k for k, v in s.upgrade_flags.items() if v) or "none"
            print(f"{s.id:22}  flags={flags:12}  {s.label}")
            print(f"{'':22}  {s.description}")
        return 0

    ids = [s.id for s in list_scenarios()] if args.all else args.scenarios
    if not ids:
        parser.error("Pass --scenario ID and/or --all (or --list)")

    scubiee = _find_scubiee()
    repo = args.repo.resolve()
    results: list[dict] = []
    failed = 0

    print(f"Using scubiee: {scubiee}")
    print(f"Repo: {repo}")
    print(f"Mode: {'check-only' if args.dry_run else 'full upgrade'}")
    print()

    if not args.dry_run:
        import subprocess as _sp

        pre_env = os.environ.copy()
        pre_env.pop("CTX_HOME", None)
        pre_env.pop("CTX_ALLOW_TEST_HOME", None)
        pre = _sp.run(
            [scubiee, "engine", "start"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=pre_env,
        )
        if pre.returncode != 0:
            _safe_print(f"Warning: engine pre-start returned {pre.returncode}")

    destructive = {"embed_abi_mismatch", "force_reindex"}

    for sid in ids:
        if sid in destructive and not _accel_ready() and not args.dry_run:
            print(f"=== {sid} ===")
            print("  SKIP (requires accel.json — run `scubiee setup` first)")
            print()
            results.append({"scenario": sid, "ok": True, "skipped": True, "reason": "accel_required"})
            continue
        print(f"=== {sid} ===")
        r = run_scenario(
            sid,
            repo=repo,
            scubiee=scubiee,
            dry_run=args.dry_run,
            use_temp_home=args.isolate_home,
        )
        results.append(r)
        status = "PASS" if r.get("ok") else "FAIL"
        if r.get("health_flake"):
            status = "PASS (health pending)"
        print(f"  {status}")
        if not r.get("ok"):
            failed += 1
            if r.get("verify"):
                for c in r["verify"].get("checks") or []:
                    if not c.get("ok"):
                        print(f"    check failed: {c['name']}: {c.get('detail')}")
            tail = r.get("upgrade_output_tail") or r.get("check_output_tail") or ""
            if tail:
                print("    --- output tail ---")
                for line in tail.splitlines()[-8:]:
                    _safe_print(f"    {line}")
        print()
        if not args.dry_run and args.pause_between > 0 and sid != ids[-1]:
            import time

            time.sleep(args.pause_between)

    summary_path = repo / ".scubiee" / "upgrade_scenario_results.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    _safe_print(f"Wrote {summary_path}")
    passed = sum(1 for r in results if r.get("ok"))
    skipped = sum(1 for r in results if r.get("skipped"))
    _safe_print(f"Done: {passed}/{len(results)} passed ({skipped} skipped)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
