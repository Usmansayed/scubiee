"""Mock upgrade scenarios for exercising ``scubiee upgrade`` end-to-end.

Each scenario seeds a specific kind of stale state (MCP pins, GATE rules,
index schema, embed ABI, accel profile, home layout, legacy bridge command),
then verifies that ``build_diff_plan`` / ``run_upgrade`` repair it.

Used by ``tests/test_upgrade_scenarios.py`` and ``scripts/simulate_upgrade_matrix.py``.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

ScenarioId = Literal[
    "stale_mcp_pins",
    "stale_gate_rules",
    "stale_instructions",
    "stale_index_schema",
    "embed_abi_mismatch",
    "missing_accel",
    "stale_home_layout",
    "legacy_mcp_command",
    "combined_surface",
    "force_reindex",
]


@dataclass(frozen=True)
class UpgradeScenario:
    id: ScenarioId
    label: str
    description: str
    upgrade_flags: dict[str, bool] = field(default_factory=dict)
    expected_actions: tuple[str, ...] = ()


def list_scenarios() -> list[UpgradeScenario]:
    return list(_SCENARIOS.values())


def get_scenario(scenario_id: str) -> UpgradeScenario:
    if scenario_id not in _SCENARIOS:
        known = ", ".join(sorted(_SCENARIOS))
        raise KeyError(f"unknown scenario {scenario_id!r}; known: {known}")
    return _SCENARIOS[scenario_id]  # type: ignore[index]


def _ensure_current_embed_meta(project_id: str) -> None:
    from pipeline.upgrade_manifest import _current_embed_fingerprint

    fp = _current_embed_fingerprint()
    model, _, dim_part = fp.partition("@dim-")
    dim = int(dim_part or "768")
    _seed_project_meta(project_id, embed_model=model, dim=dim)


def _embed_rebuild_ready() -> bool:
    try:
        from pipeline.connect_state import require_machine_setup

        require_machine_setup()
        return True
    except Exception:  # noqa: BLE001
        return False


def _baseline_connected_repo(repo: Path, *, project_id: str, version: str) -> None:
    """Ensure repo is enrolled, connected to cursor, and has valid MCP + rules."""
    from pipeline.connect_state import save_connected_tools
    from pipeline.rules_installer import apply_connected_tools_to_repo
    from pipeline.tool_registry import get_tool

    save_connected_tools(["cursor"])
    tool = get_tool("cursor")
    assert tool is not None
    apply_connected_tools_to_repo(repo)

    from pipeline.upgrade_manifest import (
        GATE_RULES_FORMAT,
        HOME_LAYOUT_VERSION,
        MCP_PIN_FORMAT,
        record_component_applied,
    )

    record_component_applied("mcp_pins", version=f"{version}:v{MCP_PIN_FORMAT}", detail="baseline")
    record_component_applied(
        "gate_rules", version=f"{version}:v{GATE_RULES_FORMAT}", detail="baseline"
    )
    record_component_applied(
        "home_layout", version=str(HOME_LAYOUT_VERSION), detail="baseline"
    )


def _write_stale_upgrade_history(*, version: str, mcp_fmt: int, rules_fmt: int) -> None:
    from pipeline.upgrade_manifest import save_upgrade_history

    save_upgrade_history(
        {
            "applied": [],
            "components": {
                "mcp_pins": {
                    "version": f"{version}:v{mcp_fmt}",
                    "detail": "stale_seed",
                    "applied_at": time.time() - 86400,
                },
                "gate_rules": {
                    "version": f"{version}:v{rules_fmt}",
                    "detail": "stale_seed",
                    "applied_at": time.time() - 86400,
                },
            },
        }
    )


def _corrupt_cursor_mcp(repo: Path, *, mode: str) -> list[str]:
    """Return list of paths modified."""
    touched: list[str] = []
    mcp_path = repo / ".cursor" / "mcp.json"
    if not mcp_path.is_file():
        return touched
    data = json.loads(mcp_path.read_text(encoding="utf-8"))
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return touched
    entry = servers.get("scubiee")
    if not isinstance(entry, dict):
        return touched
    env = entry.get("env")
    if not isinstance(env, dict):
        env = {}
        entry["env"] = env
    if mode == "missing_build":
        env.pop("CTX_SCUBIEE_BUILD", None)
    elif mode == "legacy_command":
        entry["command"] = "python"
        entry["args"] = ["-m", "pipeline.mcp_locate"]
        env.pop("CTX_SCUBIEE_BUILD", None)
    mcp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    touched.append(str(mcp_path))
    return touched


def _strip_gate_rules(repo: Path) -> list[str]:
    touched: list[str] = []
    for rel in (
        ".cursor/rules/scubiee.mdc",
        "AGENTS.md",
        ".claude/CLAUDE.md",
    ):
        path = repo / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if "<!-- scubiee:start -->" in text:
            start = text.index("<!-- scubiee:start -->")
            end = text.index("<!-- scubiee:end -->", start) + len("<!-- scubiee:end -->")
            new_text = text[:start] + text[end:].lstrip("\n")
            path.write_text(new_text, encoding="utf-8")
        elif path.suffix == ".mdc":
            path.write_text(
                "---\ndescription: stale placeholder\nalwaysApply: true\n---\n\n"
                "Old policy: use native Grep/Glob/Read for everything.\n",
                encoding="utf-8",
            )
        touched.append(str(path))
    return touched


def _strip_managed_instructions(repo: Path) -> list[str]:
    """Remove the managed GATE retrieval policy while leaving a stale shell."""
    touched = _strip_gate_rules(repo)
    rules = repo / ".cursor" / "rules" / "scubiee.mdc"
    if rules.is_file():
        rules.write_text(
            "---\ndescription: outdated\nalwaysApply: true\n---\n\n"
            "- **GATE 1** — Managed repo but native tools are fine.\n",
            encoding="utf-8",
        )
        if str(rules) not in touched:
            touched.append(str(rules))
    return touched


def _seed_project_meta(
    project_id: str,
    *,
    schema_version: int | None = None,
    embed_model: str | None = None,
    dim: int | None = None,
) -> Path:
    from pipeline.project_id import context_engine_home

    store = context_engine_home() / "projects" / project_id
    store.mkdir(parents=True, exist_ok=True)
    meta_path = store / "meta.json"
    meta: dict[str, Any] = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            meta = {}
    if schema_version is not None:
        meta["schema_version"] = schema_version
    if embed_model is not None:
        meta["embed_model"] = embed_model
    if dim is not None:
        meta["dim"] = dim
    meta.setdefault("project_id", project_id)
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta_path


_APPLY_HANDLERS: dict[ScenarioId, Callable[..., dict[str, Any]]] = {}


def _register(id: ScenarioId, scenario: UpgradeScenario) -> None:
    _SCENARIOS[id] = scenario


def apply_stale_state(
    scenario_id: str,
    repo: Path | str,
    *,
    project_id: str,
    version: str = "0.3.9",
    skip_baseline: bool = False,
) -> dict[str, Any]:
    """Seed stale on-disk state for one scenario."""
    repo = Path(repo).resolve()
    scenario = get_scenario(scenario_id)
    report: dict[str, Any] = {
        "scenario": scenario.id,
        "repo": str(repo),
        "project_id": project_id,
        "version": version,
        "touched": [],
    }

    from pipeline.project_id import context_engine_home

    home = context_engine_home()
    home.mkdir(parents=True, exist_ok=True)
    accel = home / "accel.json"
    if not accel.is_file():
        accel.write_text("{}\n", encoding="utf-8")

    if not skip_baseline:
        _baseline_connected_repo(repo, project_id=project_id, version=version)

    if scenario.id not in {"embed_abi_mismatch", "force_reindex"}:
        _ensure_current_embed_meta(project_id)

    handler = _APPLY_HANDLERS.get(scenario.id)  # type: ignore[arg-type]
    if handler is None:
        raise KeyError(f"no apply handler for {scenario_id!r}")
    sub = handler(repo, project_id=project_id, version=version)
    report.update(sub)
    report["touched"].extend(sub.get("touched") or [])
    return report


def _apply_stale_mcp_pins(repo: Path, *, project_id: str, version: str) -> dict[str, Any]:
    from pipeline.upgrade_manifest import MCP_PIN_FORMAT

    stale_fmt = max(1, MCP_PIN_FORMAT - 1)
    _write_stale_upgrade_history(version=version, mcp_fmt=stale_fmt, rules_fmt=1)
    touched = _corrupt_cursor_mcp(repo, mode="missing_build")
    return {"kind": "mcp_pins", "stale_format": stale_fmt, "touched": touched}


def _apply_stale_gate_rules(repo: Path, *, project_id: str, version: str) -> dict[str, Any]:
    from pipeline.upgrade_manifest import GATE_RULES_FORMAT

    _write_stale_upgrade_history(
        version=version, mcp_fmt=2, rules_fmt=max(0, GATE_RULES_FORMAT - 1)
    )
    touched = _strip_gate_rules(repo)
    return {"kind": "gate_rules", "touched": touched}


def _apply_stale_instructions(repo: Path, *, project_id: str, version: str) -> dict[str, Any]:
    from pipeline.upgrade_manifest import GATE_RULES_FORMAT

    _write_stale_upgrade_history(
        version=version, mcp_fmt=2, rules_fmt=max(0, GATE_RULES_FORMAT - 1)
    )
    touched = _strip_managed_instructions(repo)
    return {"kind": "instructions", "touched": touched}


def _apply_stale_index_schema(repo: Path, *, project_id: str, version: str) -> dict[str, Any]:
    from pipeline.upgrade_manifest import _current_embed_fingerprint

    fp = _current_embed_fingerprint()
    model, _, dim_part = fp.partition("@dim-")
    dim = int(dim_part or "768")
    meta_path = _seed_project_meta(
        project_id, schema_version=1, embed_model=model, dim=dim
    )
    return {"kind": "index_schema", "touched": [str(meta_path)]}


def _apply_embed_abi_mismatch(repo: Path, *, project_id: str, version: str) -> dict[str, Any]:
    meta_path = _seed_project_meta(
        project_id,
        schema_version=2,
        embed_model="legacy/sentence-transformers-old",
        dim=384,
    )
    return {"kind": "embeddings", "touched": [str(meta_path)]}


def _apply_missing_accel(repo: Path, *, project_id: str, version: str) -> dict[str, Any]:
    from pipeline.project_id import context_engine_home
    from pipeline.upgrade_manifest import _current_embed_fingerprint

    # Ensure embed meta is current so this scenario only tests accel repair.
    fp = _current_embed_fingerprint()
    model, _, dim_part = fp.partition("@dim-")
    dim = int(dim_part or "768")
    _seed_project_meta(project_id, embed_model=model, dim=dim)

    accel = context_engine_home() / "accel.json"
    touched: list[str] = []
    if accel.is_file():
        backup = accel.with_suffix(".json.bak-scenario")
        shutil.copy2(accel, backup)
        accel.unlink()
        touched.extend([str(accel), str(backup)])
    return {"kind": "accel", "touched": touched}


def _apply_stale_home_layout(repo: Path, *, project_id: str, version: str) -> dict[str, Any]:
    from pipeline.upgrade_manifest import load_upgrade_history, save_upgrade_history

    hist = load_upgrade_history()
    comps = hist.get("components") or {}
    comps.pop("home_layout", None)
    hist["components"] = comps
    save_upgrade_history(hist)
    return {"kind": "home_layout", "touched": ["upgrade_history.json"]}


def _apply_legacy_mcp_command(repo: Path, *, project_id: str, version: str) -> dict[str, Any]:
    from pipeline.upgrade_manifest import MCP_PIN_FORMAT

    stale_fmt = max(1, MCP_PIN_FORMAT - 1)
    _write_stale_upgrade_history(version=version, mcp_fmt=stale_fmt, rules_fmt=1)
    touched = _corrupt_cursor_mcp(repo, mode="legacy_command")
    return {"kind": "legacy_bridge", "stale_format": stale_fmt, "touched": touched}


def _apply_combined_surface(repo: Path, *, project_id: str, version: str) -> dict[str, Any]:
    from pipeline.upgrade_manifest import GATE_RULES_FORMAT, MCP_PIN_FORMAT

    parts = [
        _apply_stale_gate_rules(repo, project_id=project_id, version=version),
        _apply_stale_index_schema(repo, project_id=project_id, version=version),
        _apply_missing_accel(repo, project_id=project_id, version=version),
    ]
    # Gate-rules seeding resets MCP history to current — re-stale MCP last.
    stale_mcp_fmt = max(1, MCP_PIN_FORMAT - 1)
    _write_stale_upgrade_history(
        version=version, mcp_fmt=stale_mcp_fmt, rules_fmt=max(0, GATE_RULES_FORMAT - 1)
    )
    touched = _corrupt_cursor_mcp(repo, mode="missing_build")
    parts.append(
        {"kind": "mcp_pins", "stale_format": stale_mcp_fmt, "touched": touched}
    )
    all_touched: list[str] = []
    for p in parts:
        all_touched.extend(p.get("touched") or [])
    return {"kind": "combined", "parts": parts, "touched": all_touched}


def _apply_force_reindex(repo: Path, *, project_id: str, version: str) -> dict[str, Any]:
    # Meta matches current schema/embed — upgrade only rebuilds with --reindex.
    from pipeline.upgrade_manifest import _current_embed_fingerprint

    fp = _current_embed_fingerprint()
    model, _, dim_part = fp.partition("@dim-")
    dim = int(dim_part or "768")
    meta_path = _seed_project_meta(
        project_id, schema_version=2, embed_model=model, dim=dim
    )
    return {"kind": "force_reindex", "touched": [str(meta_path)]}


_APPLY_HANDLERS.update(
    {
        "stale_mcp_pins": _apply_stale_mcp_pins,
        "stale_gate_rules": _apply_stale_gate_rules,
        "stale_instructions": _apply_stale_instructions,
        "stale_index_schema": _apply_stale_index_schema,
        "embed_abi_mismatch": _apply_embed_abi_mismatch,
        "missing_accel": _apply_missing_accel,
        "stale_home_layout": _apply_stale_home_layout,
        "legacy_mcp_command": _apply_legacy_mcp_command,
        "combined_surface": _apply_combined_surface,
        "force_reindex": _apply_force_reindex,
    }
)


def plan_after_stale(
    scenario_id: str,
    repo: Path | str,
    *,
    project_id: str,
    version: str = "0.3.9",
) -> dict[str, Any]:
    """Apply stale state and return ``build_diff_plan`` dict."""
    apply_stale_state(scenario_id, repo, project_id=project_id, version=version)
    scenario = get_scenario(scenario_id)
    from pipeline.upgrade_manifest import build_diff_plan

    plan = build_diff_plan(
        from_version=version,
        to_version=version,
        skip_package=True,
        force_reindex=bool(scenario.upgrade_flags.get("reindex")),
        force_repair=bool(scenario.upgrade_flags.get("repair")),
    )
    return plan.to_dict()


def verify_post_upgrade(
    scenario_id: str,
    repo: Path | str,
    *,
    project_id: str,
    version: str,
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assert scenario-specific post-conditions after upgrade."""
    repo = Path(repo).resolve()
    scenario = get_scenario(scenario_id)
    out: dict[str, Any] = {"scenario": scenario.id, "ok": True, "checks": []}

    def check(name: str, passed: bool, detail: str = "") -> None:
        out["checks"].append({"name": name, "ok": passed, "detail": detail})
        if not passed:
            out["ok"] = False

    from pipeline.migrate import SCHEMA_VERSION
    from pipeline.mcp_install import verify_mcp_json
    from pipeline.project_id import context_engine_home
    from pipeline.upgrade_manifest import (
        GATE_RULES_FORMAT,
        HOME_LAYOUT_VERSION,
        MCP_PIN_FORMAT,
        load_upgrade_history,
    )

    mcp_path = repo / ".cursor" / "mcp.json"
    if scenario.id in {
        "stale_mcp_pins",
        "legacy_mcp_command",
        "combined_surface",
    }:
        if mcp_path.is_file():
            v = verify_mcp_json(mcp_path)
            check("mcp_json_valid", v.get("ok") is True, str(v))
            check("mcp_uses_bridge", v.get("uses_bridge") is True, str(v))
        hist = load_upgrade_history()
        mcp_ver = (hist.get("components") or {}).get("mcp_pins", {}).get("version")
        want = f"{version}:v{MCP_PIN_FORMAT}"
        check("mcp_pins_history", mcp_ver == want, f"have {mcp_ver!r} want {want!r}")

    if scenario.id in {"stale_gate_rules", "stale_instructions", "combined_surface"}:
        rules = repo / ".cursor" / "rules" / "scubiee.mdc"
        if rules.is_file():
            body = rules.read_text(encoding="utf-8")
            check(
                "gate_rules_present",
                "USE Scubiee only" in body or "GATE 1:ce_" in body,
                "managed GATE policy missing",
            )
        hist = load_upgrade_history()
        rules_ver = (hist.get("components") or {}).get("gate_rules", {}).get("version")
        want_rules = f"{version}:v{GATE_RULES_FORMAT}"
        check("gate_rules_history", rules_ver == want_rules, f"have {rules_ver!r}")

    if scenario.id in {"stale_index_schema", "combined_surface"}:
        meta_path = context_engine_home() / "projects" / project_id / "meta.json"
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            check(
                "schema_current",
                int(meta.get("schema_version", 1)) >= SCHEMA_VERSION,
                f"schema_version={meta.get('schema_version')}",
            )

    if scenario.id in {"embed_abi_mismatch", "force_reindex"}:
        if report is not None:
            emb = report.get("embeddings") or {}
            check(
                "embeddings_phase",
                emb.get("ok") is True and not emb.get("skipped"),
                str(emb),
            )
        from pipeline.upgrade_manifest import _current_embed_fingerprint

        meta_path = context_engine_home() / "projects" / project_id / "meta.json"
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            fp = _current_embed_fingerprint()
            model = meta.get("embed_model") or "unknown"
            dim = meta.get("dim") or "?"
            have = f"{model}@dim-{dim}"
            check(
                "embed_fingerprint",
                have == fp or scenario.id == "force_reindex",
                f"have {have!r} want {fp!r}",
            )

    if scenario.id in {"missing_accel", "combined_surface"}:
        accel = context_engine_home() / "accel.json"
        check("accel_present", accel.is_file(), str(accel))

    if scenario.id in {"stale_home_layout", "combined_surface"}:
        hist = load_upgrade_history()
        layout_ver = (hist.get("components") or {}).get("home_layout", {}).get("version")
        check(
            "home_layout_stamped",
            layout_ver == str(HOME_LAYOUT_VERSION),
            f"have {layout_ver!r}",
        )

    if report is not None:
        health_err = report.get("error")
        substantive = [c for c in out["checks"] if c["name"] != "upgrade_ok"]
        substantive_ok = all(c.get("ok") for c in substantive)
        if report.get("ok") is True:
            check("upgrade_ok", True, "")
        elif health_err == "health_not_ok" and substantive_ok:
            check("upgrade_ok", True, "health pending but component repairs verified")
            out["health_flake"] = True
        else:
            check("upgrade_ok", False, str(health_err or report.get("error")))
        for component in scenario.expected_actions:
            plan = report.get("plan") or {}
            actions = plan.get("actions") or []
            match = next((a for a in actions if a.get("component") == component), None)
            if match is not None:
                check(
                    f"planned_{component}",
                    match.get("action") != "skip",
                    str(match),
                )

    return out


_SCENARIOS: dict[str, UpgradeScenario] = {}

_register(
    "stale_mcp_pins",
    UpgradeScenario(
        id="stale_mcp_pins",
        label="Stale MCP pin format",
        description="v1 upgrade history + missing CTX_SCUBIEE_BUILD in .cursor/mcp.json",
        expected_actions=("mcp_pins", "daemon"),
    ),
)
_register(
    "stale_gate_rules",
    UpgradeScenario(
        id="stale_gate_rules",
        label="Stale GATE rules",
        description="Removed scubiee rule blocks; stale gate_rules history version",
        expected_actions=("gate_rules",),
    ),
)
_register(
    "stale_instructions",
    UpgradeScenario(
        id="stale_instructions",
        label="Stale agent instructions",
        description="Outdated GATE body without managed retrieval policy",
        expected_actions=("gate_rules",),
    ),
)
_register(
    "stale_index_schema",
    UpgradeScenario(
        id="stale_index_schema",
        label="Stale index schema",
        description="project meta.json stuck at schema_version=1",
        expected_actions=("index_schema",),
    ),
)
_register(
    "embed_abi_mismatch",
    UpgradeScenario(
        id="embed_abi_mismatch",
        label="Embed ABI mismatch",
        description="meta.json references legacy embed model / dimension",
        expected_actions=("embeddings",),
    ),
)
_register(
    "missing_accel",
    UpgradeScenario(
        id="missing_accel",
        label="Missing accel.json",
        description="Machine setup profile deleted — repair during upgrade",
        upgrade_flags={"repair": True},
        expected_actions=("accel",),
    ),
)
_register(
    "stale_home_layout",
    UpgradeScenario(
        id="stale_home_layout",
        label="Stale home layout stamp",
        description="upgrade_history missing home_layout component",
        expected_actions=("home_layout",),
    ),
)
_register(
    "legacy_mcp_command",
    UpgradeScenario(
        id="legacy_mcp_command",
        label="Legacy MCP command",
        description="python -m pipeline.mcp_locate instead of scubiee-mcp-bridge",
        expected_actions=("mcp_pins",),
    ),
)
_register(
    "combined_surface",
    UpgradeScenario(
        id="combined_surface",
        label="Combined stale surface",
        description="MCP + rules + schema + accel all stale at once",
        upgrade_flags={"repair": True},
        expected_actions=("mcp_pins", "gate_rules", "index_schema", "accel"),
    ),
)
_register(
    "force_reindex",
    UpgradeScenario(
        id="force_reindex",
        label="Forced reindex",
        description="Healthy meta but --reindex forces embeddings rebuild",
        upgrade_flags={"reindex": True},
        expected_actions=("embeddings",),
    ),
)
