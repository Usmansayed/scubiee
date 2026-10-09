# Scubiee 0.3.146 — changelog (changes since last pull)

_Platform focus: macOS 26.5.2, Apple Silicon (M5, arm64), MLX/Metal._
_Baseline: `upstream/main` at `5399d8f`. This release: `85dc9c1` → tag `v0.3.146`._

This release is one focused fix on top of the connect→init reliability work that
already shipped in `5399d8f`. MLX remains the only embedder on Apple Silicon — no
backend split, no FastEmbed swap.

## The one change: pin the Python install floor to 3.11

**Why.** The intermittent `init` crash on macOS ("Writing index" →
SIGSEGV/SIGBUS/SIGTRAP) was traced to a **Python-version / numpy-ABI mismatch**,
not an MLX defect. Holding MLX 0.32.3 + faiss 1.15.1 + the same source constant
and varying only the interpreter:

| Interpreter | numpy | 20× MLX first-init | Result |
|---|---|---|---|
| Python 3.10.21 | 2.2.6 | 8/8 crash | heap corruption at faiss upsert |
| Python 3.12.14 | 2.5.3 | 20/20 clean | no segfault |

The faulting site varied every run (`gc_collect_main`, `_abc_subclasscheck`,
numpy `array_zeros`, QR `np.linalg.qr`) — the signature of memory already
corrupted earlier, consistent with a numpy C-ABI mismatch on the 3.10 wheel set.

**Fix.** Refuse Python 3.10 so the toolchain always lands on 3.11+.

## Files changed since `5399d8f`

- **`pyproject.toml`** — `requires-python = ">=3.11"`; version `0.3.145 → 0.3.146`;
  removed the `Programming Language :: Python :: 3.10` classifier. `uv tool
  install` / pip now select 3.11+.
- **`npm/scripts/install-python.cjs`** — interpreter-probe floor
  `sys.version_info >= (3, 10)` → `(3, 11)`; "Python 3.10+ not found" → "3.11+".
- **`npm/package.json`** — version `0.3.145 → 0.3.146`.
- **`npm/bin/scubiee.cjs`, `npm/bin/ctx.cjs`, `npm/README.md`** — "Python 3.10+"
  requirement strings → "3.11+".
- **`packages/pipeline/mlx_mac.py`** — kept as defensive hygiene (not the fix):
  - `quiesce_mlx()` is now a pure flush (`mx.synchronize` + per-thread stream
    sync). Removed the `clear_cache()` / `set_cache_limit(0)` residency-set churn,
    which is itself a documented Apple-Silicon Metal instability trigger.
  - `embed_ids` / `embed_ids_compiled` return an **owned** numpy copy
    (`np.array(np.asarray(normed, dtype=np.float32), copy=True)`) so the result is
    detached from MLX's unified-memory buffer before faiss/numpy runs.
  - Removed per-batch `clear_cache()`; RAM is bounded via batch size + cache env,
    not destroy-bursts.
- **`docs/scubiee-macos-python-pin-fix-0.3.146.md`** — root-cause + fix writeup.
- **`docs/scubiee-macos-changelog-0.3.146.md`** — this file.

### Removed
- `docs/scubiee-macos-mlx-index-crash-escalation.md` — a stale intermediate
  "escalate to owner" note from before the Python-pin root cause was found. Its
  conclusion ("quiesce can't fix it, owner decision needed") is superseded by the
  Python-pin fix, so it was dropped to avoid a contradictory record.

## What did NOT change

- MLX is still the embedder and the index backend on Apple Silicon.
  `CTX_INDEX_EMBED_BACKEND` remains an opt-in escape hatch only.
- No change to retrieval math — embedder cosines are numerically identical to the
  pre-fix numpy.
- The connect-once / init-auto-applies lifecycle fixes (store-hold deadlock,
  delete-prune) from `5399d8f` are unchanged.

## Verification (0.3.146 wheel, Python 3.12.14 / numpy 2.5.3)

- Wheel metadata: `Requires-Python: >=3.11`, `Version: 0.3.146`.
- 20× first-ever MLX init on the tiny test repo (main.py + utils.py, 7 chunks):
  **PASS 20 / CRASH 0**, MLX confirmed on 18/20 (first 2 served warm before the
  embed log line).
- Both orderings, 4× each: init-first/connect-later **4/4**,
  connect-first/init-later **4/4**, all `ok=true chunks=7`.
- No new segfaults.

## Upgrade note

Users still on a Python-3.10 install should reinstall so the toolchain
re-selects 3.11+:

```bash
uv tool install --force --python 3.12 --reinstall scubiee
```
