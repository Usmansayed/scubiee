# Session data: best next tool after heatmap/map

**Evidence:** `.scubiee/sessions/*/work_session.json` + `session_store.json` (28 stores, 20 work sessions).

## What agents actually do

| Signal | Count / rate |
|--------|----------------|
| File roles: `map` | 103 |
| File roles: `focus:span` | **65** |
| File roles: `focus:neighbors` | **2** |
| Same file: `map` + `focus:span` | 27 |
| Sessions with map that also focus | **11/12 → P(focus\|map) ≈ 0.92** |
| `pinpoint` / `plate` in these sessions | rare (3 / 1) |
| Span `source` when body stored | mostly `read` (41), not hop |

**Prediction:** After a heatmap-like locate (`map` / future `trace`), the best next tool to complete context is **open a small body span** (`focus:span` today → `expand(handle)` / `fetch`), **not** graph neighbors.

Neighbors/hop are a **rare second step** when wiring is still missing after reading tops.

## Recommended ship loop

```text
trace (heatmap cards + handles)
  → fetch/expand top 1–3 handles   ← primary completer
  → hop(handle) only if still stuck ← secondary
  → edit
```

Do not invent a hop-first tool as the default after heatmap; session data says agents want **bodies of hot cards**, then edit.
