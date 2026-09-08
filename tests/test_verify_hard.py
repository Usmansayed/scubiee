"""Hard board: 50 tough multi-must cases — expect far from perfect scores."""



from __future__ import annotations



import sys

from pathlib import Path



import pytest



ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT / "packages"))



from trace_lab.verify_board import load_verify_board, run_verify



FIXTURE = ROOT / "fixtures" / "trace-lab"





def test_verify_hard_is_large_and_diverse():

    board = load_verify_board(FIXTURE / "verify_hard.json")

    assert len(board["cases"]) == 50

    families = {c["family"] for c in board["cases"]}

    assert len(families) == 50

    must_sizes = [len(c["must"]) for c in board["cases"]]

    assert min(must_sizes) >= 3

    assert sorted(must_sizes)[25] >= 5





@pytest.fixture(scope="module")

def hard_report():

    return run_verify(FIXTURE, board_name="verify_hard.json", require_real_embeds=False)





def test_hard_board_is_not_trivially_solved(hard_report):

    """If accuracy is near 1.0 the board is too easy / overfit."""

    s = hard_report["summary"]

    assert s["polytrace"]["accuracy"] < 0.85

    assert s["poly_embed"]["accuracy"] < 0.85

    # Still better than chance: collect some large related slices

    assert s["polytrace"]["correct"] >= 8

    for row in hard_report["cases"]:

        for arm, data in row["arms"].items():

            assert "correct" in data

            if not data["correct"]:

                assert data["missing_must"] or data["forbidden_hot"], (row["id"], arm)


