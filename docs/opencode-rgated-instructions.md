# OpenCode task: soft A/B — D_rerank vs R_gated

You are testing whether the **soft router (`r_gated`)** beats production **`d_rerank`** on vague, human-style questions over **`testdata/frontend-mcp` only**.

Do **not** use OpenCode/Cursor built-in semantic or codebase search for locating files.  
Use **only** the Conductor API (or MCP) below.

---

## What you are comparing

| Mode | What it is |
|------|------------|
| **d_rerank** | Production default — Graphify + BM25 + dense, min-rank pool, path rerank |
| **r_gated** | Soft router — same D base, but on SOFT queries may **ensure** lexically grounded Graphify hits into top-5 without clobbering D’s top-3 |

Lab note (do not treat as your verdict): automated soft-30 said r_gated ≈ 80% R@5 vs D 73%, better MRR than blunt floor; consistency/diverse still prefer D as global default. Your job is **agent judgment** on soft queries.

Corpus: `testdata/frontend-mcp` only. Do not ask about outer `context-engine` packages.

---

## Start the API (required)

```powershell
cd C:\Users\usman\Downloads\context-engine
$env:PYTHONPATH = "packages;."
.\.venv\Scripts\python -u conductor_api.py
```

Wait until indexes warm (~30–45s). Check:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health
```

Need `"ok": true`, `"ready": true`, and modes including `r_gated` / `both_rg`.

### Primary endpoint for this test

```powershell
$body = @{ query = "YOUR SOFT QUESTION HERE"; top_k = 5 } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8765/compare_rgated -Method Post -Body $body -ContentType "application/json"
```

Response fields to use:

- `modes.d_rerank.hits[]` — production list  
- `modes.r_gated.hits[]` — router list  
- `agreement.same_top1`  
- `agreement.jaccard_top_k`  
- `agreement.d_rerank_only` / `agreement.r_gated_only`

### Also allowed

```powershell
# single arm
$body = @{ query = "..."; top_k = 5; mode = "r_gated" } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8765/search -Method Post -Body $body -ContentType "application/json"
```

### Optional MCP

If configured, prefer tool **`conductor_compare_rgated`**.  
(`conductor_compare` is Graphify vs D — **not** this test.)

---

## Rules

1. Exactly **20** soft queries (invent them; do not copy a fixed example list as your only set).
2. Queries must be **vague / human / agent-style** — no filenames (`*.py`), no full module paths, no exact CamelCase API names.
3. Every question must be about **frontend-mcp** product surfaces (coordination, browser/observe, SEO, Figma, consistency, design sense, MCP wiring, recovery/cancel, resources/icons/routes, etc.).
4. After each `/compare_rgated`, open the fewest files needed to decide which list was right.
5. Save the sheet to `out/opencode_rgated_ratings.md` and paste the summary in chat.

---

## Rating sheet (fill all 20)

| # | query | same_top1 | file_you_needed | d_rank | r_gated_rank | winner | tokens_feel | confidence | notes |

- `d_rank` / `r_gated_rank`: 1–5 or `miss`  
- `winner`: `tie` | `d_rerank` | `r_gated` | `miss_both`  
- `tokens_feel`: `d_cheaper` | `r_cheaper` | `same` | `unclear`  

Winner rules:

- **r_gated** — only router had the needed file, or ranked it clearly better and you used that file first successfully  
- **d_rerank** — only D had it, or D ranked it better / router added noise  
- **tie** — same useful file at same (or equally good) rank  
- **miss_both** — neither top-5 worked  

---

## Topic coverage (frontend-mcp — soft wording only)

Spread intents across: playbooks/situation, live browser/observe, code graph fallbacks, SEO/AI visibility, Figma auth/tokens/review, consistency gates, a11y/fonts/design lint, MCP/agent wiring, cancel/retry/safe actions, icons/resources/routes.

---

## Final report (required)

1. Counts (must sum to 20): tie / d_rerank / r_gated / miss_both  
2. Soft queries where **only r_gated** helped  
3. Soft queries where **d_rerank** was better or r_gated added noise  
4. Verdict (pick one):  
   - `PREFER_R_GATED_FOR_SOFT`  
   - `KEEP_D_ONLY`  
   - `TIE_NO_CLEAR_WINNER`  
5. One paragraph: for agent-first soft traffic on this corpus, would you default search to `r_gated`?

Start: health-check API → run all 20 `/compare_rgated` → write `out/opencode_rgated_ratings.md`.
