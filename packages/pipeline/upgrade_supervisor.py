"""Version-aware Upgrade Supervisor for Scubiee.

Phases: DETECT → PLAN → SNAPSHOT → QUIESCE → SWAP → MIGRATE → REBIND → HEALTH → COMMIT|ROLLBACK
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from pipeline.upgrade_manifest import (
    DiffPlan,
    build_diff_plan,
    record_component_applied,
)
from pipeline.upgrade_platform import (
    ensure_daemon_after_upgrade,
    health_check,
    package_swap_commands,
    platform_name,
    quiesce_for_upgrade,
)


def _home() -> Path:
    from pipeline.project_id import context_engine_home

    return context_engine_home()


def dirty_marker_path() -> Path:
    return _home() / "upgrade.in_progress.json"


def write_dirty_marker(payload: dict[str, Any]) -> None:
    path = dirty_marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def clear_dirty_marker() -> None:
    path = dirty_marker_path()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def load_dirty_marker() -> dict[str, Any] | None:
    path = dirty_marker_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _revision_dir(revision_id: str) -> Path:
    return _home() / "upgrade" / revision_id


def snapshot_for_rollback(*, revision_id: str, old_version: str) -> dict[str, Any]:
    """Snapshot connect state + accel marker for rollback (indexes pointer-only in v1)."""
    dest = _revision_dir(revision_id)
    dest.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"ok": True, "path": str(dest), "copied": []}
    meta = {
        "revision_id": revision_id,
        "old_version": old_version,
        "platform": platform_name(),
        "created_at": time.time(),
    }
    (dest / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    report["copied"].append("meta.json")

    for name in ("connected_tools.json", "accel.json", "update_check.json"):
        src = _home() / name
        if src.is_file():
            shutil.copy2(src, dest / name)
            report["copied"].append(name)
    return report


def _run_cmd(cmd: list[str], *, timeout: float = 180.0) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "cmd": cmd, "error": "timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "cmd": cmd, "error": str(exc)}
    combined = ((proc.stdout or "") + (proc.stderr or "")).lower()
    return {
        "ok": proc.returncode == 0,
        "cmd": cmd,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "").strip()[-400:],
        "stderr": (proc.stderr or "").strip()[-400:],
        "access_denied": "access is denied" in combined or "os error 5" in combined,
    }


def swap_package(*, pre_release: bool = False) -> dict[str, Any]:
    """Install new package via channel-aware force path."""
    from pipeline.process_control import unlock_uv_tool_env

    attempts: list[dict[str, Any]] = []
    cmds = package_swap_commands(pre_release=pre_release)
    for cmd in cmds:
        result = _run_cmd(cmd)
        attempts.append(result)
        if result.get("ok"):
            return {"ok": True, "attempts": attempts, "cmd": cmd}
        if result.get("access_denied"):
            unlock = unlock_uv_tool_env()
            attempts.append({"unlock": unlock})
            # Retry same cmd once after unlock
            retry = _run_cmd(cmd)
            attempts.append(retry)
            if retry.get("ok"):
                return {"ok": True, "attempts": attempts, "cmd": cmd, "unlocked": True}
    return {
        "ok": False,
        "error": "package_upgrade_failed",
        "attempts": attempts,
        "hint": (
            "Windows file lock on uv tool dir. Quit Cursor MCP, run "
            "`scubiee unlock-tool`, then retry. Admin will not help."
        ),
    }


def migrate_indexes() -> dict[str, Any]:
    from pipeline.migrate import migrate_all

    return migrate_all()


def rebuild_embeddings_if_needed(plan: DiffPlan) -> dict[str, Any]:
    """Shadow-style: force rebuild enrolled repos when plan says rebuild.

    Keeps prior index until rebuild succeeds (indexer force=True writes in place
    but we record intent; full blue/green lands in a later revision).
    """
    action = plan.action_for("embeddings")
    if action is None or action.action == "skip":
        return {"ok": True, "skipped": True, "reason": "embeddings unchanged"}

    from pipeline.managed_repos import managed_repo_paths

    reports: list[dict[str, Any]] = []
    ok = True
    for repo in managed_repo_paths(enrolled_only=True):
        try:
            from pipeline.repo_lifecycle import rebuild_repo

            r = rebuild_repo(repo)
            reports.append({"repo": str(repo), "result": r})
            if isinstance(r, dict) and not r.get("ok", True):
                ok = False
        except Exception as exc:  # noqa: BLE001
            ok = False
            reports.append({"repo": str(repo), "error": str(exc)})
    return {"ok": ok, "skipped": False, "reports": reports, "destructive": True}


def rebind_mcp_and_rules() -> dict[str, Any]:
    """Rewrite MCP + GATE for all enrolled repos using connected tools."""
    from pipeline.connect_state import load_connected_tools
    from pipeline.managed_repos import managed_repo_paths
    from pipeline.rules_installer import apply_connected_tools_to_repo

    slugs = load_connected_tools()
    report: dict[str, Any] = {
        "ok": True,
        "connected_tools": slugs,
        "repos": [],
        "errors": [],
    }
    if not slugs:
        report["skipped"] = True
        report["skip_reason"] = "no tools in connected_tools.json"
        report["hint"] = "Run `scubiee connect --cursor` once after setup."
        return report

    for repo in managed_repo_paths(enrolled_only=True):
        try:
            sub = apply_connected_tools_to_repo(repo)
            report["repos"].append(sub)
            if not sub.get("ok", True):
                report["ok"] = False
                report["errors"].extend(sub.get("errors") or [])
        except Exception as exc:  # noqa: BLE001
            report["ok"] = False
            report["errors"].append(f"{repo}: {exc}")
    return report


def maybe_setup_repair() -> dict[str, Any]:
    """Best-effort accel repair (force reinstall packages / refresh profile)."""
    try:
        from pipeline.accel import configure
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "skipped": True, "error": str(exc)}

    try:
        # configure() has no repair= flag; force_install refreshes packages.
        profile = configure(force_install=True, bench=False)
        return {
            "ok": True,
            "profile": getattr(profile, "name", None) or str(profile),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def run_upgrade(
    *,
    pre_release: bool = False,
    check_only: bool = False,
    connect: bool = True,
    repair: bool = False,
    reindex: bool = False,
    skip_package: bool = False,
) -> dict[str, Any]:
    """Execute the upgrade supervisor pipeline."""
    from pipeline.upgrade import (
        _save_update_check,
        check_pypi_version,
        installed_version,
    )

    old_version = installed_version()
    revision_id = uuid.uuid4().hex[:12]
    report: dict[str, Any] = {
        "ok": True,
        "revision_id": revision_id,
        "platform": platform_name(),
        "old_version": old_version,
        "phases": [],
    }

    # DETECT
    pypi = check_pypi_version(force=True)
    report["pypi"] = pypi
    target = pypi.get("latest") or old_version
    if skip_package:
        target = old_version
    report["target_version"] = target
    report["phases"].append("detect")

    # PLAN
    plan = build_diff_plan(
        from_version=old_version,
        to_version=str(target),
        force_reindex=reindex,
        force_repair=repair,
        skip_package=skip_package or (old_version == target and not pypi.get("update_available")),
    )
    # If PyPI says update but we skip_package False, ensure package action is swap
    if pypi.get("update_available") and not skip_package:
        for a in plan.actions:
            if a.component == "package" and a.action == "skip":
                a.action = "swap"
                a.reason = f"{old_version} → {target}"
    report["plan"] = plan.to_dict()
    report["phases"].append("plan")

    if check_only:
        report["check_only"] = True
        report["next_steps"] = [
            "Run `scubiee upgrade` to apply this plan.",
        ]
        return report

    write_dirty_marker(
        {
            "revision_id": revision_id,
            "phase": "start",
            "old_version": old_version,
            "target_version": target,
            "started_at": time.time(),
            "platform": platform_name(),
        }
    )

    # SNAPSHOT
    snap = snapshot_for_rollback(revision_id=revision_id, old_version=old_version)
    report["snapshot"] = snap
    report["phases"].append("snapshot")

    need_swap = plan.needs("package")
    if need_swap:
        # QUIESCE
        write_dirty_marker(
            {
                "revision_id": revision_id,
                "phase": "quiesce",
                "old_version": old_version,
                "target_version": target,
                "started_at": time.time(),
            }
        )
        quiet = quiesce_for_upgrade()
        report["quiesce"] = quiet
        report["phases"].append("quiesce")
        if not quiet.get("ok"):
            report["ok"] = False
            report["error"] = quiet.get("error") or "quiesce_failed"
            report["hint"] = quiet.get("hint")
            # Leave dirty marker for resume/doctor
            return report

        # SWAP
        write_dirty_marker(
            {
                "revision_id": revision_id,
                "phase": "swap",
                "old_version": old_version,
                "target_version": target,
                "started_at": time.time(),
            }
        )
        swapped = swap_package(pre_release=pre_release)
        report["swap"] = swapped
        report["phases"].append("swap")
        if not swapped.get("ok"):
            report["ok"] = False
            report["error"] = swapped.get("error") or "package_upgrade_failed"
            report["hint"] = swapped.get("hint")
            return report
        record_component_applied("package", version=str(target), detail="swap")
    else:
        report["swap"] = {"ok": True, "skipped": True}
        report["phases"].append("swap_skipped")

    # Re-read installed version after swap
    try:
        from importlib.metadata import version as pkg_version

        new_version = pkg_version("scubiee")
    except Exception:  # noqa: BLE001
        new_version = installed_version()
    report["new_version"] = new_version
    if need_swap and new_version == old_version:
        report["warning"] = (
            "Package command succeeded but version unchanged — "
            "uv may not have bumped; retry with unlock-tool if needed."
        )

    # MIGRATE schema
    if plan.needs("index_schema"):
        write_dirty_marker(
            {
                "revision_id": revision_id,
                "phase": "migrate",
                "old_version": old_version,
                "target_version": new_version,
            }
        )
        try:
            migration = migrate_indexes()
            report["migration"] = migration
            record_component_applied(
                "index_schema", version=str(new_version), detail="migrate_all"
            )
        except Exception as exc:  # noqa: BLE001
            report["migration"] = {"ok": False, "error": str(exc)}
            report["ok"] = False
            report["error"] = "migration_failed"
            return report
    else:
        # Still run migrate_all — cheap no-op when current
        try:
            report["migration"] = migrate_indexes()
        except Exception as exc:  # noqa: BLE001
            report["migration"] = {"ok": False, "error": str(exc)}
    report["phases"].append("migrate")

    # Embeddings rebuild (destructive, informed)
    if plan.needs("embeddings"):
        write_dirty_marker(
            {
                "revision_id": revision_id,
                "phase": "embeddings",
                "old_version": old_version,
                "target_version": new_version,
            }
        )
        emb = rebuild_embeddings_if_needed(plan)
        report["embeddings"] = emb
        if not emb.get("ok"):
            report["ok"] = False
            report["error"] = "embeddings_rebuild_failed"
            return report
        record_component_applied(
            "embeddings", version=str(new_version), detail="rebuild"
        )
    else:
        report["embeddings"] = {"ok": True, "skipped": True}
    report["phases"].append("embeddings")

    # Accel repair
    if plan.needs("accel"):
        report["accel"] = maybe_setup_repair()
        if report["accel"].get("ok"):
            record_component_applied("accel", version=str(new_version), detail="repair")
    else:
        report["accel"] = {"ok": True, "skipped": True}
    report["phases"].append("accel")

    # Home layout stamp
    if plan.needs("home_layout"):
        from pipeline.upgrade_manifest import HOME_LAYOUT_VERSION

        record_component_applied(
            "home_layout", version=str(HOME_LAYOUT_VERSION), detail="stamp"
        )
        report["home_layout"] = {"ok": True, "version": HOME_LAYOUT_VERSION}
    report["phases"].append("home_layout")

    # REBIND daemon
    write_dirty_marker(
        {
            "revision_id": revision_id,
            "phase": "rebind",
            "old_version": old_version,
            "target_version": new_version,
        }
    )
    daemon = ensure_daemon_after_upgrade()
    report["daemon"] = daemon
    if not daemon.get("ok"):
        report["ok"] = False
        report["error"] = "daemon_start_failed"
        report["hint"] = "Run `scubiee engine start` then `scubiee status`."
        return report
    record_component_applied("daemon", version=str(new_version), detail=daemon.get("action") or "")
    report["phases"].append("daemon")

    # REBIND MCP + rules (stamp + kill workers before rewriting mcp.json)
    if connect:
        from pipeline.mcp_hot_reload import nudge_mcp_hot_reload

        report["mcp_hot_reload"] = nudge_mcp_hot_reload(new_version)

    need_rebind = plan.needs("mcp_pins") or plan.needs("gate_rules")
    if connect and need_rebind:
        from pipeline.upgrade_manifest import GATE_RULES_FORMAT, MCP_PIN_FORMAT

        rebound = rebind_mcp_and_rules()
        report["rebind"] = rebound
        if rebound.get("ok"):
            record_component_applied(
                "mcp_pins",
                version=f"{new_version}:v{MCP_PIN_FORMAT}",
                detail="apply_connected",
            )
            record_component_applied(
                "gate_rules",
                version=f"{new_version}:v{GATE_RULES_FORMAT}",
                detail="apply_connected",
            )
        else:
            report["ok"] = False
            report["error"] = "rebind_failed"
            report["hint"] = (
                "Package upgraded but MCP/rules refresh failed. "
                "Run `scubiee connect --cursor` (and other tools) manually."
            )
            return report
    else:
        if not connect:
            skip_reason = "connect disabled"
        elif not need_rebind:
            skip_reason = "mcp_pins and gate_rules already current"
        else:
            skip_reason = "not needed"
        report["rebind"] = {"ok": True, "skipped": True, "reason": skip_reason}
    report["phases"].append("rebind")

    # HEALTH
    health = health_check()
    report["health"] = health
    report["phases"].append("health")
    if not health.get("ok"):
        report["ok"] = False
        report["error"] = health.get("error") or "health_failed"
        report["hint"] = (
            "Upgrade applied but health check failed. "
            "Try `scubiee engine start` and reload IDE MCP."
        )
        return report

    # COMMIT
    _save_update_check(
        {
            "latest": new_version,
            "current": new_version,
            "checked_at": time.time(),
        }
    )
    clear_dirty_marker()
    report["phases"].append("commit")
    report["next_steps"] = [
        "Upgrade complete — daemon restarted on the new package.",
        "Quit and reopen your IDE once (or toggle MCP off/on) so the bridge reloads.",
    ]
    if report.get("rebind", {}).get("skipped"):
        report["next_steps"].append(
            "Run `scubiee connect --cursor` (or other tools) if MCP pins look stale."
        )
    destructive = [
        a for a in plan.actions if a.destructive and a.action != "skip"
    ]
    if destructive:
        report["next_steps"].append(
            "Index rebuild ran for embedding changes — verify search with `scubiee status`."
        )
    return report
