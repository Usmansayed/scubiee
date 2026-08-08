# Vendored / bundled deps

## Claude Context
**Not vendored.** Sync ideas live in `packages/pipeline/` (merkle, sync_loop, incremental).

## Graphify
**Bundled** at `packages/graphify/` (slim extract/build/export/serve + extractors).
Installed automatically with `pip install -e .` — no separate `pip install graphify`.

Upstream reference copy may still exist under `vendor/graphify/` for diffs; the
runtime package is `packages/graphify`.
