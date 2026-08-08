"""Pruning decides what to delete, so the decision itself needs coverage."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "prune_engine_state", ROOT / "scripts" / "prune_engine_state.py"
)
prune = importlib.util.module_from_spec(_spec)
sys.modules["prune_engine_state"] = prune
assert _spec and _spec.loader
_spec.loader.exec_module(prune)


def test_project_is_dead_only_when_every_path_is_gone(tmp_path):
    live = tmp_path / "live"
    live.mkdir()
    gone = tmp_path / "gone"
    registry = {
        "projects": {
            "ce_live": {"paths": [str(live)]},
            "ce_gone": {"paths": [str(gone)]},
            "ce_partial": {"paths": [str(gone), str(live)]},
        }
    }
    assert prune.dead_project_ids(registry) == ["ce_gone"]


def test_entry_without_paths_is_never_pruned():
    registry = {"projects": {"ce_unknown": {"paths": []}, "ce_bad": "not-a-dict"}}
    assert prune.dead_project_ids(registry) == []


def test_keep_protects_a_live_repo_and_its_collection(tmp_path):
    gone = tmp_path / "gone"
    registry = {"projects": {"ce_gone": {"paths": [str(gone)]}}}
    catalog = {"collections": [{"name": "gone_1234", "cwd": str(gone)}]}

    assert prune.dead_project_ids(registry, keep={str(gone)}) == []
    assert prune.dead_collections(catalog, keep={str(gone)}) == []


def test_dead_collections_follow_missing_source_dirs(tmp_path):
    live = tmp_path / "live"
    live.mkdir()
    catalog = {
        "collections": [
            {"name": "live_1", "cwd": str(live)},
            {"name": "gone_1", "cwd": str(tmp_path / "gone")},
            {"name": "no_cwd"},
        ]
    }
    assert prune.dead_collections(catalog) == ["gone_1"]
