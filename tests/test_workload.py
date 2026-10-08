"""Workload classifier tests (spec task 4.5).

The classifier answers one question: is the pending index work *small* (absorb
silently) or *substantial* (minutes-scale, surface to the agent)? The threshold
is wall-clock TIME (``CTX_SUBSTANTIAL_SECONDS``), not a file count, plus a
corpus-fraction trip and a forced-reindex override.

Offline; CTX_HOME tmp; no live engine/embedder. Stores are fabricated on disk
with the real ``chunks.jsonl`` / ``meta.json`` / ``merkle.json`` layout so the
classifier's exact-chunk-count and throughput reads exercise real code paths.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    # Pin the time budget + default throughput so tests are deterministic
    # regardless of host env.
    monkeypatch.setenv("CTX_SUBSTANTIAL_SECONDS", "25")
    monkeypatch.setenv("CTX_SUBSTANTIAL_FRACTION", "0.4")
    monkeypatch.setenv("CTX_DEFAULT_EMBED_CPS", "20")
    yield


# ---- fabrication helpers ----------------------------------------------------

def _make_store(repo, project_id="ce_wl"):
    from pipeline.project_id import projects_root
    from pipeline.store import PipelineStore

    base = projects_root() / project_id
    base.mkdir(parents=True, exist_ok=True)
    return PipelineStore(repo, base_dir=base, project_id=project_id, resolve=False)


def _write_file(repo, rel, lines):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(f"x = {i}" for i in range(lines)) + "\n", encoding="utf-8")
    return p


def _persist_chunks(store, per_file: dict[str, int]):
    """Write chunks.jsonl with `count` rows per file (real `file`-key layout)."""
    rows = []
    for rel, count in per_file.items():
        for n in range(count):
            rows.append(json.dumps({"id": f"{rel}:{n}", "file": rel, "text": "y"}))
    store.chunks_path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _set_cps(store, cps: float):
    meta = store.load_meta()
    meta["embed_cps"] = cps
    store.save_meta(meta)


# ---- file-type weighting ----------------------------------------------------

def test_file_type_weighting():
    from pipeline.workload import file_type_weight

    assert file_type_weight("a.py") == 1.0
    assert file_type_weight("src/x.ts") == 1.0
    assert file_type_weight("README.md") == 0.5
    assert file_type_weight("config.yaml") == 0.3
    # unknown / binary / vendored -> free (never embedded)
    assert file_type_weight("logo.png") == 0.0
    assert file_type_weight("data.bin") == 0.0


# ---- small vs substantial ---------------------------------------------------

def test_a_few_small_code_files_is_not_substantial(tmp_path):
    from pipeline.workload import classify_workload

    repo = tmp_path / "repo"
    repo.mkdir()
    added = []
    for i in range(5):
        rel = f"m{i}.py"
        _write_file(repo, rel, 30)  # ~ 2 chunks each
        added.append(rel)
    store = _make_store(repo)

    pending = classify_workload([*added], [], [], repo=repo, store=store, corpus_size=400)
    assert pending.substantial is False
    assert pending.estimated_seconds < 25.0


def test_massive_paste_is_substantial(tmp_path):
    from pipeline.workload import classify_workload

    repo = tmp_path / "repo"
    repo.mkdir()
    added = []
    # 1000 new code files, ~8 chunks each -> ~8000 units / 20 cps = 400s >> 25s
    for i in range(1000):
        rel = f"gen/f{i}.py"
        _write_file(repo, rel, 200)
        added.append(rel)
    store = _make_store(repo)

    pending = classify_workload(added, [], [], repo=repo, store=store, corpus_size=50_000)
    assert pending.substantial is True
    assert pending.estimated_units > 0
    assert pending.estimated_seconds >= 25.0


def test_full_reindex_is_always_substantial(tmp_path):
    from pipeline.workload import classify_workload

    repo = tmp_path / "repo"
    repo.mkdir()
    _write_file(repo, "a.py", 5)
    store = _make_store(repo)

    pending = classify_workload(
        ["a.py"], [], [], repo=repo, store=store, corpus_size=10, full_reindex=True
    )
    assert pending.substantial is True
    assert pending.reason == "full_reindex"
    assert pending.action == "scubiee index . --force"


def test_corpus_fraction_trips_substantial(tmp_path):
    from pipeline.workload import classify_workload

    repo = tmp_path / "repo"
    repo.mkdir()
    # modify 60 already-indexed files, each 10 chunks -> 600 units of a 1000
    # corpus = 0.6 fraction >= 0.4; but 600/20cps = 30s which is also > budget,
    # so pin a FAST throughput to isolate the fraction trip from the time trip.
    per_file = {}
    modified = []
    for i in range(60):
        rel = f"f{i}.py"
        _write_file(repo, rel, 1)
        per_file[rel] = 10
        modified.append(rel)
    store = _make_store(repo)
    _persist_chunks(store, per_file)
    _set_cps(store, 100_000.0)  # throughput so high the time trip can't fire

    pending = classify_workload(
        [], modified, [], repo=repo, store=store, corpus_size=1000
    )
    assert pending.estimated_seconds < 25.0, "time trip should be inert here"
    assert pending.substantial is True
    assert pending.reason == "bulk_paste"


def test_removed_only_is_cheap(tmp_path):
    from pipeline.workload import classify_workload

    repo = tmp_path / "repo"
    repo.mkdir()
    store = _make_store(repo)
    removed = [f"old{i}.py" for i in range(500)]

    # Deletes carry only a token prune cost (0.5/path), so 500 deletes stay well
    # under budget and silent — a pure delete is cheap even in bulk.
    pending = classify_workload([], [], removed, repo=repo, store=store, corpus_size=1000)
    assert pending.substantial is False
    assert pending.estimated_units < 300  # 500 * 0.5 = 250, not minutes-scale


def test_many_tiny_files_is_substantial_via_per_file_overhead(tmp_path):
    """A large COUNT of files is minutes-scale work even when each is tiny.

    Regression for the adversarial finding: 300 trivially-small offline files
    estimated ~15s (not substantial) and stayed silent, yet genuinely took
    ~150s to drain. The per-file overhead term makes the count register.
    """
    from pipeline.workload import classify_workload

    repo = tmp_path / "repo"
    repo.mkdir()
    added = []
    for i in range(300):
        rel = f"paste/tiny_{i}.py"
        _write_file(repo, rel, 2)  # ~1 chunk each by content alone
        added.append(rel)
    store = _make_store(repo)

    pending = classify_workload(added, [], [], repo=repo, store=store, corpus_size=9000)
    assert pending.substantial is True
    # content alone would be ~300 units (~15s); overhead lifts it minutes-scale.
    assert pending.estimated_seconds >= 25.0


def test_a_dozen_small_files_still_silent(tmp_path):
    """The overhead must not over-flag ordinary small multi-file edits."""
    from pipeline.workload import classify_workload

    repo = tmp_path / "repo"
    repo.mkdir()
    added = [f"m_{i}.py" for i in range(8)]
    for rel in added:
        _write_file(repo, rel, 20)
    store = _make_store(repo)

    pending = classify_workload(added, [], [], repo=repo, store=store, corpus_size=9000)
    assert pending.substantial is False


# ---- throughput sourcing ----------------------------------------------------

def test_unmeasured_throughput_uses_conservative_default(tmp_path):
    from pipeline.workload import throughput_chunks_per_s

    repo = tmp_path / "repo"
    repo.mkdir()
    store = _make_store(repo)
    # no embed_cps persisted -> default (pinned to 20 by the fixture)
    assert throughput_chunks_per_s(store) == 20.0


def test_measured_throughput_overrides_default(tmp_path):
    from pipeline.workload import throughput_chunks_per_s

    repo = tmp_path / "repo"
    repo.mkdir()
    store = _make_store(repo)
    _set_cps(store, 250.0)
    assert throughput_chunks_per_s(store) == 250.0


def test_record_embed_throughput_ema(tmp_path):
    from pipeline.workload import record_embed_throughput, throughput_chunks_per_s

    repo = tmp_path / "repo"
    repo.mkdir()
    store = _make_store(repo)

    # first sample seeds the average directly
    record_embed_throughput(store, chunks=1000, seconds=10.0)  # 100 cps
    assert throughput_chunks_per_s(store) == pytest.approx(100.0, abs=0.1)

    # a second, faster sample is folded via EMA (0.3*200 + 0.7*100 = 130)
    record_embed_throughput(store, chunks=1000, seconds=5.0)  # 200 cps
    assert throughput_chunks_per_s(store) == pytest.approx(130.0, abs=0.5)


def test_record_throughput_ignores_implausible_samples(tmp_path):
    from pipeline.workload import record_embed_throughput, throughput_chunks_per_s

    repo = tmp_path / "repo"
    repo.mkdir()
    store = _make_store(repo)
    # tiny batch dominated by fixed overhead -> ignored, default stays
    record_embed_throughput(store, chunks=2, seconds=5.0)
    assert throughput_chunks_per_s(store) == 20.0
    # zero/negative guarded
    record_embed_throughput(store, chunks=0, seconds=5.0)
    record_embed_throughput(store, chunks=100, seconds=0.0)
    assert throughput_chunks_per_s(store) == 20.0


# ---- exact-count vs line-estimate -------------------------------------------

def test_modified_uses_exact_indexed_chunk_count(tmp_path):
    from pipeline.workload import estimate_units

    repo = tmp_path / "repo"
    repo.mkdir()
    # file is tiny on disk (1 line) but was indexed with 40 chunks; the exact
    # count must dominate the 1-line estimate.
    _write_file(repo, "big.py", 1)
    store = _make_store(repo)
    _persist_chunks(store, {"big.py": 40})

    # 40 exact chunks + one PER_FILE_OVERHEAD_UNITS (10) = 50; the exact count
    # still dominates the 1-line estimate (which would be ~1 + overhead).
    from pipeline.workload import PER_FILE_OVERHEAD_UNITS

    units = estimate_units([], ["big.py"], [], repo=repo, store=store)
    assert units == 40 + int(PER_FILE_OVERHEAD_UNITS)


def test_doc_weighting_halves_cost(tmp_path):
    from pipeline.workload import PER_FILE_OVERHEAD_UNITS, estimate_units

    repo = tmp_path / "repo"
    repo.mkdir()
    _write_file(repo, "code.py", 250)   # ~10 chunks * 1.0
    _write_file(repo, "doc.md", 250)    # ~10 chunks * 0.5
    store = _make_store(repo)

    # The per-file overhead (same for both) is added on top of the weighted
    # chunk cost; subtract it to check the chunk portion halves for docs.
    oh = int(PER_FILE_OVERHEAD_UNITS)
    code_chunks = estimate_units(["code.py"], [], [], repo=repo, store=store) - oh
    doc_chunks = estimate_units(["doc.md"], [], [], repo=repo, store=store) - oh
    assert doc_chunks == pytest.approx(code_chunks * 0.5, abs=1)
