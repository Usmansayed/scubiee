"""OPEN-B exploration: the warm deadline is one effective value on every surface.

Property 1 (Bug Condition): for any process env E, every deadline surface equals
``effective_warm_deadline_ms(E)``:

- ``max(1000, int(E["CTX_WARM_DEADLINE_MS"]))`` when the key is set and parses;
- the shipped default 90000 (same as the install pin) otherwise.

Surfaces: ``warm_contract.warm_deadline_ms()``, ``runtime_controller.warm_deadline_ms()``,
``ReadySnapshot.as_status_fields()``, ``warm_status_fields()`` and
``start_attach_warm_pipeline(...)["deadline_ms"]`` (with a fake RuntimeController, so
no HTTP probe to the live ``:8765``). Status surfaces also carry
``warm_deadline_source`` = ``"env"`` when the value came from the env, else ``"default"``.

This test is written against the expected behavior and is EXPECTED TO FAIL on the
unfixed code (both readers default to 30000; no ``warm_deadline_source`` field).

Cases come from a seeded generator (no Hypothesis). Re-run one case with
``pytest tests/test_open_b_warm_deadline.py -k <case id>``.

**Validates: Requirements 1.1, 1.2, 2.1, 2.2**
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import pytest

SEED = 20260926
ENV_KEY = "CTX_WARM_DEADLINE_MS"
SHIPPED_DEFAULT_MS = 90_000
FLOOR_MS = 1000
_UNSET = object()


def effective_warm_deadline_ms(raw: Any) -> int:
    """Oracle: the one value every surface must report for env value *raw*."""
    if raw is _UNSET:
        return SHIPPED_DEFAULT_MS
    try:
        return max(FLOOR_MS, int(str(raw).strip()))
    except ValueError:
        return SHIPPED_DEFAULT_MS


def expected_source(raw: Any) -> str:
    """``env`` when the deadline came from the env value, else ``default``."""
    if raw is _UNSET:
        return "default"
    try:
        int(str(raw).strip())
    except ValueError:
        return "default"
    return "env"


def _build_cases() -> list[tuple[str, Any]]:
    rng = random.Random(SEED)
    cases: list[tuple[str, Any]] = [
        # Concrete cases from the task: unpinned host and the install pin.
        ("unset", _UNSET),
        ("pin-90000", "90000"),
        ("legacy-30000", "30000"),
    ]
    for i in range(6):
        cases.append((f"valid-{i}", str(rng.randint(FLOOR_MS, 600_000))))
    for i in range(4):
        cases.append((f"below-floor-{i}", str(rng.randint(-5000, FLOOR_MS - 1))))
    alphabet = "abcdefghijklmnopqrstuvwxyz_-!"
    for i in range(4):
        n = rng.randint(1, 8)
        cases.append((f"invalid-{i}", "".join(rng.choice(alphabet) for _ in range(n))))
    cases.append(("invalid-empty", ""))
    cases.append(("invalid-units", f"{rng.randint(1, 120)}s"))
    return cases


CASES = _build_cases()


class _FakeController:
    """Stands in for ``RuntimeController`` so attach never probes live HTTP."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def ensure(self, repo, reason):  # noqa: ANN001
        from pipeline.runtime_controller import ReadySnapshot

        self.calls.append((str(repo), str(reason)))
        return ReadySnapshot(
            state="STARTING",
            engine_ok=False,
            embedder_loaded=False,
            ast_ready=False,
        )


def _read_surfaces(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    from pipeline import mcp_lifecycle as life
    from pipeline import runtime_controller as rc
    from pipeline import warm_contract as wc

    # warm_status_fields freezes process globals; keep them local to this case.
    monkeypatch.setattr(wc, "_STARTED_AT", None)
    monkeypatch.setattr(wc, "_READY_AT", None)
    monkeypatch.setenv("CTX_MCP_ATTACH_WARM", "1")
    fake = _FakeController()
    monkeypatch.setattr(rc.RuntimeController, "get", classmethod(lambda cls: fake))

    snap_fields = rc.ReadySnapshot(
        state="READY",
        engine_ok=True,
        embedder_loaded=True,
        ast_ready=True,
        soft_search_ready=True,
    ).as_status_fields()
    wsf = wc.warm_status_fields(engine_healthy=True, embedder_loaded=True)
    attach = life.start_attach_warm_pipeline(tmp_path)
    assert fake.calls, "start_attach_warm_pipeline must go through the fake controller"

    return {
        "warm_contract.warm_deadline_ms()": wc.warm_deadline_ms(),
        "runtime_controller.warm_deadline_ms()": rc.warm_deadline_ms(),
        "ReadySnapshot.as_status_fields().warm_deadline_ms": snap_fields.get("warm_deadline_ms"),
        "warm_status_fields().warm_deadline_ms": wsf.get("warm_deadline_ms"),
        "start_attach_warm_pipeline().deadline_ms": attach.get("deadline_ms"),
        "ReadySnapshot.as_status_fields().warm_deadline_source": snap_fields.get(
            "warm_deadline_source", "<missing>"
        ),
        "warm_status_fields().warm_deadline_source": wsf.get("warm_deadline_source", "<missing>"),
    }


@pytest.mark.parametrize(
    ("case_id", "raw"),
    CASES,
    ids=[case_id for case_id, _ in CASES],
)
def test_warm_deadline_is_one_effective_value(
    case_id: str, raw: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    if raw is _UNSET:
        monkeypatch.delenv(ENV_KEY, raising=False)
    else:
        monkeypatch.setenv(ENV_KEY, raw)

    want_ms = effective_warm_deadline_ms(raw)
    want_src = expected_source(raw)
    got = _read_surfaces(monkeypatch, tmp_path)

    mismatches = []
    for name, value in got.items():
        want = want_src if name.endswith("warm_deadline_source") else want_ms
        if value != want:
            mismatches.append(f"  {name} = {value!r} (expected {want!r})")

    env_repr = "<unset>" if raw is _UNSET else repr(raw)
    assert not mismatches, (
        f"seed={SEED} case={case_id} {ENV_KEY}={env_repr} "
        f"effective={want_ms} source={want_src}\n" + "\n".join(mismatches)
    )
