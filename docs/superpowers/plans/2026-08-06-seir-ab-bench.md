# SEIR A/B Bench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prototype deterministic post-AST embed texts and A/B them against CE baseline on `testdata/frontend-mcp` without changing production indexer defaults.

**Architecture:** Small `packages/seir/` renderers + `scripts/seir_ab_bench.py` that imports Embedder/FAISS/gold. Shared function/class spans; five arms; temp collections under `out/seir_ab/`.

**Tech Stack:** Python 3.11+, stdlib `ast`, existing `pipeline.embedder.Embedder`, `pipeline.vectordb`, `conductor.hard_v2_gold.HARD_V2`, optional Graphify `graph.json`.

## Global Constraints

- Do not modify production indexer / MCP / daemon / `chunk_compress` defaults.
- No LLMs — rule-based only.
- Hard cap default 512 chars per chunk text.
- Corpus: `testdata/frontend-mcp`.
- Gold: `HARD_V2` (`files_substr` hit).
- Embedder: CodeRank via existing accel (fail fast if unavailable).

---

### Task 1: SEIR core types + caps + spans

**Files:**
- Create: `packages/seir/__init__.py`
- Create: `packages/seir/caps.py`
- Create: `packages/seir/spans.py`
- Create: `packages/seir/types.py`
- Test: `tests/test_seir_spans.py`

**Interfaces:**
- Produces: `SpanContext(file, start_line, end_line, symbol, source, node_kind)`, `truncate(text, max_chars) -> str`, `estimate_tokens(text) -> int`, `iter_python_spans(repo: Path, *, limit: int | None) -> list[SpanContext]`

- [ ] **Step 1: Write failing tests for truncate + span extraction**

```python
from pathlib import Path
from seir.caps import truncate, estimate_tokens
from seir.spans import iter_python_spans

def test_truncate_prefers_head():
    assert truncate("abcdef", 4) == "abcd"
    assert len(truncate("x" * 100, 512)) <= 512

def test_spans_from_fixture(tmp_path: Path):
    p = tmp_path / "m.py"
    p.write_text("def login(email, password):\n    return 1\n\nclass A:\n    def f(self):\n        pass\n", encoding="utf-8")
    spans = iter_python_spans(tmp_path)
    names = {s.symbol for s in spans}
    assert "login" in names
    assert any(s.symbol and s.symbol.endswith(".f") or s.symbol == "A.f" or "f" in (s.symbol or "") for s in spans)
```

- [ ] **Step 2: Implement types/caps/spans (Python ast walk of `.py` under repo, skip junk dirs)**

- [ ] **Step 3: pytest passes**

- [ ] **Step 4: Commit** `feat(seir): spans and char caps`

---

### Task 2: Renderers (five arms)

**Files:**
- Create: `packages/seir/baseline.py`
- Create: `packages/seir/ast_tree.py`
- Create: `packages/seir/rels.py`
- Create: `packages/seir/semantic.py`
- Create: `packages/seir/importance.py`
- Create: `packages/seir/render.py`
- Test: `tests/test_seir_render.py`

**Interfaces:**
- Consumes: `SpanContext`, `truncate`
- Produces: `ARMS`, `render(arm: str, span: SpanContext, *, max_chars: int = 512, graph=None, baseline_text: str | None = None) -> str`

**Arm rules:**
- `baseline`: `baseline_text` if provided else `mix`-style compress of `File/Symbol` + source (import `compress_chunk` / `prepare_enriched_from_parts` — do not change those modules).
- `ast_tree`: compact indented dump of the span’s AST subtree (FunctionDef/ClassDef only; omit docstrings bodies longer than 1 line summary).
- `rels`: Calls / Reads / Writes / Returns from AST; CalledBy from optional NetworkX/graphify graph if passed.
- `semantic`: keyword heuristics for Purpose/Boundary; Inputs=args; Output=return name hints; Deps=imported/called top names.
- `importance`: score calls (bcrypt/jwt/auth high; log/debug/metric low); emit top lines only.

- [ ] **Step 1: Failing golden tests on a tiny login() fixture**

- [ ] **Step 2: Implement renderers + `render()` dispatcher**

- [ ] **Step 3: pytest `tests/test_seir_render.py` PASS**

- [ ] **Step 4: Commit** `feat(seir): five deterministic representation arms`

---

### Task 3: Bench script + HARD_V2 eval

**Files:**
- Create: `scripts/seir_ab_bench.py`
- Modify: none in production packages

**Behavior:**
1. Clear reliance on polluted `CTX_HOME` — use `out/seir_ab/home` as isolated store root via env for FAISS only.
2. Build spans from repo (optional `--limit-spans`).
3. Load graph from `PipelineStore(repo).base/graph.json` if present, else `repo/graphify-out/graph.json` if present.
4. For each arm: render → Embedder CodeRank → FaissCollection under `out/seir_ab/<arm>/` → eval HARD_V2 with dense-only top_k (no conductor stack required — pure dense A/B on representation quality).
5. Write `out/seir_ab_<ts>.json` with quality + density + timing.

Dense-only eval is intentional: isolates representation effect from BM25/graph fusion.

- [ ] **Step 1: Implement script**

- [ ] **Step 2: Smoke** `python -u scripts/seir_ab_bench.py --limit-spans 40 --arms baseline,ast_tree`

- [ ] **Step 3: Full run** all arms on frontend-mcp + HARD_V2

- [ ] **Step 4: Commit** script + note results path (do not commit large FAISS blobs)

---

## Spec coverage

| Spec item | Task |
|-----------|------|
| Isolated plug-in B | 3 |
| Arms baseline/ast/rels/semantic/importance | 2 |
| frontend-mcp + HARD_V2 | 3 |
| Metrics R@k MRR nDCG tokens size latency | 3 |
| No production path changes | all |
| Density cap 512 | 1–2 |
