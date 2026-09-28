# Blind-20 simple Phase2 (must-file recall)

Total Phase1 wall: **197.5s**

## Mean must-file recall

| Arm | Mean recall | Thin packs (n<=1) |
|-----|-------------|-------------------|
| map top5 (baseline) | 0.833 | n/a |
| composite_v1 | 0.662 | 17/20 |
| polytrace | 0.662 | 17/20 |
| ultimate | 0.662 | 17/20 |

**Pack winner (must-file):** composite_v1

## Notes

- Warm-engine map after first query was ~1s; first map paid engine/sync (~128s).
- Packs often n=1 because map seeds had empty symbol → resolve landed on a single seed node (__init__ / file-level).
- Map top5 files often already contain the right modules; pack heat expansion was weak without a real symbol seed.

## Per case

- r01 map=1.0 composite_v1=0.25 polytrace=0.25 ultimate=0.25 seed=packages/pipeline/searcher.py
- r02 map=1.0 composite_v1=1.0 polytrace=1.0 ultimate=1.0 seed=packages/pipeline/capability.py
- r03 map=0.5 composite_v1=0.5 polytrace=0.5 ultimate=0.5 seed=packages/conductor/graphify_retriever.py
- r04 map=1.0 composite_v1=1.0 polytrace=1.0 ultimate=1.0 seed=packages/pipeline/repo_lifecycle.py
- r05 map=0.667 composite_v1=0.333 polytrace=0.333 ultimate=0.333 seed=packages/pipeline/__main__.py
- r06 map=1.0 composite_v1=1.0 polytrace=1.0 ultimate=1.0 seed=packages/pipeline/dashboard_server.py
- r07 map=1.0 composite_v1=1.0 polytrace=1.0 ultimate=1.0 seed=packages/pipeline/wipe.py
- r08 map=0.5 composite_v1=0.5 polytrace=0.5 ultimate=0.5 seed=packages/pipeline/__main__.py
- r09 map=0.667 composite_v1=0.0 polytrace=0.0 ultimate=0.0 seed=packages/pipeline/__init__.py
- r10 map=1.0 composite_v1=0.5 polytrace=0.5 ultimate=0.5 seed=packages/pipeline/searcher.py
- r11 map=1.0 composite_v1=1.0 polytrace=1.0 ultimate=1.0 seed=packages/pipeline/indexer.py
- r12 map=1.0 composite_v1=0.5 polytrace=0.5 ultimate=0.5 seed=packages/pipeline/memory_budget.py
- r13 map=1.0 composite_v1=1.0 polytrace=1.0 ultimate=1.0 seed=packages/pipeline/rules_installer.py
- r14 map=0.667 composite_v1=0.333 polytrace=0.333 ultimate=0.333 seed=packages/pipeline/locate_cli.py
- r15 map=1.0 composite_v1=1.0 polytrace=1.0 ultimate=1.0 seed=packages/pipeline/freshness.py
- r16 map=0.5 composite_v1=0.5 polytrace=0.5 ultimate=0.5 seed=packages/pipeline/__main__.py
- r17 map=1.0 composite_v1=1.0 polytrace=1.0 ultimate=1.0 seed=packages/pipeline/mcp_permissions.py
- r18 map=1.0 composite_v1=1.0 polytrace=1.0 ultimate=1.0 seed=packages/trace_lab/polytrace.py
- r19 map=0.5 composite_v1=0.5 polytrace=0.5 ultimate=0.5 seed=packages/pipeline/engine.py
- r20 map=0.667 composite_v1=0.333 polytrace=0.333 ultimate=0.333 seed=packages/pipeline/chunk_merkle.py
