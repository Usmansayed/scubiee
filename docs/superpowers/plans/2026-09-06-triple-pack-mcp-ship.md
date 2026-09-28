# Ship: triple pack MCP tools (0.3.22)

## Tools

| MCP tool | Engine | Notes |
|----------|--------|-------|
| `pack_context` | `composite_v1` | Default ladder pack (unchanged name) |
| `pack_poly_embed` | `poly_embed` | Poly structure + real CodeRank embeds |
| `pack_semantic` | `semantic_tracer_fuse` | Safe semantic heat + real embeds |

Ladder: `map` → one of the three packs (prefer `seed_symbol`) → `expand_context`.

## Install

```text
uv tool install --force --reinstall <repo>
# verified: scubiee 0.3.22 with pack_context | pack_poly_embed | pack_semantic
```

Reload Scubiee MCP in Cursor after install.

## Smoke

```text
python scripts/smoke_triple_pack.py
# put_span seed → all three packs ok, n_pack ≥ 3
```

First poly/semantic pack on a repo builds `.scubiee/cache/pack_embed_coderank.jsonl` (one-time).
