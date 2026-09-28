# INVALID — prior top-5 venture bakeoff (do not cite)

**Date invalidated:** 2026-09-06

## Why invalid

1. **Product FAISS proposal was dead.** `_product_faiss_files` called `search_repo(..., mode="semantic")` — invalid kwarg. Exception swallowed → **always 0 hits**. Architecture A1 never used the vector DB.
2. No preflight gate: bakeoff could “succeed” without proving DML / real EmbedField / FAISS.
3. Accidental fixture `index_repo` briefly overwrote the shared product collection (restored: **5779** chunks on main repo).

Superseded by a re-run that passes `scripts/venture_preflight.py` + fixed FAISS helper + `require_real_embeds=True`. See `2026-09-06-top5-semantic-venture.md` after that re-run.
