# Blind map→pack phase 2 — ground truth compare

Ground truth collected **after** the blind run (independent symbol/path search). Frozen map/pack not re-run.

## Summary

| Metric | Value |
|--------|-------|
| Seed in must-files | 80% (16/20) |
| Mean **map** must-file recall | 77.50% |
| Mean **pack** must-file recall | 55.00% |
| Mean **union** must-file recall | 77.50% |
| Mean **pack** must-symbol recall | 33.33% |
| Perfect union file coverage | 14/20 |
| Thin packs (n_pack < 2) | 13/20 |

## Per task

| ID | Seed OK | Map file | Pack file | Union file | Pack sym | Missing files | Missing syms |
|----|---------|----------|-----------|------------|----------|---------------|--------------|
| `t01` | True | 1.00 | 0.67 | 1.00 | 0.67 | — | put_span |
| `t02` | True | 1.00 | 0.50 | 1.00 | 0.00 | — | install_tool,write_project_tool_surface,write_project_gate_rules,apply_permissions_to_repo_tool_surface |
| `t03` | True | 0.50 | 0.50 | 0.50 | 0.00 | mcp_locate.py | map_context_impl,pack_context_impl |
| `t04` | True | 1.00 | 1.00 | 1.00 | 0.00 | — | apply_rank_composite |
| `t05` | True | 1.00 | 0.50 | 1.00 | 0.00 | — | apply_embed_keep_drop |
| `t06` | True | 1.00 | 0.33 | 1.00 | 0.00 | — | run_semantic_tracer_fuse |
| `t07` | False | 0.00 | 0.00 | 0.00 | 0.00 | __main__.py,locate_cli.py | cmd_pack,cli_pack |
| `t08` | True | 0.50 | 0.50 | 0.50 | 1.00 | engine.py | — |
| `t09` | True | 1.00 | 0.50 | 1.00 | 1.00 | — | — |
| `t10` | True | 1.00 | 1.00 | 1.00 | 0.00 | — | write_project_gate_rules |
| `t11` | True | 1.00 | 1.00 | 1.00 | 0.00 | — | map_context_impl,pack_context_impl |
| `t12` | False | 0.00 | 0.00 | 0.00 | 0.00 | mcp_locate.py | expand_context_impl |
| `t13` | False | 1.00 | 0.00 | 1.00 | 0.00 | — | apply_permissions_to_repo_tool_surface |
| `t14` | True | 1.00 | 1.00 | 1.00 | 1.00 | — | — |
| `t15` | True | 1.00 | 1.00 | 1.00 | 1.00 | — | — |
| `t16` | True | 1.00 | 0.50 | 1.00 | 0.00 | — | put_span |
| `t17` | False | 0.00 | 0.00 | 0.00 | 1.00 | mcp_locate.py,gate_cli.py | — |
| `t18` | True | 0.50 | 0.50 | 0.50 | 0.00 | semantic_teleport.py | apply_strict_embed_teleport |
| `t19` | True | 1.00 | 1.00 | 1.00 | 1.00 | — | — |
| `t20` | True | 1.00 | 0.50 | 1.00 | 0.00 | — | register_hybrid_arms |

## Findings (factual)

1. **Map file recall is strong** when must-files are named in the enrich query — map often surfaces the right *files*.
2. **Lean pack is often thin** (many n_pack=1) and frequently misses the *symbols* that matter (`install_tool`, `pack_context_impl`, `apply_embed_keep_drop`, …).
3. **Wrong/weak seeds** hurt pack: e.g. t07 landed on `policy/faction.py` instead of `__main__.py`/`locate_cli.py`; t17 on `pipeline/__init__.py`.
4. **Suggested seeds often omit symbol** (file-only), so pack expands from a weak entry.
5. **Tests/docs** appear in map cards (noise) — phase-1 cards included test/docs ranks for some tasks.

Artifacts: ground truth JSON + this compare. No pack re-run.
