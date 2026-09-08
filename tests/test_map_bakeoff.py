"""Map bakeoff: graph+BM25 vs dense for seed finding."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from trace_lab.map_bakeoff import run_map_bakeoff

FIXTURE = ROOT / "fixtures" / "trace-lab"


@pytest.fixture(scope="module")
def bakeoff():
    return run_map_bakeoff(FIXTURE, with_real_embeds=False)


def test_map_bakeoff_runs_multiple_arms(bakeoff):
    names = {r["arm"] for r in bakeoff["summary"]}
    assert "bm25" in names
    assert "graph_boost" in names
    assert "graph_ppr" in names


def test_graph_bm25_not_worse_than_plain_bm25(bakeoff):
    by = {r["arm"]: r for r in bakeoff["summary"]}
    # Graph reinforcement should not destroy BM25 on this board
    assert by["graph_boost"]["mean_f1"] + 0.05 >= by["bm25"]["mean_f1"] * 0.9
