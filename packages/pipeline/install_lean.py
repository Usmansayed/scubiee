"""Keep one Scubiee install after upgrade or connect.

``uv tool install`` updates the tool env and leaves an older ``pip`` / conda
copy on PATH. Connect then pins that older interpreter into IDE mcp.json.
This module drops strictly older copies (and same-version duplicates) and
rewrites pythonw MCP commands onto the keeper.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class Install:
    prefix: str
    python: str
    version: str
    kind: str  # "uv-tool" | "pip"


def version_key(raw: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in (raw or "").split("."):
        digits = ""
        for ch in piece:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) or (0,)


def choose_keeper(installs: list[Install]) -> Install | None:
    """Newest version wins. A tie keeps the uv tool copy."""
    if not installs:
        return None

    def rank(item: Install) -> tuple[tuple[int, ...], int]:
        return (version_key(item.version), 1 if item.kind == "uv-tool" else 0)

    return max(installs, key=rank)


def prefix_of_exe(exe: Path) -> Path:
    try:
        resolved = exe.resolve()
    except OSError:
        resolved = exe
    parent = resolved.parent
    if parent.name.lower() in {"scripts", "bin"}:
        return parent.parent
    return parent


def pythonw_for(python: str) -> str:
    path = Path(python)
    if os.name == "nt":
        sibling = path.with_name("pythonw.exe")
        if sibling.is_file():
            return str(sibling).replace("\\", "/")
        scripts = path.parent / "Scripts" / "pythonw.exe"
        if path.parent.name.lower() != "scripts" and scripts.is_file():
            return str(scripts).replace("\\", "/")
    return str(path).replace("\\", "/")


def retarget_mcp_file(path: Path, keeper_pythonw: str, build_id: str) -> bool:
    """Point a scubiee python/pythonw MCP command at *keeper_pythonw*."""
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    keeper_prefix = str(prefix_of_exe(Path(keeper_pythonw)).resolve()).lower()
    changed = False
    for key in ("mcpServers", "servers"):
        servers = data.get(key)
        if not isinstance(servers, dict):
            continue
        for name, entry in servers.items():
            if str(name).lower() not in {"scubiee", "context-engine"}:
                continue
            if not isinstance(entry, dict):
                continue
            cmd = str(entry.get("command") or "")
            exe_name = Path(cmd).name.lower()
            if exe_name not in {"python.exe", "pythonw.exe", "python", "pythonw"}:
                continue
            try:
                cmd_prefix = str(prefix_of_exe(Path(cmd)).resolve()).lower()
            except OSError:
                cmd_prefix = ""
            if cmd_prefix == keeper_prefix:
                env = entry.get("env")
                if isinstance(env, dict) and build_id:
                    cur = str(env.get("CTX_SCUBIEE_BUILD") or "")
                    if cur != build_id:
                        env["CTX_SCUBIEE_BUILD"] = build_id
                        changed = True
                continue
            entry["command"] = keeper_pythonw
            entry["args"] = ["-u", "-m", "pipeline.mcp_bridge"]
            env = entry.get("env")
            if not isinstance(env, dict):
                env = {}
                entry["env"] = env
            if build_id:
                env["CTX_SCUBIEE_BUILD"] = build_id
            env["CTX_MCP_BRIDGE_SPAWN_JSON"] = json.dumps(
                [keeper_pythonw, "-u", "-m", "pipeline.mcp_locate"]
            )
            changed = True
    if not changed:
        return False
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def _same_prefix(a: str, b: str) -> bool:
    try:
        return str(prefix_of_exe(Path(a)).resolve()).lower() == str(
            prefix_of_exe(Path(b)).resolve()
        ).lower()
    except OSError:
        return Path(a).resolve().as_posix().lower() == Path(b).resolve().as_posix().lower()


def _child_env() -> dict[str, str]:
    """Env for a foreign interpreter. Drop inherited path overrides.

    A uv-tool ``scubiee`` process often has ``PYTHONPATH`` pointed at its own
    site-packages. A child ``pip uninstall`` then removes that copy and
    reports success while the conda install stays on disk.
    """
    env = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    return env


def _version_of_python(python: Path) -> str | None:
    if not python.is_file():
        return None
    try:
        from pipeline.process_job import hidden_run

        proc = hidden_run(
            [
                str(python),
                "-c",
                "import importlib.metadata as m; print(m.version('scubiee'))",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            env=_child_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    return lines[-1] if lines else None


def _add(found: dict[str, Install], prefix: Path, python: Path, version: str, kind: str) -> None:
    key = str(prefix.resolve()).lower()
    item = Install(
        prefix=str(prefix.resolve()),
        python=str(python.resolve()),
        version=version,
        kind=kind,
    )
    prev = found.get(key)
    if prev is None or (item.kind == "uv-tool" and prev.kind != "uv-tool"):
        found[key] = item


def discover_installs() -> list[Install]:
    """Current interpreter, the uv tool env, and ``scubiee`` executables on PATH."""
    from pipeline.mcp_install import _uv_tool_scubiee_python
    from pipeline.upgrade import installed_version

    found: dict[str, Install] = {}
    current = Path(sys.executable)
    current_ver = (installed_version() or "").strip()
    if current_ver and current_ver != "unknown" and current.is_file():
        kind = "uv-tool" if _uv_prefix(current) else "pip"
        _add(found, prefix_of_exe(current), current, current_ver, kind)

    uv_py = _uv_tool_scubiee_python()
    if uv_py:
        uv_path = Path(uv_py)
        ver = _version_of_python(uv_path)
        if ver:
            _add(found, prefix_of_exe(uv_path), uv_path, ver, "uv-tool")

    for exe in _where_scubiee():
        prefix = prefix_of_exe(exe)
        python = _python_in_prefix(prefix)
        if python is None:
            continue
        ver = _version_of_python(python)
        if not ver:
            continue
        kind = "uv-tool" if _uv_prefix(python) else "pip"
        _add(found, prefix, python, ver, kind)
    return list(found.values())


def _uv_prefix(python: Path) -> bool:
    try:
        from pipeline.process_control import is_uv_tool_install

        return bool(is_uv_tool_install(python))
    except Exception:  # noqa: BLE001
        return False


def _python_in_prefix(prefix: Path) -> Path | None:
    names = ("python.exe", "python") if os.name == "nt" else ("python",)
    for rel in ("Scripts", "bin", ""):
        base = prefix / rel if rel else prefix
        for name in names:
            candidate = base / name
            if candidate.is_file():
                return candidate
    return None


def _where_scubiee() -> list[Path]:
    cmd = ["where.exe", "scubiee"] if os.name == "nt" else ["which", "-a", "scubiee"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    out: list[Path] = []
    for line in (proc.stdout or "").splitlines():
        text = line.strip().strip('"')
        if not text:
            continue
        path = Path(text)
        if path.is_file():
            out.append(path)
    return out


def mcp_config_paths() -> list[Path]:
    home = Path.home()
    paths: list[Path] = [
        home / ".kiro" / "settings" / "mcp.json",
        home / ".cursor" / "mcp.json",
    ]
    try:
        from pipeline.connect_state import load_connected_tools
        from pipeline.managed_repos import managed_repo_paths
        from pipeline.tool_registry import (
            get_tool,
            resolve_mcp_project_paths,
            resolve_mcp_user_paths,
        )

        repos = list(managed_repo_paths(enrolled_only=True))
        for slug in load_connected_tools() or []:
            tool = get_tool(slug)
            if tool is None:
                continue
            for user_path in resolve_mcp_user_paths(tool):
                if user_path.suffix.lower() == ".json":
                    paths.append(user_path)
            for repo in repos:
                for project_path in resolve_mcp_project_paths(tool, repo):
                    if project_path.suffix.lower() == ".json":
                        paths.append(project_path)
    except Exception:  # noqa: BLE001
        pass
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


_SCRUB = r"""
import importlib.metadata, shutil
from pathlib import Path
try:
    dist = importlib.metadata.distribution("scubiee")
except importlib.metadata.PackageNotFoundError:
    print("absent")
    raise SystemExit(0)
meta = Path(getattr(dist, "_path", "") or "")
site = meta.parent
prefix = site.parent
if prefix.name.lower() in {"lib", "lib64"}:
    prefix = prefix.parent
record = meta / "RECORD"
if not meta.is_dir() or not record.is_file():
    print("no-record")
    raise SystemExit(2)
prefix_r = prefix.resolve()
for line in record.read_text(encoding="utf-8", errors="replace").splitlines():
    rel = line.split(",", 1)[0].strip()
    if not rel:
        continue
    target = (site / rel).resolve()
    try:
        target.relative_to(prefix_r)
    except ValueError:
        continue
    if target.is_file():
        target.unlink()
shutil.rmtree(meta, ignore_errors=True)
print("scrubbed")
"""


def _uninstall(python: str) -> dict[str, Any]:
    try:
        from pipeline.process_job import hidden_run

        proc = hidden_run(
            [python, "-m", "pip", "uninstall", "-y", "scubiee"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env=_child_env(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "python": python, "error": str(exc)}
    row: dict[str, Any] = {
        "ok": proc.returncode == 0,
        "python": python,
        "returncode": proc.returncode,
        "stderr_tail": "\n".join((proc.stderr or "").splitlines()[-6:]),
        "stdout_tail": "\n".join((proc.stdout or "").splitlines()[-6:]),
    }
    if _version_of_python(Path(python)):
        try:
            scrub = hidden_run(
                [python, "-c", _SCRUB],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
                env=_child_env(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            row["ok"] = False
            row["scrub_error"] = str(exc)
            return row
        row["scrub_returncode"] = scrub.returncode
        row["scrub_stdout"] = (scrub.stdout or "").strip()
        row["ok"] = scrub.returncode == 0 and _version_of_python(Path(python)) is None
    return row


def uninstall_pip_copies() -> list[dict[str, Any]]:
    """Uninstall pip/conda copies. Leaves the uv tool install for wipe/upgrade."""
    rows: list[dict[str, Any]] = []
    for item in discover_installs():
        if item.kind == "uv-tool":
            continue
        rows.append(_uninstall(item.python))
    return rows


def apply_lean(
    *,
    installs: list[Install] | None = None,
    uninstall: Callable[[str], dict[str, Any]] | None = None,
    mcp_paths: list[Path] | None = None,
    build_id: str | None = None,
) -> dict[str, Any]:
    """Drop older installs and retarget pythonw MCP commands onto the keeper.

    Does not touch ``~/.scubiee``, model caches, or the keeper prefix.
    Set ``SCUBIEE_KEEP_OTHER_INSTALLS=1`` to skip uninstall (retarget still runs).
    """
    found = list(installs) if installs is not None else discover_installs()
    keeper = choose_keeper(found)
    report: dict[str, Any] = {"ok": True, "installs": [item.__dict__ for item in found]}
    if keeper is None:
        report["skipped"] = True
        report["reason"] = "no installs"
        return report
    report["keeper"] = keeper.__dict__
    keeper_pyw = pythonw_for(keeper.python)
    stamp = build_id or _stamp_for(keeper.version)
    keep_others = (os.environ.get("SCUBIEE_KEEP_OTHER_INSTALLS") or "").strip() in {
        "1",
        "true",
        "yes",
    }
    removed: list[dict[str, Any]] = []
    do_uninstall = uninstall or _uninstall
    for item in found:
        if _same_prefix(item.python, keeper.python):
            continue
        if version_key(item.version) > version_key(keeper.version):
            continue
        if keep_others:
            removed.append({"python": item.python, "skipped": True, "reason": "keep_other_installs"})
            continue
        removed.append(do_uninstall(item.python))
    report["removed"] = removed
    rewritten: list[str] = []
    for path in mcp_paths if mcp_paths is not None else mcp_config_paths():
        if retarget_mcp_file(path, keeper_pyw, stamp):
            rewritten.append(str(path))
    report["mcp_rewritten"] = rewritten
    report["keeper_pythonw"] = keeper_pyw
    if any(row.get("ok") is False for row in removed):
        report["ok"] = False
    return report


def _stamp_for(version: str) -> str:
    try:
        from pipeline.mcp_hot_reload import ensure_active_build_stamp

        stamp = ensure_active_build_stamp(version)
        bid = str(stamp.get("build_id") or "").strip()
        if bid:
            return bid
    except Exception:  # noqa: BLE001
        pass
    return version


def newer_uv_pythonw() -> str | None:
    """pythonw of the uv tool install when it is at least as new as this process."""
    from pipeline.mcp_install import _uv_tool_scubiee_python
    from pipeline.upgrade import installed_version

    uv_py = _uv_tool_scubiee_python()
    if not uv_py:
        return None
    if _same_prefix(uv_py, sys.executable):
        return None
    ver = _version_of_python(Path(uv_py))
    if not ver:
        return None
    current = (installed_version() or "").strip()
    if current and current != "unknown" and version_key(ver) < version_key(current):
        return None
    return pythonw_for(uv_py)


def maybe_reexec_newer_uv() -> None:
    """Replace this process with the uv tool CLI when that install is newer."""
    from pipeline.mcp_install import _uv_tool_scubiee_python
    from pipeline.upgrade import installed_version

    uv_py = _uv_tool_scubiee_python()
    if not uv_py or _same_prefix(uv_py, sys.executable):
        return
    ver = _version_of_python(Path(uv_py))
    current = (installed_version() or "").strip()
    if not ver or not current or current == "unknown":
        return
    if version_key(ver) <= version_key(current):
        return
    scripts = Path(uv_py).parent
    exe_name = "scubiee.exe" if os.name == "nt" else "scubiee"
    exe = scripts / exe_name
    if not exe.is_file():
        return
    argv = [str(exe), *sys.argv[1:]]
    os.execv(str(exe), argv)
