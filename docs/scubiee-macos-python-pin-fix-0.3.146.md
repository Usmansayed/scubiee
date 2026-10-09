# Scubiee macOS v0.3.146 — init crash root cause + Python-pin fix

_Platform: macOS 26.5.2, Apple Silicon (M5, arm64), MLX/Metal._
_Builds: crash reproduced on 0.3.145 installed under Python 3.10; fixed in 0.3.146 (`requires-python>=3.11`)._

## Summary

The intermittent `init` crash on macOS ("Writing index" → SIGSEGV/SIGBUS/SIGTRAP)
was **not an MLX bug**. It was a **Python-version / numpy-ABI mismatch**: when
scubiee was installed under **Python 3.10 (numpy 2.2.6)**, the heap was corrupted
at the faiss vector-write step. Under **Python 3.12 (numpy 2.5.3)** the exact same
MLX + faiss code is clean.

The fix is to **pin the install to Python 3.11+** so the toolchain never lands on
the bad interpreter. **MLX stays the embedder — nothing in the embedding or index
architecture changed.**

## Root cause

One variable isolated everything else held constant (MLX 0.32.3, faiss 1.15.1,
same source):

| Interpreter | numpy | 20× first-init MLX | Result |
|---|---|---|---|
| Python 3.10.21 | 2.2.6 | 8/8 crash | heap corruption at faiss upsert |
| Python 3.12.14 | 2.5.3 | 20/20 clean | no segfault |

Crash signature was latent heap corruption surfacing at varying sites
(`gc_collect_main`, `_abc_subclasscheck`, numpy `array_zeros` / QR `np.linalg.qr`).
These are symptoms of memory already corrupted earlier, not of the crashing call
itself — consistent with a numpy C-ABI mismatch on the 3.10 wheel set, not an MLX
or faiss defect.

Rejected alternatives (all still crashed under Python 3.10, so none was the real
fix): `quiesce_mlx` synchronize + clear_cache; owned numpy copy
(`np.array(..., copy=True)`); removing per-batch `clear_cache`; subprocess
isolation. The defensive `quiesce_mlx` + owned-copy changes are kept as harmless
hygiene, but they are not what fixes the crash.

## Fix

- `pyproject.toml`: `requires-python = ">=3.11"`; version → `0.3.146`; drop the
  `Programming Language :: Python :: 3.10` classifier. `uv tool install` and pip
  now refuse Python 3.10 and select 3.11+.
- `npm/scripts/install-python.cjs`: interpreter probe floor `(3, 10)` → `(3, 11)`;
  "Python 3.10+ not found" → "3.11+".
- `npm/bin/scubiee.cjs`, `npm/bin/ctx.cjs`, `npm/README.md`: "Python 3.10+" →
  "3.11+". `npm/package.json` version → `0.3.146`.

## Verification (0.3.146, Python 3.12.14 / numpy 2.5.3)

- Wheel metadata: `Requires-Python: >=3.11`, `Version: 0.3.146`.
- 20× first-ever MLX init on the tiny test repo (`/tmp/scubiee_testrepo`,
  main.py + utils.py, 7 chunks): **PASS=20 CRASH=0**, MLX confirmed on 18/20
  (first 2 served from a warm cache before the embed log line).
- Both orderings, 4× each: **init-first/connect-later 4/4 ok**,
  **connect-first/init-later 4/4 ok**, all `ok=true chunks=7`.
- No new segfaults; retrieval numerically unchanged from prior numpy
  (embedder cosines identical to pre-fix runs).

## Operator note

Existing users still on a Python-3.10 install should reinstall so the toolchain
re-selects 3.11+ (e.g. `uv tool install --force --python 3.12 --reinstall scubiee`).
A 3.10 install is the trigger for the crash; the version pin prevents new installs
from landing there.
