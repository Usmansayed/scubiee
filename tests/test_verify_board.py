"""Hard correctness on diverse verify board (must⊆hot, must_not∩hot=∅)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from trace_lab.verify_board import load_verify_board, run_verify

FIXTURE = ROOT / "fixtures" / "trace-lab"


@pytest.fixture(scope="module")
def verify_report():
    return run_verify(FIXTURE, require_real_embeds=False)


def test_verify_board_is_diverse():
    board = load_verify_board(FIXTURE / "verify_board.json")
    assert len(board["cases"]) >= 20
    families = {c["family"] for c in board["cases"]}
    assert len(families) >= 15
    assert {"cache", "notify", "limits", "job-notify", "adversarial-pay"} <= families


def test_poly_embed_matches_polytrace_correctness(verify_report):
    """Proper embed use: rerank/prune without losing musts or admitting must_not."""
    s = verify_report["summary"]
    assert s["polytrace"]["correct"] == s["polytrace"]["n"]
    assert s["poly_embed"]["correct"] == s["poly_embed"]["n"]
    assert s["poly_embed"]["accuracy"] >= s["polytrace"]["accuracy"]
    # Embed-as-primary-walk must not be the winner on this board.
    if "embed_power_oracle" in s:
        assert s["poly_embed"]["correct"] > s["embed_power_oracle"]["correct"]


def test_report_flags_incorrect_cases_explicitly(verify_report):
    """Every case has a boolean correct flag — we verify data, not only F1."""
    for row in verify_report["cases"]:
        for arm, data in row["arms"].items():
            assert "correct" in data
            assert isinstance(data["correct"], bool)
            if not data["correct"]:
                assert data["missing_must"] or data["forbidden_hot"], (row["id"], arm)
