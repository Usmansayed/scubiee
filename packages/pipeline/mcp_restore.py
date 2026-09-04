"""Restore live Scubiee MCP pins after unlock/upgrade stubs leave hosts "off".

Cursor and other IDEs often show Scubiee as disabled/disconnected when
``mcp.json`` still has a no-op stub (``cmd /c exit 0``) or ``disabled: true``
left behind after ``unlock-tool`` / failed upgrade quiesce. Neighbor MCP
servers are never touched — only the ``scubiee`` key is rewritten.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def is_stubbed_mcp_entry(entry: dict[str, Any]) -> bool:
    """True when the entry is the halt/unlock no-op spawn (not a real bridge)."""
    from pipeline.process_control import mcp_noop_command

    if not isinstance(entry, dict):
        return False
    noop_cmd, noop_args = mcp_noop_command()
    cmd = entry.get("command")
    args = list(entry.get("args") or [])
    if isinstance(cmd, list):
        parts = [str(x) for x in cmd]
        if parts == [noop_cmd, *noop_args]:
            return True
        head = parts[0].lower() if parts else ""
        return head in {"cmd", "cmd.exe", "true"} and (
            "exit" in " ".join(p.lower() for p in parts) or head == "true"
        )
    head = str(cmd or "").lower()
    if head in {noop_cmd.lower(), "true", "cmd", "cmd.exe"}:
        if head == "true" and not args:
            return True
        joined = " ".join(str(a).lower() for a in args)
        return "/c" in args or "exit" in joined or head in {"cmd", "cmd.exe"}
    return False


def mcp_entry_needs_restore(entry: dict[str, Any]) -> bool:
    """Stubbed, explicitly disabled, or missing a real Scubiee launcher."""
    if not isinstance(entry, dict):
        return True
    if entry.get("disabled") is True:
        return True
    if entry.get("enabled") is False:
        return True
    if is_stubbed_mcp_entry(entry):
        return True
    cmd = entry.get("command")
    text = (
        " ".join(str(x) for x in cmd)
        if isinstance(cmd, list)
        else str(cmd or "")
    ).lower()
    args = " ".join(str(a) for a in (entry.get("args") or [])).lower()
    blob = f"{text} {args}"
    return not (
        "scubiee-mcp" in blob
        or "pipeline.mcp_locate" in blob
        or "pipeline.mcp_server" in blob
    )


def _iter_scubiee_json_entries() -> list[tuple[Path, str, dict[str, Any]]]:
    """Yield (path, key, entry) for scubiee blocks in project MCP JSON files."""
    from pipeline.branding import MCP_SERVER_NAME
    from pipeline.connect_state import load_connected_tools
    from pipeline.managed_repos import managed_repo_paths
    from pipeline.tool_registry import get_tool, resolve_mcp_project_write_targets

    found: list[tuple[Path, str, dict[str, Any]]] = []
    seen: set[str] = set()
    roots: list[Path] = []
    try:
        roots.append(Path.cwd().resolve())
    except OSError:
        pass
    for repo in managed_repo_paths(enrolled_only=False):
        roots.append(Path(repo).resolve())

    slugs = load_connected_tools() or ["cursor"]
    for root in roots:
        for slug in slugs:
            tool = get_tool(slug)
            if tool is None:
                continue
            for path, schema, key in resolve_mcp_project_write_targets(tool, root):
                if schema not in {None, "cursor", "json", ""} and path.suffix.lower() != ".json":
                    continue
                if not path.is_file():
                    continue
                pkey = str(path.resolve()).replace("\\", "/").lower()
                if pkey in seen:
                    continue
                seen.add(pkey)
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    continue
                if not isinstance(data, dict):
                    continue
                bucket_key = key or "mcpServers"
                servers = data.get(bucket_key)
                if not isinstance(servers, dict):
                    servers = data.get("mcpServers")
                    bucket_key = "mcpServers"
                if not isinstance(servers, dict):
                    continue
                # OpenCode v2 nests under mcp.servers
                if bucket_key == "mcp" and isinstance(servers.get("servers"), dict):
                    nested = servers["servers"]
                    entry = nested.get(MCP_SERVER_NAME)
                    if isinstance(entry, dict):
                        found.append((path, "mcp.servers", entry))
                    continue
                entry = servers.get(MCP_SERVER_NAME)
                if isinstance(entry, dict):
                    found.append((path, bucket_key, entry))
                else:
                    # unlock/strip removed the key — still needs a live pin.
                    found.append((path, bucket_key, {}))
    return found


def scan_mcp_pins_needing_restore() -> dict[str, Any]:
    """Report which project MCP files still have stubbed/disabled Scubiee entries."""
    needing: list[str] = []
    for path, _key, entry in _iter_scubiee_json_entries():
        if mcp_entry_needs_restore(entry):
            needing.append(str(path))
    return {
        "ok": True,
        "needs_restore": bool(needing),
        "paths": needing,
        "count": len(needing),
    }


def restore_live_mcp_pins(
    *,
    project: Path | str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Rewrite live Scubiee MCP + GATE pins for connected hosts on enrolled repos.

    Clears no-op stubs and ``disabled: true`` left by unlock/upgrade quiesce.
    Also clears Cursor's sticky UI disable list (``disabledMcpServers``) so the
    Settings toggle does not stay off after a healthy pin rewrite.
    Safe to call when pins are already healthy (no-op rewrite).
    """
    report: dict[str, Any] = {
        "ok": True,
        "skipped": False,
        "restored": False,
        "paths_before": [],
        "errors": [],
    }

    scan = scan_mcp_pins_needing_restore()
    report["scan"] = scan
    report["paths_before"] = list(scan.get("paths") or [])
    if not force and not scan.get("needs_restore"):
        # Pins look live, but Cursor may still have toggled Scubiee off in UI state.
        report["skipped"] = True
        report["skip_reason"] = "mcp_pins_already_live"
        report["cursor_ui"] = clear_cursor_disabled_scubiee()
        return report

    # Prefer full rebind (all enrolled repos + connected tools).
    try:
        from pipeline.upgrade_supervisor import rebind_mcp_and_rules

        rebound = rebind_mcp_and_rules()
        report["rebind"] = rebound
        if not rebound.get("ok", True):
            report["ok"] = False
            report["errors"].extend(rebound.get("errors") or [])
        elif rebound.get("skipped"):
            # No connected_tools yet — still heal cwd / project cursor mcp.json.
            report["fallback"] = _restore_cursor_project_mcp(project)
            if not (report["fallback"] or {}).get("ok", True):
                report["ok"] = False
        else:
            report["restored"] = True
    except Exception as exc:  # noqa: BLE001
        report["ok"] = False
        report["errors"].append(str(exc))
        report["fallback"] = _restore_cursor_project_mcp(project)

    # Clear sticky disabled on any leftover JSON entries (hosts that ignore rewrite).
    cleared = _clear_disabled_flags()
    report["cleared_disabled"] = cleared
    if cleared.get("paths"):
        report["restored"] = True

    # Cursor Settings toggle lives in state.vscdb — clear Scubiee from that list.
    report["cursor_ui"] = clear_cursor_disabled_scubiee()

    after = scan_mcp_pins_needing_restore()
    report["scan_after"] = after
    if after.get("needs_restore"):
        report["ok"] = False
        report["errors"].append("stub_or_disabled_still_present")
        report["hint"] = (
            "Run `scubiee connect` (or `scubiee connect --cursor`) then reload the host MCP."
        )
    elif report.get("restored") or report.get("fallback", {}).get("ok"):
        report["restored"] = True
        report["hint"] = (
            "Scubiee MCP pins restored. If the host toggle still looks off, "
            "reload the window once (Cursor caches MCP UI separately)."
        )
    return report


def _restore_cursor_project_mcp(project: Path | str | None) -> dict[str, Any]:
    """Best-effort rewrite of project .cursor/mcp.json when no connected_tools yet."""
    try:
        from pipeline.mcp_install import write_cursor_mcp
        from pipeline.mcp_permissions import enrich_server_entry_permissions
        from pipeline.mcp_install import merge_mcp_json, server_entry
        from pipeline.branding import MCP_SERVER_NAME
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}

    root = Path(project).resolve() if project else Path.cwd().resolve()
    try:
        # Prefer permission-enriched entry (autoApprove) without sticky disabled:true.
        path = root / ".cursor" / "mcp.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = enrich_server_entry_permissions(
            server_entry(root),
            "cursor",
            profile="locate",
        )
        # Cursor: omit disabled key when live (UI + json "disabled" fight across restarts).
        entry.pop("disabled", None)
        entry.pop("enabled", None)
        data: dict[str, Any] = {"mcpServers": {}}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
            except (OSError, json.JSONDecodeError):
                pass
        servers = data.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            servers = {}
            data["mcpServers"] = servers
        servers[MCP_SERVER_NAME] = entry
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        # Keep write_cursor_mcp as secondary for rule files.
        try:
            write_cursor_mcp(repo=root)
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "path": str(path)}
    except Exception as exc:  # noqa: BLE001
        try:
            merge_mcp_json(root / ".cursor" / "mcp.json", repo=root)
            return {"ok": True, "path": str(root / ".cursor" / "mcp.json"), "via": "merge"}
        except Exception as exc2:  # noqa: BLE001
            return {"ok": False, "error": f"{exc}; {exc2}"}


def _clear_disabled_flags() -> dict[str, Any]:
    """Pop ``disabled: true`` / fix ``enabled: false`` on scubiee JSON entries."""
    from pipeline.branding import MCP_SERVER_NAME

    cleared: list[str] = []
    for path, bucket_key, entry in _iter_scubiee_json_entries():
        if entry.get("disabled") is not True and entry.get("enabled") is not False:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        block: dict[str, Any] | None = None
        if bucket_key == "mcp.servers":
            mcp = data.get("mcp")
            if isinstance(mcp, dict) and isinstance(mcp.get("servers"), dict):
                block = mcp["servers"].get(MCP_SERVER_NAME)
                if isinstance(block, dict):
                    block.pop("disabled", None)
                    if block.get("enabled") is False:
                        block["enabled"] = True
                    mcp["servers"][MCP_SERVER_NAME] = block
                    data["mcp"] = mcp
        else:
            servers = data.get(bucket_key)
            if not isinstance(servers, dict):
                continue
            block = servers.get(MCP_SERVER_NAME)
            if not isinstance(block, dict):
                continue
            block.pop("disabled", None)
            if block.get("enabled") is False:
                block["enabled"] = True
            servers[MCP_SERVER_NAME] = block
            data[bucket_key] = servers
        if not isinstance(block, dict):
            continue
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        cleared.append(str(path))
    return {"ok": True, "paths": cleared}


def _scubiee_ui_disable_names() -> tuple[str, ...]:
    """Cursor ``disabledMcpServers`` id fragments that mean Scubiee is toggled off."""
    from pipeline.branding import MCP_SERVER_NAME

    return (MCP_SERVER_NAME.lower(), "scubiee")


def _is_scubiee_disabled_ui_id(value: str) -> bool:
    """True for Scubiee MCP UI ids — never neighbor servers (figma, etc.)."""
    low = (value or "").strip().lower()
    if not low:
        return False
    if "scubiee" in low:
        return True
    # Legacy server names before Scubiee branding (exact / suffix only).
    if low in {"user-context-engine", "context-engine"}:
        return True
    if low.endswith("-context-engine") and "figma" not in low and "frontend" not in low:
        return True
    return False


def clear_cursor_disabled_scubiee() -> dict[str, Any]:
    """Remove Scubiee from Cursor's sticky ``cursor/disabledMcpServers`` UI list.

    Cursor keeps enable/disable in ``state.vscdb`` (not only ``mcp.json``). After
    unlock/upgrade we restore the pin, but Settings can still show the toggle off
    until this list is cleared.
    """
    import os
    import sqlite3

    report: dict[str, Any] = {"ok": True, "cleared": [], "errors": []}
    appdata = os.environ.get("APPDATA") or os.environ.get("HOME") or ""
    if not appdata:
        return {"ok": True, "skipped": True, "skip_reason": "no_appdata"}
    roots = [
        Path(appdata) / "Cursor" / "User" / "workspaceStorage",
        Path(appdata) / "Cursor" / "User" / "globalStorage",
        # Older / portable layouts
        Path.home() / ".cursor" / "User" / "workspaceStorage",
        Path.home() / "Library" / "Application Support" / "Cursor" / "User" / "workspaceStorage",
        Path.home() / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage",
    ]
    key = "cursor/disabledMcpServers"
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for db in root.rglob("state.vscdb"):
            pkey = str(db.resolve()).replace("\\", "/").lower()
            if pkey in seen:
                continue
            seen.add(pkey)
            try:
                con = sqlite3.connect(str(db), timeout=2.0)
            except sqlite3.Error as exc:
                report["errors"].append(f"{db}: {exc}")
                continue
            try:
                cur = con.cursor()
                row = cur.execute(
                    "SELECT value FROM ItemTable WHERE key = ?", (key,)
                ).fetchone()
                if not row:
                    continue
                raw = row[0]
                if isinstance(raw, (bytes, bytearray)):
                    text = raw.decode("utf-8", errors="replace")
                else:
                    text = str(raw)
                try:
                    values = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if not isinstance(values, list) or not values:
                    continue
                kept = [v for v in values if not _is_scubiee_disabled_ui_id(str(v))]
                if kept == values:
                    continue
                cur.execute(
                    "UPDATE ItemTable SET value = ? WHERE key = ?",
                    (json.dumps(kept), key),
                )
                con.commit()
                report["cleared"].append(
                    {"path": str(db), "removed": sorted(set(values) - set(kept))}
                )
            except sqlite3.Error as exc:
                report["errors"].append(f"{db}: {exc}")
            finally:
                try:
                    con.close()
                except sqlite3.Error:
                    pass
    if report["errors"]:
        report["ok"] = False
    return report


def heal_mcp_pins_if_stubbed(*, force: bool = False) -> dict[str, Any]:
    """Daemon/engine start hook: restore only when stubs/disabled are detected."""
    try:
        from pipeline.lifecycle_runtime import upgrade_in_progress

        if upgrade_in_progress():
            return {
                "ok": True,
                "skipped": True,
                "skip_reason": "upgrade_in_progress",
            }
    except Exception:  # noqa: BLE001
        pass
    try:
        from pipeline.pause_resume import is_paused

        if is_paused():
            return {"ok": True, "skipped": True, "skip_reason": "paused"}
    except Exception:  # noqa: BLE001
        pass
    try:
        return restore_live_mcp_pins(force=force)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "skipped": True}
