"""Declarative per-version upgrade definitions.

Each release registers what should happen to each install component when
crossing *into* that version. ``build_diff_plan`` composes the release chain
from ``from_version`` → ``to_version`` and maps dispositions onto executor
actions — only what changed runs; everything else is preserved.

Dispositions
------------
- **preserve** — leave as-is (skip)
- **clear** — drop stale artifact, rebuild from scratch where needed
- **migrate** — in-place format/metadata migration
- **update** — refresh config/templates in place (MCP pins, GATE rules)
- **reinstall** — replace runtime (package swap, daemon restart, accel repair, re-embed)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pipeline.upgrade_manifest import ComponentAction, ComponentId, DiffPlan

Disposition = Literal["preserve", "clear", "migrate", "update", "reinstall"]

# Strongest disposition wins when multiple releases touch the same component.
_DISPOSITION_RANK: dict[Disposition, int] = {
    "preserve": 0,
    "update": 1,
    "migrate": 2,
    "clear": 3,
    "reinstall": 4,
}


@dataclass(frozen=True)
class StepSpec:
    """What one release wants done to a single component."""

    component: ComponentId
    disposition: Disposition
    reason: str
    destructive: bool = False
    pin_format: int | None = None  # mcp_pins / gate_rules template generation


@dataclass
class ReleaseSpec:
    """Upgrade instructions introduced by package version ``version``."""

    version: str
    notes: str = ""
    steps: dict[ComponentId, StepSpec] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "notes": self.notes,
            "steps": {
                comp: {
                    "disposition": step.disposition,
                    "reason": step.reason,
                    "destructive": step.destructive,
                    **({"pin_format": step.pin_format} if step.pin_format is not None else {}),
                }
                for comp, step in self.steps.items()
            },
        }


@dataclass
class ComposedUpgrade:
    """Merged steps for a version range."""

    from_version: str
    to_version: str
    releases: list[ReleaseSpec]
    steps: dict[ComponentId, StepSpec]

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_version": self.from_version,
            "to_version": self.to_version,
            "releases": [r.to_dict() for r in self.releases],
            "steps": {
                comp: {
                    "disposition": step.disposition,
                    "reason": step.reason,
                    "destructive": step.destructive,
                }
                for comp, step in self.steps.items()
            },
        }


_REGISTRY: dict[str, ReleaseSpec] = {}


def _parse_version(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in str(version or "0").strip().split("."):
        digits = ""
        for ch in piece:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits or "0"))
    return tuple(parts) or (0,)


def register_release(spec: ReleaseSpec) -> None:
    key = spec.version.strip()
    if not key:
        raise ValueError("release version required")
    _REGISTRY[key] = spec


def get_release(version: str) -> ReleaseSpec | None:
    return _REGISTRY.get(version.strip())


def list_releases() -> list[ReleaseSpec]:
    return [_REGISTRY[k] for k in sorted(_REGISTRY, key=_parse_version)]


def releases_between(from_version: str, to_version: str) -> list[ReleaseSpec]:
    """Return registered releases with ``from < v <= to``."""
    lo = _parse_version(from_version)
    hi = _parse_version(to_version)
    if lo >= hi:
        return []
    out: list[ReleaseSpec] = []
    for ver in sorted(_REGISTRY, key=_parse_version):
        parsed = _parse_version(ver)
        if lo < parsed <= hi:
            out.append(_REGISTRY[ver])
    return out


def _merge_step(existing: StepSpec | None, incoming: StepSpec) -> StepSpec:
    if existing is None:
        return incoming
    if _DISPOSITION_RANK[incoming.disposition] >= _DISPOSITION_RANK[existing.disposition]:
        return StepSpec(
            component=incoming.component,
            disposition=incoming.disposition,
            reason=incoming.reason,
            destructive=existing.destructive or incoming.destructive,
            pin_format=incoming.pin_format if incoming.pin_format is not None else existing.pin_format,
        )
    return existing


def compose_upgrade(from_version: str, to_version: str) -> ComposedUpgrade:
    """Merge release steps across the upgrade path."""
    releases = releases_between(from_version, to_version)
    merged: dict[ComponentId, StepSpec] = {}
    for release in releases:
        for comp, step in release.steps.items():
            merged[comp] = _merge_step(merged.get(comp), step)
    return ComposedUpgrade(
        from_version=from_version,
        to_version=to_version,
        releases=releases,
        steps=merged,
    )


# --- Step builders (use in release modules) ---------------------------------

def _step(component: ComponentId, disposition: Disposition, reason: str, **kwargs: Any) -> StepSpec:
    destructive = bool(kwargs.get("destructive", disposition in {"clear", "reinstall"}))
    return StepSpec(
        component=component,
        disposition=disposition,
        reason=reason,
        destructive=destructive,
        pin_format=kwargs.get("pin_format"),
    )


def preserve_component(component: ComponentId, *, reason: str = "unchanged in this release") -> StepSpec:
    return _step(component, "preserve", reason, destructive=False)


def clear_component(component: ComponentId, *, reason: str) -> StepSpec:
    return _step(component, "clear", reason, destructive=True)


def migrate_component(component: ComponentId, *, reason: str) -> StepSpec:
    return _step(component, "migrate", reason, destructive=False)


def update_component(
    component: ComponentId,
    *,
    reason: str,
    pin_format: int | None = None,
) -> StepSpec:
    return _step(component, "update", reason, destructive=False, pin_format=pin_format)


def reinstall_component(component: ComponentId, *, reason: str) -> StepSpec:
    return _step(component, "reinstall", reason, destructive=True)


def release(version: str, *, notes: str = "") -> Callable[[type], type]:
    """Class decorator to register a release definition."""

    def decorator(cls: type) -> type:
        steps: dict[ComponentId, StepSpec] = {}
        for name in cls.__dict__:
            if name.startswith("_"):
                continue
            val = getattr(cls, name)
            if isinstance(val, StepSpec):
                steps[val.component] = val
        register_release(ReleaseSpec(version=version, notes=notes or getattr(cls, "__doc__", "") or "", steps=steps))
        return cls

    return decorator


def disposition_to_action(component: ComponentId, step: StepSpec) -> ComponentAction:
    """Map declarative disposition → supervisor executor action."""
    disp = step.disposition
    if disp == "preserve":
        return ComponentAction(component, "skip", step.reason, destructive=False)

    if component == "package":
        return ComponentAction(component, "swap" if disp == "reinstall" else "skip", step.reason)

    if component == "daemon":
        return ComponentAction(component, "restart", step.reason)

    if component == "index_schema":
        if disp in {"migrate", "update", "clear", "reinstall"}:
            return ComponentAction(
                component,
                "migrate",
                step.reason,
                destructive=disp in {"clear", "reinstall"},
            )
        return ComponentAction(component, "skip", step.reason)

    if component == "embeddings":
        if disp in {"clear", "reinstall"}:
            return ComponentAction(component, "rebuild", step.reason, destructive=True)
        return ComponentAction(component, "skip", step.reason)

    if component in {"mcp_pins", "gate_rules"}:
        if disp in {"update", "clear", "reinstall"}:
            return ComponentAction(component, "rewrite", step.reason)
        return ComponentAction(component, "skip", step.reason)

    if component == "accel":
        if disp == "reinstall":
            return ComponentAction(component, "repair", step.reason)
        return ComponentAction(component, "skip", step.reason)

    if component == "home_layout":
        if disp in {"migrate", "update", "clear", "reinstall"}:
            return ComponentAction(component, "migrate", step.reason)
        return ComponentAction(component, "skip", step.reason)

    return ComponentAction(component, "skip", step.reason)


def apply_runtime_guards(
    plan: DiffPlan,
    composed: ComposedUpgrade,
    *,
    force_reindex: bool = False,
    force_repair: bool = False,
    runtime: dict[ComponentId, StepSpec | None],
) -> None:
    """Promote preserve → action when on-disk state requires it."""
    from pipeline.upgrade_manifest import ComponentAction

    def _set(component: ComponentId, action: str, reason: str, *, destructive: bool = False) -> None:
        for i, existing in enumerate(plan.actions):
            if existing.component == component:
                plan.actions[i] = ComponentAction(component, action, reason, destructive=destructive)  # type: ignore[arg-type]
                return
        plan.actions.append(ComponentAction(component, action, reason, destructive=destructive))  # type: ignore[arg-type]

    for component, step in runtime.items():
        if step is None:
            continue
        mapped = disposition_to_action(component, step)
        if mapped.action != "skip":
            _set(component, mapped.action, mapped.reason, destructive=mapped.destructive)

    if force_reindex:
        _set("embeddings", "rebuild", "forced by --reindex", destructive=True)
    if force_repair:
        _set("accel", "repair", "forced by --repair")

    # Surface release notes as warnings when destructive steps are scheduled.
    for rel in composed.releases:
        for step in rel.steps.values():
            if step.destructive and plan.needs(step.component):
                plan.warnings.append(f"{rel.version}: {step.reason}")


def build_plan_from_registry(
    *,
    from_version: str,
    to_version: str,
    skip_package: bool = False,
    force_reindex: bool = False,
    force_repair: bool = False,
    runtime: dict[ComponentId, StepSpec | None] | None = None,
) -> DiffPlan:
    """Build a DiffPlan from registered releases + runtime guards."""
    composed = compose_upgrade(from_version, to_version)
    plan = DiffPlan(from_version=from_version, to_version=to_version)

    # Package + daemon defaults for any version crossing.
    if skip_package or from_version == to_version:
        plan.actions.append(
            ComponentAction("package", "skip", "package version already at target")
        )
        plan.actions.append(
            ComponentAction("daemon", "restart", "ensure daemon matches installed CLI")
        )
    else:
        plan.actions.append(
            ComponentAction("package", "swap", f"{from_version} → {to_version}")
        )
        plan.actions.append(
            ComponentAction("daemon", "restart", "recreate daemon after package swap")
        )

    all_components: list[ComponentId] = [
        "index_schema",
        "embeddings",
        "mcp_pins",
        "gate_rules",
        "accel",
        "home_layout",
    ]

    for component in all_components:
        step = composed.steps.get(component)
        if step is None:
            plan.actions.append(
                ComponentAction(component, "skip", "no release step; preserve by default")
            )
        else:
            mapped = disposition_to_action(component, step)
            plan.actions.append(mapped)

    apply_runtime_guards(
        plan,
        composed,
        force_reindex=force_reindex,
        force_repair=force_repair,
        runtime=runtime or {},
    )

    plan.warnings.insert(0, f"release_path: {[r.version for r in composed.releases]}")
    plan.release_path = [r.version for r in composed.releases]
    return plan
