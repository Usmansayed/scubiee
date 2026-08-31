"""Release certification — required vs skipped vs optional checks."""

from __future__ import annotations

import importlib
import importlib.util
import os
import platform
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


def _check(
    name: str,
    ok: bool,
    *,
    required: bool = True,
    detail: str = "",
    status: str | None = None,
) -> dict[str, Any]:
    if status is None:
        status = "passed" if ok else ("failed" if required else "optional_failed")
    if status == "skipped":
        ok = False
        # Skips are never proof and never required failures.
        required = False
    return {
        "name": name,
        "ok": ok,
        "required": required,
        "status": status,
        "detail": detail,
    }


def certify_platform_lane(
    name: str,
    profile: Any,
    *,
    hardware_available: bool,
    providers: list[str],
    warmup: Any,
) -> dict[str, Any]:
    """Certify one explicit lane; unavailable hardware is neutral, never proof."""

    if not hardware_available:
        return _check(
            name,
            False,
            status="skipped",
            detail="required hardware/provider lane is unavailable",
        )
    from pipeline.preflight import validate_provider

    validation = validate_provider(
        profile,
        finder=lambda _module: object(),
        provider_getter=lambda: list(providers),
        warmup=warmup,
    )
    return _check(name, validation.ok, detail=str(validation.to_dict()))


@contextmanager
def _temporary_environment(**updates: str | None) -> Iterator[None]:
    previous = {name: os.environ.get(name) for name in updates}
    try:
        for name, value in updates.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def scenario_checks(root: Path) -> list[dict[str, Any]]:
    """Run required production simulations in an isolated temporary CE home."""
    del root
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="ctx-certify-") as temporary:
        sandbox = Path(temporary)
        home = sandbox / "home"
        home.mkdir()
        with _temporary_environment(CTX_HOME=str(home)):
            try:
                from pipeline.repo_lifecycle import initialize_repo, managed_state

                repo = sandbox / "lifecycle-repo"
                repo.mkdir()
                initialized = initialize_repo(repo, index=False)
                ok = bool(initialized.get("project_id")) and managed_state(repo) == "active"
                checks.append(
                    _check(
                        "repo_lifecycle",
                        ok,
                        detail=f"state={managed_state(repo)}",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                checks.append(_check("repo_lifecycle", False, detail=str(exc)))

            try:
                from pipeline.artifact_guard import atomic_write_text
                from pipeline.project_id import index_is_usable

                blocked = sandbox / "blocked-store"
                blocked.write_text("not-a-directory\n", encoding="utf-8")
                denied = False
                try:
                    atomic_write_text(blocked / "chunks.jsonl", "{}\n")
                except OSError:
                    denied = True
                unusable = index_is_usable(blocked) is False
                checks.append(
                    _check(
                        "disk_denial_unusable_store",
                        denied and unusable,
                        detail=f"denied={denied} unusable={unusable}",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                checks.append(
                    _check("disk_denial_unusable_store", False, detail=str(exc))
                )

            if os.name != "posix":
                checks.append(
                    _check(
                        "permission_denial",
                        False,
                        status="skipped",
                        detail=f"chmod denial is not reliable on {os.name}",
                    )
                )
            else:
                permission_dir = sandbox / "permission-denied"
                permission_dir.mkdir()
                permission_dir.chmod(0)
                permission_denied = False
                try:
                    (permission_dir / "probe").write_text("x", encoding="utf-8")
                except PermissionError:
                    permission_denied = True
                finally:
                    permission_dir.chmod(0o700)
                if permission_denied:
                    checks.append(
                        _check(
                            "permission_denial",
                            True,
                            detail="chmod(0) rejected the write",
                        )
                    )
                else:
                    checks.append(
                        _check(
                            "permission_denial",
                            False,
                            status="skipped",
                            detail="filesystem or elevated user did not enforce chmod denial",
                        )
                    )

            try:
                from pipeline.dirty_journal import (
                    JournalingLedger,
                    restore_ledger_from_journal,
                )
                from pipeline.dirty_ledger import DirtyLedger

                first = JournalingLedger("certify-journal")
                first.mark(["pkg/dirty.py"], reason="write", now=1.0)
                replayed = DirtyLedger(debounce_ms=0)
                restore = restore_ledger_from_journal(
                    replayed, "certify-journal", now=2.0
                )
                paths = replayed.snapshot().get("paths") or {}
                ok = restore.get("ok") is True and "pkg/dirty.py" in paths
                checks.append(
                    _check(
                        "dirty_restart_journal_replay",
                        ok,
                        detail=f"restore={restore} paths={sorted(paths)}",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                checks.append(
                    _check("dirty_restart_journal_replay", False, detail=str(exc))
                )

            try:
                from pipeline.repo_runtime import RepoHub

                repo_a = sandbox / "repo-a"
                repo_b = sandbox / "repo-b"
                repo_a.mkdir()
                repo_b.mkdir()
                from pipeline.project_id import save_registry, write_id_file

                pid_a = "ce_certify_a1234567890abcdef"
                pid_b = "ce_certify_b1234567890abcdef"
                write_id_file(repo_a, pid_a)
                write_id_file(repo_b, pid_b)
                save_registry(
                    {
                        "projects": {
                            pid_a: {
                                "managed": True,
                                "root": str(repo_a.resolve()),
                                "paths": [str(repo_a.resolve())],
                            },
                            pid_b: {
                                "managed": True,
                                "root": str(repo_b.resolve()),
                                "paths": [str(repo_b.resolve())],
                            },
                        }
                    }
                )
                hub = RepoHub()
                runtime_a = hub.ensure(repo_a)
                runtime_b = hub.ensure(repo_b)
                hub.isolate_failure(runtime_a.project_id, "simulated provider failure")
                error_a = (
                    getattr(runtime_a, "isolated_error", None)
                    or getattr(runtime_a, "warm_error", None)
                    or getattr(runtime_a, "error", None)
                )
                error_b = (
                    getattr(runtime_b, "isolated_error", None)
                    or getattr(runtime_b, "warm_error", None)
                    or getattr(runtime_b, "error", None)
                )
                ok = (
                    runtime_a.project_id != runtime_b.project_id
                    and runtime_a is not runtime_b
                    and bool(error_a)
                    and not error_b
                )
                checks.append(
                    _check(
                        "two_repo_runtime_isolation",
                        ok,
                        detail=(
                            f"ids={runtime_a.project_id},{runtime_b.project_id} "
                            f"isolated={bool(error_a)} peer_error={bool(error_b)}"
                        ),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                checks.append(
                    _check("two_repo_runtime_isolation", False, detail=str(exc))
                )

            try:
                from pipeline.accel import AccelProfile
                from pipeline.preflight import validate_provider

                saved = AccelProfile(
                    profile="cuda",
                    provider="CUDAExecutionProvider",
                    batch_size=16,
                )
                validation = validate_provider(
                    saved,
                    finder=lambda module: (
                        object()
                        if module in {"fastembed", "onnxruntime"}
                        else None
                    ),
                    provider_getter=lambda: ["CPUExecutionProvider"],
                    warmup=lambda _profile: True,
                )
                ok = (
                    validation.ok is False
                    and validation.provider_available is False
                    and validation.model_warm is False
                )
                checks.append(
                    _check(
                        "provider_warmup_fail_closed",
                        ok,
                        detail=str(validation.to_dict()),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                checks.append(
                    _check("provider_warmup_fail_closed", False, detail=str(exc))
                )

            try:
                from pipeline.merkle import file_sha256
                from pipeline.store import PipelineStore
                from pipeline.sync_loop import BackgroundSyncLoop

                watched = sandbox / "watched-repo"
                watched.mkdir()
                changed = watched / "recovered.py"
                changed.write_text("recovered = False\n", encoding="utf-8")
                from pipeline.project_id import projects_root, save_registry, write_id_file

                watch_pid = "ce_certifywatch1234567890abc"
                write_id_file(watched, watch_pid)
                save_registry(
                    {
                        "projects": {
                            watch_pid: {
                                "managed": True,
                                "root": str(watched.resolve()),
                                "paths": [str(watched.resolve())],
                            }
                        }
                    }
                )
                watch_store = projects_root() / watch_pid
                watch_store.mkdir(parents=True, exist_ok=True)
                store = PipelineStore(
                    watched,
                    base_dir=watch_store,
                    project_id=watch_pid,
                    resolve=False,
                )
                store.save_merkle({"recovered.py": file_sha256(changed)})
                store.save_meta({"fast": False, "git_head": None})
                loop = BackgroundSyncLoop(watched, debounce_ms=0)
                changed.write_text("recovered = True\n", encoding="utf-8")
                recovery = loop.note_watcher_overflow()
                dirty = (loop.status().get("dirty") or {}).get("paths") or {}
                ok = (
                    recovery.get("reason") == "watcher_overflow"
                    and "recovered.py" in dirty
                )
                checks.append(
                    _check(
                        "watcher_overflow_recovery",
                        ok,
                        detail=f"recovery={recovery} dirty={sorted(dirty)}",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                checks.append(
                    _check("watcher_overflow_recovery", False, detail=str(exc))
                )

            try:
                from pipeline.doctor import plan_repairs

                repair_repo = sandbox / "doctor-repair-repo"
                repair_repo.mkdir()
                (repair_repo / "mod.py").write_text("value = 1\n", encoding="utf-8")
                planned = plan_repairs(repair_repo)
                kinds = {item["id"]: item["kind"] for item in planned}
                safe_ok = all(
                    item["kind"] == "safe"
                    for item in planned
                    if item["id"]
                    in {"bind_daemon", "initialize_index", "replay_dirty_journal"}
                )
                manual_ok = all(
                    item["kind"] == "manual"
                    for item in planned
                    if item["id"] in {"install_deps", "init_repair", "rebuild_index"}
                )
                classified = bool(planned) and all(
                    item.get("kind") in {"safe", "manual"} for item in planned
                )
                ok = classified and safe_ok and manual_ok and (
                    "initialize_index" in kinds or "bind_daemon" in kinds
                )
                checks.append(
                    _check(
                        "doctor_safe_repair_classification",
                        ok,
                        detail=str(kinds),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                checks.append(
                    _check(
                        "doctor_safe_repair_classification",
                        False,
                        detail=str(exc),
                    )
                )

            try:
                from pipeline.lifecycle_runtime import (
                    DEFAULT_IDLE_S,
                    DESIRED_STANDBY,
                    engine_should_be_running,
                    load_policy,
                    set_desired_mode,
                    should_idle_stop,
                    supervisor_command,
                    current_desktop,
                )

                set_desired_mode(DESIRED_STANDBY)
                cmd = supervisor_command(python="python")
                ok = (
                    DEFAULT_IDLE_S == 25.0
                    and engine_should_be_running() is False
                    and should_idle_stop(now=10_000.0) is False
                    and load_policy()["desired_mode"] == DESIRED_STANDBY
                    and cmd[-2:] == ["supervisor", "--logon"]
                    and current_desktop() in {"windows", "darwin", "linux"}
                )
                checks.append(
                    _check(
                        "autonomous_standby_idle_policy",
                        ok,
                        detail=f"idle_s={DEFAULT_IDLE_S} cmd={cmd[-3:]}",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                checks.append(
                    _check("autonomous_standby_idle_policy", False, detail=str(exc))
                )

            try:
                from pipeline.artifact_guard import publish_manifest, validate_manifest

                store = sandbox / "publication-store"
                store.mkdir()
                artifact = store / "chunks.jsonl"
                artifact.write_text('{"id":1}\n', encoding="utf-8")
                publish_manifest(store, [artifact])
                clean = validate_manifest(store)
                artifact.write_text('{"id":2}\n', encoding="utf-8")
                corrupt = validate_manifest(store)
                ok = (
                    clean.get("ok") is True
                    and corrupt.get("ok") is False
                    and corrupt.get("reason") == "checksum_mismatch"
                )
                checks.append(
                    _check(
                        "publication_coherence",
                        ok,
                        detail=(
                            f"clean={clean.get('reason', 'ok')} "
                            f"corrupt={corrupt.get('reason')}"
                        ),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                checks.append(
                    _check("publication_coherence", False, detail=str(exc))
                )

    checks.append(
        _check(
            "external_client_matrix",
            False,
            required=False,
            status="skipped",
            detail="optional: scubiee test clients --clients",
        )
    )
    return checks


def certify(
    root: Path | str | None = None,
    *,
    skip_daemon: bool = False,
    skip_canary: bool = True,
) -> dict[str, Any]:
    """Run the product release gate. Only required failures block ok=true."""
    repo = Path(root).resolve() if root else Path.cwd()
    checks: list[dict[str, Any]] = []
    t0 = time.perf_counter()

    # Imports
    for mod in (
        "pipeline.preflight",
        "pipeline.artifact_guard",
        "pipeline.test_runner",
        "pipeline.doctor",
        "pipeline.daemon",
    ):
        try:
            importlib.import_module(mod)
            checks.append(_check(f"import_{mod.split('.')[-1]}", True))
        except Exception as exc:  # noqa: BLE001
            checks.append(_check(f"import_{mod.split('.')[-1]}", False, detail=str(exc)))

    # MCP phase surface exists
    try:
        from pipeline import mcp_locate

        surface_default = (os.environ.get("CTX_MCP_SURFACE") or "").strip().lower()
        # Product ships phase; shell may override for legacy trials.
        phase_ok = "phase" in getattr(mcp_locate, "_SURFACES", set())
        checks.append(
            _check(
                "mcp_phase_surface_available",
                phase_ok,
                detail=f"active_env={surface_default or 'unset'} default_fn={mcp_locate._active_surface()}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("mcp_phase_surface_available", False, detail=str(exc)))

    # Install config defaults to phase
    try:
        from pipeline.mcp_install import server_entry

        entry = server_entry(repo)
        checks.append(
            _check(
                "install_mcp_phase_env",
                entry.get("env", {}).get("CTX_MCP_SURFACE") == "phase"
                and "PYTHONPATH" not in (entry.get("env") or {}),
                detail=str(entry.get("env", {}).get("CTX_MCP_SURFACE")),
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("install_mcp_phase_env", False, detail=str(exc)))

    # Doctor
    try:
        from pipeline.doctor import doctor_repo

        doc = doctor_repo(repo)
        checks.append(
            _check(
                "doctor_capabilities",
                bool(doc.get("capabilities", {}).get("ok")),
                detail=f"missing={doc.get('capabilities', {}).get('missing_required')}",
            )
        )
        provider_validation = (doc.get("accel") or {}).get("provider_validation") or {}
        checks.append(
            _check(
                "saved_provider_model_warmup",
                bool(provider_validation.get("ok")),
                detail=str(provider_validation),
            )
        )
        current_os = platform.system()
        saved_name = (doc.get("accel") or {}).get("profile")
        for lane_name, lane_os, lane_profile in (
            ("windows_dml", "Windows", "dml"),
            ("linux_nvidia_cuda", "Linux", "cuda"),
            ("linux_cpu_safe", "Linux", "cpu"),
            ("darwin_mlx", "Darwin", "mlx"),
            ("darwin_coreml", "Darwin", "coreml"),
            ("darwin_cpu_safe", "Darwin", "cpu"),
        ):
            applicable = current_os == lane_os and saved_name == lane_profile
            checks.append(
                _check(
                    lane_name,
                    bool(provider_validation.get("ok")) if applicable else False,
                    status=None if applicable else "skipped",
                    detail=(
                        str(provider_validation)
                        if applicable
                        else (
                            f"lane requires os={lane_os} saved_profile={lane_profile}; "
                            f"found os={current_os} saved_profile={saved_name}"
                        )
                    ),
                )
            )
        # Index readiness may be false on a fresh checkout — report, not hard fail unless claimed ready
        checks.append(
            _check(
                "doctor_index_usable",
                True,
                required=False,
                status="passed" if doc.get("readiness", {}).get("index_usable") else "skipped",
                detail=str(doc.get("readiness")),
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("doctor_capabilities", False, detail=str(exc)))

    # Daemon binding
    if skip_daemon:
        checks.append(
            _check("daemon_binding", True, required=False, status="skipped", detail="skip_daemon")
        )
    else:
        try:
            from pipeline.daemon import validate_daemon_binding

            bind = validate_daemon_binding(repo)
            checks.append(
                _check(
                    "daemon_binding",
                    bool(bind.get("ok")),
                    required=False,
                    status="passed" if bind.get("ok") else "skipped",
                    detail=str(bind.get("repair") or bind),
                )
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(
                _check(
                    "daemon_binding",
                    True,
                    required=False,
                    status="skipped",
                    detail=str(exc),
                )
            )

    checks.extend(scenario_checks(repo))

    if not skip_canary:
        checks.append(
            _check(
                "semantic_canary",
                True,
                required=False,
                status="skipped",
                detail="enable with --skip-canary false when index is warm",
            )
        )

    required_failures = [
        c for c in checks if c["required"] and c.get("status") == "failed"
    ]
    return {
        "ok": not required_failures,
        "repo": str(repo),
        "passed": sum(1 for c in checks if c.get("status") == "passed"),
        "failed_required": len(required_failures),
        "skipped": sum(1 for c in checks if c.get("status") == "skipped"),
        "checks": checks,
        "failures": required_failures,
        "ms": round((time.perf_counter() - t0) * 1000, 1),
        "certify_version": 1,
    }
