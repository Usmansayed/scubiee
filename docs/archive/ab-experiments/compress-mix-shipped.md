# Locked production compression

**Locked:** `CTX_COMPRESS=mix` · `CTX_COMPRESS_MAX_CHARS=512`  
**Opt out:** `CTX_COMPRESS=off` (legacy char truncate)

Do not ship size-ladder 300/350 as default — keep the normal 512 cap (speed is already fine @ seq=128/512).

## Which technique wins consistently?

| Technique | Role | Soft / overall |
|-----------|------|----------------|
| **mix** | Card-labeled identity + importance/rare body fill | **Winner** — best soft R@5/MRR across bakeoffs |
| budget_c | Fixed % + rare-idents | Strong hard; loses soft to mix |
| card | Meta/intent only | Weaker soft than mix |
| importance | Score-fill only | Trailed mix on soft expanded |
| skeleton | AST stubs | Consistently worst soft |
| baseline / legacy truncate | Dumb cut @512/1200 | Beat by mix (+0.10 soft R@5 vs default512) |

**Ship mix.** Size/allocation experiments are research; production stays mix@512.

## Evidence (frontend-mcp, FAISS+TQ, R_plan)

- Soft 52: mix ahead of card/importance/skeleton  
- vs legacy1200 / default512: mix wins soft R@5  
- Budget A/B/C @450: mix > budget_c > … > skeleton  
- Difficult 139-q macro: mix@450 competitive; smaller budgets optional, **not** required  

## Env

```text
CTX_COMPRESS=mix                 # default
CTX_COMPRESS_MAX_CHARS=512       # default
CTX_EMBED_SEQ=128                # --fast default (512 ≡ quality for mix)
```
