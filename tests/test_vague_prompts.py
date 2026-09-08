"""Vague human prompts: map(+vector) → PolyTrace heatmap agreement."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from trace_lab.retrieve import query_intent
from trace_lab.vague_eval import load_vague_prompts, run_vague_eval

FIXTURE = ROOT / "fixtures" / "trace-lab"


@pytest.fixture(scope="module")
def vague_report():
    return run_vague_eval(FIXTURE, with_graphify=False, with_embed_power=False)


def test_vague_prompt_file_has_at_least_20():
    data = load_vague_prompts(FIXTURE / "vague_prompts.json")
    assert len(data["prompts"]) >= 28
    families = {p["family"] for p in data["prompts"]}
    assert len(families) >= 16


def test_oracle_polytrace_holds_on_vague_prompts(vague_report):
    """Given the right seed, PolyTrace should stay strong even on vague wording."""
    ora = vague_report["summary"]["arms"]["oracle"]
    assert ora["mean_recall_must"] >= 0.95, ora
    assert ora["mean_f1"] >= 0.90, ora
    assert ora["sum_forbidden_fp"] <= 2, ora


def test_oracle_paraphrases_agree_on_heatmap(vague_report):
    """Same family + oracle seed → nearly the same hot set."""
    assert vague_report["summary"]["oracle_mean_family_jaccard"] >= 0.85
    assert vague_report["summary"]["oracle_families_identical"] >= 4


def test_mapfuse_beats_pure_vector_seed(vague_report):
    arms = vague_report["summary"]["arms"]
    assert arms["mapfuse"]["mean_f1"] >= arms["vector"]["mean_f1"]
    assert arms["mapfuse"]["seed_ok"] >= arms["vector"]["seed_ok"]


def test_vector_channel_is_actually_used(vague_report):
    """Vector-only arm must find at least some correct seeds (not zero)."""
    vec = vague_report["summary"]["arms"]["vector"]
    assert vec["seed_ok"] >= 8, vec
    assert vec["mean_f1"] > 0.3, vec


def test_intent_on_vague_phrases():
    assert query_intent("people get kicked out after a while, where is that timeout?") == "config"
    assert query_intent("auth middleware is printing something somewhere") == "site"
    assert query_intent("who even reads that TOKEN_TTL constant?") == "refs"
    assert query_intent("theres something with bearer headers and loading the account after claims, where is that?") == "flow"
