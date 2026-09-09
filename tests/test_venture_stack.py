"""Internal stack tests for venture tools — must pass before bakeoffs / blind-10.

Uses real ``~/.scubiee`` (overrides pytest CTX_HOME isolation) so DML + product FAISS
are the same stack production agents hit.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

# Every test here points CTX_HOME at the real ~/.scubiee and searches the live
# product index, so a default run both depends on this machine's enrollment and
# can spend minutes re-syncing it. Opt in with `pytest -m integration`.
pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "trace-lab"
REAL_HOME = Path.home() / ".scubiee"
GATE_PID = "ce_d9cb766c3820091ed9ffbc64ef33063c"


@pytest.fixture
def real_scubiee_home(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Override autouse CTX_HOME isolation so product accel + index are visible."""
    assert REAL_HOME.is_dir(), f"missing real scubiee home {REAL_HOME}"
    monkeypatch.setenv("CTX_HOME", str(REAL_HOME))
    monkeypatch.setenv("CTX_TRUST_ID_FILE", "1")
    monkeypatch.delenv("CTX_ALLOW_TEST_HOME", raising=False)
    try:
        from pipeline import accel

        monkeypatch.setattr(accel, "ACCEL_PATH", REAL_HOME / "accel.json", raising=False)
    except Exception:
        pass
    return REAL_HOME


@pytest.fixture(scope="module")
def ort_providers():
    import onnxruntime as ort

    return list(ort.get_available_providers())


def test_t1_dml_provider_present(ort_providers):
    assert "DmlExecutionProvider" in ort_providers, ort_providers


def test_t2_product_embedder_dml_code_rank(real_scubiee_home):
    from pipeline.embedder import Embedder

    emb = Embedder(quiet=True)
    mat = emb.embed_many(["def authenticate(user):\n    return True\n"], is_query=False)
    assert emb.backend == "fastembed"
    assert emb.device == "dml"
    assert mat.shape == (1, 768)
    assert float(np.linalg.norm(mat[0])) > 0.5


def test_t3_product_faiss_returns_hits(real_scubiee_home):
    from pipeline.project_id import index_is_usable, resolve_project
    from pipeline.searcher import search_repo
    from trace_lab.semantic_venture import _product_faiss_files, product_faiss_ok

    ref = resolve_project(ROOT)
    assert ref.project_id == GATE_PID, ref.project_id
    store = Path(ref.store_dir)
    assert index_is_usable(store), f"store unusable: {store}"

    hits = search_repo(ROOT, "authenticate verify token session", top_k=5, use_server=False)
    assert len(hits) >= 1, "product FAISS empty — index/publication broken"
    assert getattr(hits[0], "file", None)

    status = product_faiss_ok(ROOT, "authenticate verify token")
    assert status["ok"] is True, status
    assert status["n_hits"] >= 1
    assert not status.get("error")

    files = _product_faiss_files(ROOT, "session isolation", top_k=3)
    assert len(files) >= 1
    err = getattr(_product_faiss_files, "last_error", "")
    assert not err, err


def test_t4_index_publication_usable_product_corpus(real_scubiee_home):
    from pipeline.artifact_guard import validate_manifest
    from pipeline.project_id import index_is_usable, resolve_project

    ref = resolve_project(ROOT)
    assert ref.project_id == GATE_PID
    store = Path(ref.store_dir)
    assert index_is_usable(store), f"store unusable: {store}"
    report = validate_manifest(store)
    assert report.get("ok"), report
    meta = json.loads((store / "meta.json").read_text(encoding="utf-8"))
    root = str(meta.get("root") or "").replace("/", "\\").lower()
    assert "fixtures\\trace-lab" not in root, f"contaminated index root={meta.get('root')}"
    assert int(meta.get("chunks") or 0) >= 5000, meta.get("chunks")


def test_t5_embed_field_require_real_on_fixture(real_scubiee_home):
    from trace_lab.corpus import extract_nodes
    from trace_lab.embed_field import EmbedField

    nodes = extract_nodes(FIXTURE)
    assert nodes, "fixture corpus empty"
    cache = FIXTURE / ".embed_cache" / "coderank_test.jsonl"
    field = EmbedField(nodes, cache_path=cache, require_real=True, quiet=True)
    assert str(field.backend).startswith("real:"), field.backend
    assert field.dim == 768
    aff = field.affinities("authenticate JWT verify credentials")
    assert aff
    assert max(aff.values()) > 0.05


def test_t6_propose_verify_keeps_seed_and_records_faiss(real_scubiee_home):
    from trace_lab.embed_field import EmbedField
    from trace_lab.lsp_index import build_lsp_index
    from trace_lab.semantic_venture import propose_and_verify
    from trace_lab.strategies import compile_bundle
    from trace_lab.types import HeatCell, Heatmap

    nodes, graph, _lex, _tr = compile_bundle(
        FIXTURE, with_graphify=False, with_embed_power=False, require_real_embeds=False
    )
    lsp = build_lsp_index(FIXTURE, nodes, graph)
    field = EmbedField(
        nodes,
        cache_path=FIXTURE / ".embed_cache" / "coderank_test.jsonl",
        require_real=True,
        quiet=True,
    )
    seed = next(iter(nodes))
    hm = Heatmap(
        strategy="seed_only",
        cells=[HeatCell(seed, 1.0, "seed", (seed,))],
        extra={},
    )
    out = propose_and_verify(
        hm,
        seed_id=seed,
        query="authenticate JWT verify token credentials",
        nodes=nodes,
        graph=graph,
        lsp=lsp,
        field=field,
        extra_graph=None,
        root=ROOT,
        strategy="test_propose",
        top_k=8,
        min_sem=0.35,
        verify="path2",
        use_product_faiss=True,
    )
    assert out.cells
    assert any(c.node_id == seed and c.score >= 0.99 for c in out.cells)
    meta = out.extra or {}
    assert "proposed_admitted" in meta
    assert "faiss_files" in meta


def test_t7_venture_arms_smoke(real_scubiee_home):
    from trace_lab.strategies import compile_bundle
    from trace_lab.vague_eval import prompt_to_case

    _nodes, _graph, _lex, tracers = compile_bundle(
        FIXTURE, with_graphify=True, with_embed_power=True, require_real_embeds=True
    )
    needed = [
        "composite_v1",
        "venture_propose_verify",
        "venture_multiview",
        "venture_semantic_frontier",
    ]
    for name in needed:
        assert name in tracers, f"missing arm {name}; have={sorted(tracers)}"

    board = json.loads((FIXTURE / "verify_hard.json").read_text(encoding="utf-8"))
    gold = prompt_to_case(board["cases"][0])
    for name in needed:
        hm = tracers[name](gold, _nodes, _graph, _lex)
        assert hm.cells, name
        assert gold.seed.id in {c.node_id for c in hm.cells} or any(
            c.score >= 0.45 for c in hm.cells
        ), name
