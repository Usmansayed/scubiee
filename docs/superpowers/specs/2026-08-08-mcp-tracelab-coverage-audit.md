# MCP vs TraceLab sessions — coverage & mcp-builder audit

**Date:** 2026-08-08  
**Server:** `context_engine_mcp` (`pipeline.mcp_locate`)  
**Skill:** anthropics `mcp-builder`

## Does it solve all session issues?

**No — not “all,” but it covers the main retrieval-append failure modes that drive ~50%.**

| TraceLab issue | Covered? | How |
|---|---|---|
| Cold-start ls/find/rg cascades (WF1) | **Yes** | `map` one hybrid shot |
| Follow-up re-Grep / re-Read (WF2/WF6) | **Yes** | `recall` + `already_in_session` stubs |
| Repair widen-search (WF3) | **Partial** | `focus` in hot zone; agent must choose it over Bash |
| Search-heavy loops (WF4) | **Yes if agent complies** | One `map`; rule forbids Grep |
| Edit-heavy re-reads (WF5) | **Yes** | `workspace(pin)` + `expand` |
| Duplicate signature re-sends (~21% median) | **Yes** | content-hash session store |
| Near-duplicate reads | **Yes** | path/hash stubs + focus(path) |
| Large unused dumps | **Mostly** | savings excerpts + expand-on-demand |
| Shell used for verify/tests | **Out of scope** | Keep native Bash/pytest |
| Agents ignoring MCP / still Grepping | **Not solvable in MCP alone** | Needs client rules + eval harness |
| Measured 50% on live A/B | **Not yet** | Phase C harness still TODO |

**Bottom line:** The MCP is the right *system* for the research findings. Token savings are **conditional on agents using it** instead of Grep/Read dumps. Design + rules are in place; proof = A/B.

## mcp-builder checklist

| Practice | Status |
|---|---|
| Clear server name `context_engine_mcp` | Done |
| Workflow tools (not raw API dump) | Done — intentional for locate UX |
| Flat tool args (`map(query=…)`) | Done |
| Pydantic validation | Done |
| Tool annotations (readOnly/destructive/…) | Done |
| Actionable errors + hints | Done |
| Concise descriptions matching behavior | Done |
| json \| markdown response_format | Done |
| Pagination on recall | Done (limit/offset/has_more) |
| Savings defaults (0 = auto) | **Fixed** (was overriding with rich budgets) |
| Status playbooks for WF1–WF6 | Done |
| Eval suite (10 QA pairs) | TODO (Phase 4 of mcp-builder) |

## Agent contract (required for 50%)

```
map → cold start
recall → every follow-up first
focus → new need in hot zone
expand → edit-time body only
workspace pin/show/clear → session control
Bash/Grep → verify only, never discovery
```
