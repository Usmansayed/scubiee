# Context Engine — full retrieval pipeline

Date: 2026-08-02

## Product pipeline

```
repo files
   │
   ├─ Merkle scan (SHA-256 file tree) → {added, modified, removed}
   ├─ Graphify AST → RepoIR + graph.json
   ├─ Symbol-span chunks + graph metadata injection
   ├─ Embed (Ollama nomic-embed-text, with offline fallback)
   ├─ TurboQuant compress (Google ICLR 2026–style, 4-bit default)
   └─ FAISS IndexIDMap2(IndexFlatIP) for cosine/IP search
         │
         ▼
   Conductor D_rerank (Graphify + BM25 + dense FAISS)
```

## Vector DB (FAISS + TurboQuant)

Root: `~/.context-engine/vectordb/` (override `CTX_VECTORDB_ROOT`)

```
vectordb/
  catalog.json
  collections/
    <repoName>_<cwdHash>/
      meta.json          # name, cwd, dim, bits, ntotal
      faiss.index        # FAISS IndexIDMap2(IndexFlatIP)
      turboquant.npz     # compressed embeddings
      ids.npy
      payloads.jsonl     # file/line/symbol per vector id
```

API: `pipeline.vectordb.VectorDatabase` — `create_collection`, `get_or_create_for_cwd`, `list_collections`, `drop_collection`; collection `add` / `delete` / `search` / `save`.

Each working directory gets its own collection (isolated vector space).


## CLI

```powershell
$env:PYTHONPATH = "packages"
.\.venv\Scripts\python -m pipeline index fixtures/mini-repo --force
.\.venv\Scripts\python -m pipeline search "login validatePassword" fixtures/mini-repo
.\.venv\Scripts\python -m pipeline status fixtures/mini-repo
```

## Compression

Default **4 bits/coord** TurboQuant reference codec (~4× vs float32 with uint8/dim packing in v0.1; upgrade to bit-packing + official `turboquant` package later).
Queries stay float32 (asymmetric). FAISS searches dequantized (or persisted) vectors.
