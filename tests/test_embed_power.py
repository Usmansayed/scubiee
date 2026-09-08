"""EmbedPower: CodeRank embeddings drive soft seeds, edge capacity, and cut."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from trace_lab.vague_eval import load_vague_prompts, run_vague_eval

FIXTURE = ROOT / "fixtures" / "trace-lab"


@pytest.fixture(scope="module")
def embed_report():
    return run_vague_eval(
        FIXTURE,
        with_graphify=False,
        with_embed_power=True,
        require_real_embeds=False,  # use real if available, else hash
    )


def test_wide_prompt_board():
    data = load_vague_prompts(FIXTURE / "vague_prompts.json")
    assert len(data["prompts"]) >= 28
    families = {p["family"] for p in data["prompts"]}
    assert len(families) >= 16
    assert "adversarial-pay-auth-words" in families
    assert "negation-not-login" in families
    assert "underspec-timeout" in families


def test_embed_power_beats_hash_vector_map(embed_report):
    arms = embed_report["summary"]["arms"]
    assert "embed_power" in arms
    # End-to-end (no gold seed) should beat pure hashed-vector seed picking.
    assert arms["embed_power"]["mean_f1"] >= arms["vector"]["mean_f1"]


def test_embed_power_oracle_strong(embed_report):
    """With gold seed, embed-gated expansion should stay high-precision."""
    ora = embed_report["summary"]["arms"]["embed_power_oracle"]
    assert ora["mean_recall_must"] >= 0.85, ora
    assert ora["mean_f1"] >= 0.80, ora


def test_embed_power_end_to_end_useful(embed_report):
    """No gold seed: embeddings in the loop should clear a usefulness floor."""
    ep = embed_report["summary"]["arms"]["embed_power"]
    assert ep["mean_recall_must"] >= 0.55, ep
    assert ep["mean_f1"] >= 0.50, ep
    assert ep["sum_forbidden_fp"] <= 12, ep


def test_adversarial_payment_auth_words(embed_report):
    row = next(p for p in embed_report["prompts"] if p["id"] == "v21")
    ep = row["arms"]["embed_power"]
    # Must not hot-rank JWT path as the answer to a payment question.
    assert "app/middleware/auth.py::authenticate" not in ep["false_positives_forbidden"] or ep["f1"] >= 0.5
    # Prefer finding charge or at least not dumping auth must_not as all hot
    hot = set(ep["hot"])
    auth_bad = {
        "app/middleware/auth.py::authenticate",
        "app/utils/token.py::decode",
        "app/services/jwt_service.py::JwtService.verify",
    }
    assert len(hot & auth_bad) <= 1 or "app/billing/invoices.py::charge" in hot
