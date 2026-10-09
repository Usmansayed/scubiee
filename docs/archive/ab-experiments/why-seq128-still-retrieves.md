# Why seq=128 search still finds the right code

**Question:** If we truncate chunks hard for speed, why doesn’t semantic search fall apart?

**Quick test (this machine, frontend-mcp fast index):** `out/bench_seq128_why_it_works.json`

| Metric | Result |
|--------|--------|
| Index | CodeRankEmbed, **seq≈128**, fast `max_chars=512` |
| Corpus | 3148 chunks |
| Probe suite | 10 symbol / soft-ish queries |
| Quality (top-5 file needles) | **10/10** |
| Avg latency (warm) | ~207 ms |

So on this repo, short embeddings still retrieve the right modules.

---

## First: the “80% cut” intuition is often wrong

People imagine: *one huge file → keep first 20% → embed garbage.*

What we actually store:

1. **AST / symbol chunks** (function/class spans), not whole files.  
2. Fast mode **caps body text at ~512 characters** (`128 * 4`), not “80% of a novel.”  
3. Measured on this index:

| Chunk size (chars) | Value |
|--------------------|-------|
| mean | ~358 |
| median (p50) | ~406 |
| p90 / max | **512** (cap) |
| Share sitting on the cap | ~42% |

So for **~58% of chunks**, the model already sees essentially the whole (short) span.  
Only the long ones lose the **tail** of the function body — not a random mid-file slice.

`seq=128` then means: embed about the first **128 tokens** of that already-small text.

---

## Why retrieval stays good anyway

### 1. The useful signal is at the front
Code search queries usually match:

- symbol names (`probe_validation_form`, `handle_session_start`)
- path / module cues (`form_probe.py`, `handlers.py`)
- short docstrings / signatures

We **prepend metadata** before embed (path, symbol, graph neighbors). That header is exactly what CodeRank needs to point at the right place. Research on code RAG calls this out repeatedly: AST chunks + path/symbol enrichment beat long raw windows ([AST-aware chunking](https://dreaming.press/posts/how-to-chunk-code-for-rag.html), [symbol-granular chunking](https://www.catnipcoder.com/symbol-granular-chunking-for-code-retrieval)).

### 2. Embeddings are for *finding*, not *explaining*
The vector answers: “which span is about this?”  
It does **not** need the full implementation to rank `form_probe.py` above unrelated SEO code.  
After a hit, the engine reads **live disk** for the real lines (preview / agent Read). Truncation hurts *understanding inside the vector*, not *opening the right file*.

### 3. Hybrid fusion covers what dense misses
Conductor doesn’t use dense alone:

- **BM25** loves exact identifiers even if the vector only saw the name  
- **Graphify** affinity boosts structural neighbors  
- **D / R_plan rerank** uses path + lexical overlap again  

So even a “thin” embedding is enough seed; lexical + graph pull the winner up.

### 4. CodeRank is trained for code identity
Bi-encoders like CodeRankEmbed are tuned so **names and signatures** dominate similarity. A truncated body still shares the same identity tokens as the query.

---

## What *does* get worse with short seq

| Scenario | Risk |
|----------|------|
| Soft query, meaning buried mid-function | Higher miss rate |
| Two similar helpers, differ only in the long body | More confusion |
| “Explain this algorithm” from the vector alone | Thin — must read full span |

That’s why **seq=256/512** is better for max quality, and **128** is a speed trade for laptop indexing — not because search is magic, but because **locate ≠ compress the whole function into one vector**.

---

## Mental model

```text
Query "probe_validation_form"
        │
        ├─ dense: head of chunk still has name + path metadata  → form_probe.py
        ├─ BM25: exact token match                              → form_probe.py
        └─ graph / rerank: reinforce                             → top hit
        │
        └─ read disk span (full function) for the agent
```

**Bottom line:** We don’t “search 20% of random text.” We search **small AST units whose identifying head is intact**, fuse with BM25/graph, then load the full code from disk. That’s why 10/10 on the quick probe still happens with seq=128.
