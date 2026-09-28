# Design: pack_context — few calls, fat relevant context

**Date:** 2026-09-04  
**Status:** approved — implementing

## Insight
Fewer API calls with more relevant context often beats many thin calls (tool/decision overhead). Goal: full useful context in the fewest calls while saving total tokens vs guide→many Reads.

## Default tool
`pack_context` = heatmap + auto-collect hot bodies in one response.

## Non-goals
- Delete map_context/expand/collect (experiment arms)
- Dump entire repo
- Force agents to only use pack (encourage as default for understand/fix with seed)
