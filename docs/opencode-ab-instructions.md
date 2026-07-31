# OpenCode brief: Graphify vs D_rerank retrieval A/B

You are opening the **context-engine** repo to run a **human/agent judgment test**.  
Do **not** use OpenCode’s (or Cursor’s) built-in semantic / codebase search for this experiment.  
Use **only** the Conductor A/B surfaces below so we can compare **pure Graphify** vs **D_rerank**.

---

## What this project is testing

| Mode | What it is | Strength |
|------|------------|----------|
| **graphify** | Structure graph only (AST symbols, imports, calls → seed + BFS). No embeddings. | Fast, precise when the query names real identifiers/paths. Often fewer files to open → fewer tokens. |
| **d_rerank** | Our conductor: Graphify + BM25 + dense (nomic) min-rank pool, then lexical/path rerank. | Better on paraphrases / vague wording. Slightly slower and often slightly more token cost when both already hit. |

**Question we need you to answer:** On real coding tasks in this repo, is D_rerank worth keeping, or is Graphify alone good enough (and cheaper)?

Corpus under test: `testdata/frontend-mcp` (~673 Python files, ~3148 chunks).  
Shared engine: `packages/conductor/service.py`.

A prior automated gold-bank run (46 queries) is in `out/conductor_prod_ab_agent_run.json`. Your job is **agentic / qualitative** rating on tasks you actually try to solve — not re-running that script only.

---

## Prerequisites (start these first)

1. **Ollama** running with `nomic-embed-text`  
   - Embed endpoint expected: `http://localhost:11434/api/embed`

2. **Python venv** already at `.venv` (deps installed).

3. From repo root (`context-engine`):

```powershell
cd C:\Users\usman\Downloads\context-engine
$env:PYTHONPATH = "packages;."
.\.venv\Scripts\python -u conductor_api.py
```

Leave that process running. First start can take ~30–45s while indexes warm.  
Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health
```

You want `"ok": true`, `"ready": true`.

### Optional: MCP (if OpenCode supports MCP config)

```json
{
  "mcpServers": {
    "conductor-ab": {
      "command": "C:/Users/usman/Downloads/context-engine/.venv/Scripts/python.exe",
      "args": ["-u", "C:/Users/usman/Downloads/context-engine/conductor_mcp.py"],
      "env": {
        "PYTHONPATH": "C:/Users/usman/Downloads/context-engine/packages;C:/Users/usman/Downloads/context-engine"
      }
    }
  }
}
```

MCP tools (same engine as HTTP):

- `conductor_compare(query, top_k)` — **use this by default**
- `conductor_search(query, mode, top_k)` — single arm
- `conductor_status()` — readiness

If MCP is awkward, **HTTP is enough**.

---

## How you must search (rules)

1. When you need code location / context, call **`/compare`** (or `conductor_compare`) with your natural-language question.
2. **Do not** use built-in codebase/semantic search for locating files in this test.
3. You **may** open files that either mode returned (read tool / editor). That is expected — we measure which list pointed you right with less waste.
4. Prefer `top_k: 5` unless you need more.

### HTTP compare example

```powershell
$body = @{
  query = "where do we choose which coordination playbook to run"
  top_k = 5
} | ConvertTo-Json

Invoke-RestMethod http://127.0.0.1:8765/compare -Method Post -Body $body -ContentType "application/json"
```

### What the response means

```text
modes.graphify.hits[]   → ranked files from pure Graphify
modes.d_rerank.hits[]   → ranked files from D_rerank
agreement.same_top1     → both agree on #1 file?
agreement.jaccard_top_k → overlap of the two top-k lists
agreement.graphify_only / d_rerank_only → files only one side returned
```

Each hit has `file`, `score`, `preview`, channel scores when present.

---

## What to do in the session (procedure)

Run **at least 10–15** real questions. Mix styles:

| Style | Example queries |
|-------|-----------------|
| Symbol / path | `playbook_selector.py`, `observe_bridge`, `llms_txt analyzer` |
| Paraphrase | “chooses which coordination playbook should run given the project situation” |
| Confusion | “null graph stub — not the real CRG impl” |
| Domain | Figma token store, SEO crawlability, consistency snapshot gate, a11y reviewer |
| Soft / error | recovery policy, safe tools for cancelled runs |

For **each** query:

1. Call compare.
2. Look at both ranked lists **before** opening files.
3. Open the smallest set of files needed to answer (usually top‑1 or top‑2).
4. Fill one row in the rating table below (copy into your reply or `out/opencode_ab_ratings.md`).

---

## Rating sheet (fill this)

For each query, rate:

| Field | How to fill |
|-------|-------------|
| `query` | Exact string you sent to compare |
| `same_top1` | true/false from response |
| `file_you_needed` | Path of the file that actually answered the question (or `NONE`) |
| `graphify_rank` | 1–5 if that file appears in Graphify list, else `miss` |
| `d_rerank_rank` | 1–5 if in D list, else `miss` |
| `winner` | `tie` \| `graphify` \| `d_rerank` \| `miss_both` |
| `tokens_feel` | `graphify_cheaper` \| `d_cheaper` \| `same` \| `unclear` — based on how many / how big files you opened before you were done |
| `confidence` | 1–5 (5 = sure that file was the right one) |
| `notes` | One short line |

### Winner rules

- **tie** — both lists had the needed file at the same rank (or both rank‑1 and you would open the same file).
- **graphify** — only Graphify had it, or Graphify ranked it clearly better and you used Graphify’s file first successfully.
- **d_rerank** — only D had it, or D ranked it clearly better / saved you from a wrong Graphify top hit.
- **miss_both** — neither top‑5 had what you needed (say what you eventually found by other means, if any).

### Example row

```md
| where is playbook selector | true | .../playbook_selector.py | 1 | 1 | tie | same | 5 | both correct immediately |
```

---

## Suggested starter queries (optional)

You can invent your own; these are warm-ups from our banks:

1. `coordination_intelligence planning playbook_selector.py PlaybookSelector`
2. `chooses which coordination playbook should run given the current project situation`
3. `bridges live browser observation into the resource intelligence ranking path`
4. `null graph stub when CRG is unavailable — not the real crg_impl extractor`
5. `seo_intelligence ai_visibility analyzers llms_txt.py`
6. `checks whether a site published guidance that AI crawlers should read`
7. `figma_intelligence connection token_store.py PAT persistence`
8. `consistency intelligence snapshot gate`
9. `accessibility reviewer in design sense`
10. `after proposing SEO fixes, re-run checks to confirm they actually landed`

---

## What to report back when done

Write a short summary:

1. **Counts:** how many `tie` / `graphify` / `d_rerank` / `miss_both`.
2. **When D uniquely helped** — paste those queries (paraphrase? confusion?).
3. **When Graphify was enough or cheaper** — any case D only added noise/latency.
4. **Verdict (pick one):**
   - `KEEP_D` — D_rerank should stay as default search for agents  
   - `GRAPHIFY_ONLY` — Graphify alone is enough for this corpus/workflow  
   - `HYBRID_POLICY` — Graphify for symbol-ish queries; D for paraphrase / soft language  
5. **Token gut check:** Did D feel like it saved you from reading the wrong files often enough to justify ~2–3× retrieval latency and sometimes larger top‑k dumps?

Paste the filled rating table + verdict into chat (or save `out/opencode_ab_ratings.md`).

---

## Quick reference

| Action | Command / tool |
|--------|----------------|
| Start API | `.\.venv\Scripts\python -u conductor_api.py` (`PYTHONPATH=packages;.`) |
| Health | `GET http://127.0.0.1:8765/health` |
| A/B search | `POST http://127.0.0.1:8765/compare` `{ "query", "top_k": 5 }` |
| One mode | `POST /search` `{ "query", "mode": "graphify"\|"d_rerank", "top_k": 5 }` |
| MCP | `conductor_compare` / `conductor_search` / `conductor_status` |
| Prior auto results | `out/conductor_prod_ab_agent_run.json` |
| This brief | `docs/opencode-ab-instructions.md` |

**Do not** treat Cursor/OpenCode built-in semantic search as either arm of this A/B.  
**Do** treat `graphify` and `d_rerank` lists from Conductor as the only retrieval sources under test.
