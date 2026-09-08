"""Seeded PolyTrace (no embed) vs EmbedPower (embed) — same seed+prompt."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from trace_lab.seeded_compare import load_seeded_prompts, run_seeded_compare

FIXTURE = ROOT / "fixtures" / "trace-lab"


@pytest.fixture(scope="module")
def seeded_report():
    return run_seeded_compare(FIXTURE, require_real_embeds=False)


def test_seeded_prompts_have_collected_context():
    data = load_seeded_prompts(FIXTURE / "seeded_prompts.json")
    assert len(data["prompts"]) >= 8
    for p in data["prompts"]:
        assert p["seed"]["file"] and p["seed"]["symbol"]
        assert p["must"], p["id"]
        assert p.get("context_notes"), p["id"]


def test_both_arms_strong_with_gold_seed(seeded_report):
    s = seeded_report["summary"]
    assert s["polytrace"]["mean_recall_must"] >= 0.90, s["polytrace"]
    assert s["embed_power"]["mean_recall_must"] >= 0.85, s["embed_power"]
    assert s["polytrace"]["mean_f1"] >= 0.85, s["polytrace"]
    assert s["embed_power"]["mean_f1"] >= 0.80, s["embed_power"]


def test_polytrace_still_competitive_without_embed(seeded_report):
    """With seed given, structure-only PolyTrace should not collapse vs embeds."""
    s = seeded_report["summary"]
    assert s["polytrace"]["mean_f1"] + 0.05 >= s["embed_power"]["mean_f1"]
