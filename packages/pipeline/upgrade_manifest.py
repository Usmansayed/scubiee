"""Component migration manifest and DiffPlan for Scubiee upgrades.

Flyway-style: each component has a version key; only dirty components run.
History lives under ``~/.scubiee/upgrade_history.json``.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

ComponentId = Literal[
    "package",
    "daemon",
    "index_schema",
    "embeddings",
    "mcp_pins",
    "gate_rules",
    "accel",
    "home_layout",
]

# Template / pin format version — bump when MCP env keys or GATE body must refresh.
# v2: scubiee-mcp-bridge + CTX_SCUBIEE_BUILD (hot reload after upgrade).
MCP_PIN_FORMAT = 2
GATE_RULES_FORMAT = 1
HOME_LAYOUT_VERSION = 1
ACCEL_PROFILE_VERSION = 1


@dataclass
class ComponentAction:
    component: ComponentId
    action: Literal["skip", "swap", "restart", "migrate", "rebuild", "rewrite", "repair"]
    reason: str
    destructive: bool = False


@dataclass
class DiffPlan:
    from_version: str
    to_version: str
    actions: list[ComponentAction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def needs(self, component: ComponentId) -> bool:
        for a in self.actions:
            if a.component == component and a.action != "skip":
                return True
        return False

    def action_for(self, component: ComponentId) -> ComponentAction | None:
        for a in self.actions:
            if a.component == component:
                return a
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_version": self.from_version,
            "to_version": self.to_version,
            "actions": [asdict(a) for a in self.actions],
            "warnings": list(self.warnings),
        }


def _history_path() -> Path:
    from pipeline.project_id import context_engine_home

    return context_engine_home() / "upgrade_history.json"


def load_upgrade_history() -> dict[str, Any]:
    path = _history_path()
    if not path.is_file():
        return {"applied": [], "components": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"applied": [], "components": {}}
    if not isinstance(data, dict):
        return {"applied": [], "components": {}}
    data.setdefault("applied", [])
    data.setdefault("components", {})
    return data


def save_upgrade_history(data: dict[str, Any]) -> None:
    path = _history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def record_component_applied(component: ComponentId, *, version: str, detail: str = "") -> None:
    hist = load_upgrade_history()
    comps = hist.setdefault("components", {})
    comps[component] = {
        "version": version,
        "detail": detail,
        "applied_at": time.time(),
    }
    applied = hist.setdefault("applied", [])
    applied.append(
        {
            "component": component,
            "version": version,
            "detail": detail,
            "at": time.time(),
        }
    )
    # Keep last 100 events
    hist["applied"] = applied[-100:]
    save_upgrade_history(hist)


def _current_embed_fingerprint() -> str:
    """Stable tag for live embedding ABI (model + expected dim if known)."""
    model = "nomic-ai/CodeRankEmbed"
    dim = 768
    try:
        from pipeline import indexer  # type: ignore

        model = getattr(indexer, "EMBED_MODEL", None) or getattr(
            indexer, "DEFAULT_EMBED_MODEL", model
        )
        dim = int(getattr(indexer, "EMBED_DIM", dim) or dim)
    except Exception:  # noqa: BLE001
        pass
    return f"{model}@dim-{dim}"


def _project_embed_fingerprints() -> list[str]:
    from pipeline.project_id import context_engine_home

    root = context_engine_home() / "projects"
    if not root.is_dir():
        return []
    found: list[str] = []
    for meta_path in root.glob("*/meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        model = meta.get("embed_model") or "unknown"
        dim = meta.get("dim") or "?"
        found.append(f"{model}@dim-{dim}")
    return found


def build_diff_plan(
    *,
    from_version: str,
    to_version: str,
    force_reindex: bool = False,
    force_repair: bool = False,
    skip_package: bool = False,
) -> DiffPlan:
    """Compute which components must change for this upgrade."""
    from pipeline.migrate import SCHEMA_VERSION, detect_migration_needed
    from pipeline.project_id import context_engine_home

    plan = DiffPlan(from_version=from_version, to_version=to_version)
    hist = load_upgrade_history()
    comps = hist.get("components") or {}

    # package
    if skip_package or from_version == to_version:
        plan.actions.append(
            ComponentAction("package", "skip", "package version already at target")
        )
    else:
        plan.actions.append(
            ComponentAction("package", "swap", f"{from_version} → {to_version}")
        )

    # daemon always restarted after package swap; ensure when skip_package
    if skip_package:
        plan.actions.append(
            ComponentAction("daemon", "restart", "ensure daemon matches installed CLI")
        )
    else:
        plan.actions.append(
            ComponentAction("daemon", "restart", "recreate daemon after package swap")
        )

    # index schema
    schema_needed = False
    try:
        from pipeline.managed_repos import managed_repo_paths

        for repo in managed_repo_paths(enrolled_only=False):
            det = detect_migration_needed(repo)
            if det.get("needs_migration"):
                schema_needed = True
                break
    except Exception:  # noqa: BLE001
        # Fall back: any project meta behind SCHEMA_VERSION
        projects = context_engine_home() / "projects"
        if projects.is_dir():
            for meta_path in projects.glob("*/meta.json"):
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    if int(meta.get("schema_version", 1)) < SCHEMA_VERSION:
                        schema_needed = True
                        break
                except Exception:  # noqa: BLE001
                    continue

    if schema_needed:
        plan.actions.append(
            ComponentAction(
                "index_schema",
                "migrate",
                f"bring indexes to schema_version={SCHEMA_VERSION}",
            )
        )
    else:
        plan.actions.append(
            ComponentAction("index_schema", "skip", "schema already current")
        )

    # embeddings
    current_fp = _current_embed_fingerprint()
    project_fps = set(_project_embed_fingerprints())
    embed_mismatch = bool(project_fps) and any(fp != current_fp for fp in project_fps)
    if force_reindex or embed_mismatch:
        reason = (
            "forced by --reindex"
            if force_reindex
            else f"embed ABI mismatch (want {current_fp}; have {sorted(project_fps)})"
        )
        plan.actions.append(
            ComponentAction(
                "embeddings",
                "rebuild",
                reason,
                destructive=True,
            )
        )
        plan.warnings.append(
            "Embeddings rebuild required — old index kept until new index is healthy."
        )
    else:
        plan.actions.append(
            ComponentAction("embeddings", "skip", f"embed ABI ok ({current_fp})")
        )

    # MCP pins + GATE rules — rewrite when package changes or format bump
    mcp_applied = (comps.get("mcp_pins") or {}).get("version")
    rules_applied = (comps.get("gate_rules") or {}).get("version")
    need_mcp = (
        not skip_package
        or mcp_applied != f"{to_version}:v{MCP_PIN_FORMAT}"
        or from_version != to_version
    )
    need_rules = (
        not skip_package
        or rules_applied != f"{to_version}:v{GATE_RULES_FORMAT}"
        or from_version != to_version
    )
    # Always rewrite MCP/rules after any package upgrade so pins match new code.
    if need_mcp or not skip_package:
        plan.actions.append(
            ComponentAction(
                "mcp_pins",
                "rewrite",
                "refresh MCP configs for connected tools / enrolled repos",
            )
        )
    else:
        plan.actions.append(ComponentAction("mcp_pins", "skip", "MCP pin format current"))

    if need_rules or not skip_package:
        plan.actions.append(
            ComponentAction(
                "gate_rules",
                "rewrite",
                "refresh GATE rules / agent instructions",
            )
        )
    else:
        plan.actions.append(
            ComponentAction("gate_rules", "skip", "GATE rules format current")
        )

    # accel / setup
    accel_path = context_engine_home() / "accel.json"
    if force_repair or not accel_path.is_file():
        plan.actions.append(
            ComponentAction(
                "accel",
                "repair",
                "setup --repair" if force_repair else "accel.json missing",
            )
        )
    else:
        plan.actions.append(ComponentAction("accel", "skip", "accel.json present"))

    # home layout
    layout_applied = (comps.get("home_layout") or {}).get("version")
    if layout_applied != str(HOME_LAYOUT_VERSION):
        plan.actions.append(
            ComponentAction(
                "home_layout",
                "migrate",
                f"home layout → v{HOME_LAYOUT_VERSION}",
            )
        )
    else:
        plan.actions.append(ComponentAction("home_layout", "skip", "home layout current"))

    return plan
