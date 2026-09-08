"""Smoke + hard-board check for semantic_trace (no faction policy)."""



from __future__ import annotations



import sys

from pathlib import Path



import pytest



ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT / "packages"))



from trace_lab.strategies import compile_bundle

from trace_lab.verify_board import run_verify

from trace_lab.vague_eval import prompt_to_case



FIXTURE = ROOT / "fixtures" / "trace-lab"





def test_semantic_trace_registered_and_runs():

    nodes, graph, lex, tracers = compile_bundle(

        FIXTURE, with_graphify=False, with_embed_power=True, require_real_embeds=False

    )

    assert "semantic_trace" in tracers

    board = (FIXTURE / "verify_hard.json").read_text(encoding="utf-8")

    import json



    raw = json.loads(board)["cases"][0]

    gold = prompt_to_case(raw)

    hm = tracers["semantic_trace"](gold, nodes, graph, lex)

    assert hm.strategy == "semantic_trace"

    assert hm.cells and hm.cells[0].node_id == gold.seed.id





@pytest.fixture(scope="module")

def hard_report():

    return run_verify(FIXTURE, board_name="verify_hard.json", require_real_embeds=False)





def test_semantic_trace_on_scoreboard(hard_report):

    s = hard_report["summary"]

    assert "semantic_trace" in s

    # Soft metrics present

    assert "mean_ndcg" in s["semantic_trace"]

    assert "mean_must_at_10" in s["semantic_trace"]

    # Should collect a non-trivial share of musts on average

    assert s["semantic_trace"]["mean_recall_must"] >= 0.55


