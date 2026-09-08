"""Load gold tracing cases from fixtures/trace-lab/cases/*.json."""

from __future__ import annotations

import json
from pathlib import Path

from trace_lab.types import GoldCase, GoldRef


def _ref(raw: dict) -> GoldRef:
    return GoldRef(
        file=str(raw["file"]).replace("\\", "/"),
        symbol=str(raw["symbol"]),
        why=str(raw.get("why") or ""),
    )


def load_case(path: Path) -> GoldCase:
    data = json.loads(path.read_text(encoding="utf-8"))
    seed = _ref(data["seed"])
    return GoldCase(
        id=str(data["id"]),
        title=str(data.get("title") or data["id"]),
        query=str(data["query"]),
        seed=seed,
        must=[_ref(x) for x in data.get("must") or []],
        should=[_ref(x) for x in data.get("should") or []],
        must_not=[_ref(x) for x in data.get("must_not") or []],
        gold_rank=[str(x) for x in data.get("gold_rank") or []],
        notes=str(data.get("notes") or ""),
    )


def load_cases(cases_dir: Path) -> list[GoldCase]:
    paths = sorted(cases_dir.glob("*.json"))
    return [load_case(p) for p in paths]


def default_fixture_root() -> Path:
    return Path(__file__).resolve().parents[2] / "fixtures" / "trace-lab"
