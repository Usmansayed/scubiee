# MacBook handoff — Scubiee 0.3.102 (OS-specific, realistic)

**From:** Windows pre-prod on 2026-09-21 (`docs/superpowers/plans/_preprod_0_3_101_win_sim_realistic/`)  
**Checkout / PyPI:** install **0.3.102** (`uv tool install scubiee` or `uv tool install --force .`) — keepalive/dummy-search contention fixes after the morning 0.3.101 cut.  
**You are validating:** Apple Silicon (preferred) or Intel Mac. Windows already ran Cursor Lane A + idle 120s. **Mac must prove MLX/ORT, not DirectML.**

Do **not** treat Windows numbers as Mac numbers. Unique maps are real FastEmbed + D-channel (dense + BM25 + **full** graph BFS). Few-ms is identical-query cache only.

---

## What Windows already proved (do not re-litigate)

- Install: `uv tool` / PyPI **0.3.102**, ORT DirectML 1.24.4.
- Keepalive **8s** + capped index touch (dense+BM25+graph `max_visit=64`) + skip when search/embed busy + **4s post-search cooldown** + keepalive encode **`abort_if_search`** (do not FIFO unique maps behind a dummy tick).
- Dummy locate search skipped when engine keepalive already warmed retrieve (avoids dual-MCP pile-up after host-sim `clean_slate` reconnects Cursor).
- Locate dummy `/v1/search` after `embedder_loaded` (MCP process; needs MCP reload). Bridge process does **not** arm dummy search.
- **Lane A Cursor** `--live --settle-s 40 --idle-s 120` (**PASS** `mcp-host-sim-20260921T184003Z`): unique `map_second` **64ms**, unique `post_idle_map` **153ms** (attempt 1), pack/expand **≤76ms**, `status_first` **458ms**.
- Earlier same-day Lane A: `post_idle_map` **804ms** (pre-contention-fix). Re-test on Mac with the tip that includes abort/cooldown.
- Unit: keepalive + locate-prewarm **24 passed**. ship_check PASS; warm_contract PASS (HTTP after 60s idle **281ms** on re-run).
- **Lane B Kiro** still optional / previously failed unique `map_second` ≤1s on Windows.

---

## Why Mac is a different test (OS-specific)

| Topic | Windows (done) | Mac (you) |
|-------|----------------|-----------|
| Accel | `onnxruntime-directml` / GPU **D3 ~10s** idle | Apple Silicon **MLX**; Intel **coreml/cpu**. No DirectML. ORT thread-pool still sleeps after idle ([ORT #23461](https://github.com/microsoft/onnxruntime/issues/23461)) — **keep keepalive=8s**. |
| Wheel | `onnxruntime-directml>=1.17,<1.25` | `fastembed` + `onnxruntime` + **`mlx` on arm64**. After install: `scubiee setup --repair` → profile **`mlx`**, never leftover `cpu`. |
| MCP spawn | `pythonw.exe` + `CREATE_NO_WINDOW` | plain `python` / `scubiee-mcp-bridge`. Confirm **no extra Terminal.app windows** on Cursor connect. |
| Dual Python | conda vs `uv tool` fighting `~/.scubiee` (seen on Win) | Homebrew python vs `uv tool` — pin `CTX_DAEMON_PYTHON` to the uv-tool interpreter. |
| Paths | `%USERPROFILE%\.scubiee` | `~/.scubiee`. MCP `CTX_REPO` must be an **absolute** path (Cursor still does not expand `${workspaceFolder}`). |
| SIGSEGV | less common | `TOKENIZERS_PARALLELISM=false` + GC disable in MCP (already in `mcp_locate.main`). If locate dies on first map, capture Console + `~/.scubiee/engine.log`. |
| RSS cap | 1536 MB + CPU 35% JobObject | JobObject is Windows-only. Confirm Mac RSS stays sane with MLX weights + keepalive; do not copy Win JobObject assumptions. |

Keepalive **must not** replace full D-channel on real map. Map/pack still run uncapped `graph.affinity_scores` + `bm25.score_all` + `dense.score_all` via `retrieve_D_channel_best`. If Mac cards show `retrieve_mode=capability` or `pseudo`, that is a **fail**.

---

## Install (clean, then this repo)

```bash
# Stop anything holding ~/.scubiee
scubiee engine stop 2>/dev/null || true
# Prefer one install only:
uv tool uninstall scubiee 2>/dev/null || true
pip uninstall -y scubiee 2>/dev/null || true

# From the checkout you were handed (same tip as Windows 0.3.101 + contention fixes):
cd /path/to/context-engine
git pull   # or sync the tip you were given
uv tool install --force . --refresh
scubiee --version   # expect 0.3.102
scubiee setup --repair
scubiee setup --status   # acceleration.profile == mlx on Apple Silicon
```

Confirm providers in the **uv-tool** interpreter (not Homebrew):

```bash
"$(uv tool dir)/scubiee/bin/python" -c "import onnxruntime as ort; print(ort.__version__, ort.get_available_providers())"
# Apple Silicon: MLX path is FastEmbed/MLX, not DmlExecutionProvider.
```

Init this repo (or a small enrolled repo):

```bash
scubiee init .
scubiee connect --cursor --repo "$(pwd)"
# Confirm .cursor/mcp.json: absolute CTX_REPO, CTX_EMBED_KEEPALIVE=1, CTX_EMBED_KEEPALIVE_S=8
```

Reload Cursor MCP. Wait **~40s** for dense (do not judge first map during ORT/MLX load).

---

## Realistic tests (not a pytest-only pass)

### A) Live Cursor MCP (same as a user)

After reload + 40s:

1. Unique `map` (dense code-vocab query, not a repeat). Record `elapsed_ms`, `embed_ms`, `retrieve_ms`, `retrieve_mode`, card `source` tags.
2. Second **different** unique `map`. Must be **<1s**.
3. `pack_context` lean with suggested seeds.
4. `expand_context` on a **known** `file::symbol` from the heatmap (unknown new symbols can 404 the AST graph even when search is fine).
5. If you have a session handle: `expand(handle=…)`. Ship surface does not mint handles from map/pack.
6. Wait **≥20s** (DML D3 analogue; Mac still cold-caches). Unique `map` again **<1s**.
7. Wait **≥120s** with MCP still connected. Unique `map` again **<1s**.

**Pass:** first unique after warm ≤**3s**; every later unique map and pack/expand **<1s**; `retrieve_mode=D_channel_best`; sources include bm25 **and** graph, not dense-only.

### B) CLI combinations (engine/health while Cursor MCP is up)

Windows already ran this matrix on 0.3.101. Reproduce on Mac with the **uv-tool** `scubiee` on PATH. Do **not** `scubiee map|pack|expand` while Cursor MCP locate tools are callable.

**Run (safe):**

```bash
scubiee --version
scubiee -h
scubiee preflight .
scubiee preflight . --lexical-only
scubiee setup --status          # expect acceleration.profile == mlx on Apple Silicon
scubiee resources
scubiee list
scubiee status . --json
scubiee gate .
scubiee engine status .
scubiee engine ensure .
scubiee dashboard --status
scubiee diagnose --no-tests
scubiee certify . --skip-daemon
scubiee certify . --skip-daemon --canary
scubiee migrate .
scubiee migrate --check-all
scubiee settings --show
scubiee upgrade --check         # DiffPlan only
scubiee connect --cursor --dry-run --repo "$(pwd)"
scubiee connect --all --dry-run
scubiee search "retrieve_D_channel_best FastEmbed mlx graph bm25 dense packages/pipeline/engine.py::search" .
curl -s http://127.0.0.1:8765/health
curl -s -X POST http://127.0.0.1:8765/v1/embed/keepalive
```

**Expected non-zero (not a Mac fail if same reasons):**

- `doctor` / `doctor --fix` — dirty journal of uncommitted docs; exit 1 with `replay_dirty_journal`.
- `sync-now` — auto cap 10k chunks; oversized change asks for `index --force` (do **not** force unless you intend a full reindex).
- `search --local` — `dense_embed_required` while the daemon holds the embedder.
- `scubiee test core` using **uv-tool** python — `No module named pytest`. Use the checkout interpreter: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest <core files>`.

**Do not run on a live enrolled repo:** `wipe`, `halt`, `pause`, `disconnect`, `rebuild`, `never-index`, `remove`, `unlock-tool`, `heal`, `index --force`, `mcp` stdio, `engine stop`/`run`, `upgrade` without `--check`. Do **not** run `python scripts/run_cli_combination_tests.py` without isolation — last scenario deletes the uv tool dir; even `--quick` issues `stop` / `engine stop` / `disconnect`.

After you quit Cursor / disconnect MCP, optional CLI locate:

```bash
scubiee map "retrieve_D_channel_best FastEmbed mlx embed_keepalive graph bm25 dense packages/pipeline/engine.py::search"
```

### C) Host-sim (process-real MCP, installed wheel)

From repo root, **no** `CTX_SIM_DEV=1` (that overlays checkout `packages/` into the bridge):

```bash
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export CTX_EMBED_KEEPALIVE=1
export CTX_EMBED_KEEPALIVE_S=8
unset CTX_SIM_DEV

python scripts/mcp_host_sim.py --lane a --live --settle-s 40 --idle-s 120 \
  --mcp-client cursor --project-id "$(python -c "import json; print(json.load(open('.scubiee/id.json'))['project_id'])")" \
  --out-dir docs/superpowers/plans/_preprod_0_3_101_macos_sim_realistic
```

**Pass (same budgets as Windows):**

| Phase | Budget |
|-------|--------|
| soft_ready | ≤40s (Windows: ~16s soft; Mac MLX load may be longer — still ≤40s warm) |
| map_first after settle | ≤**3s** |
| map_second unique | ≤**1s** |
| pack / expand | ≤**1s** |
| post_idle_map after **120s** | ≤**1s** (sim may retry once if a keepalive encode was mid-flight) |

Copy the `mcp-host-sim-*.md` table into your reply.

Optional Kiro (Windows previously failed ~1.22s):

```bash
python scripts/mcp_host_sim.py --lane b --live --settle-s 40 --idle-s 120 --mcp-client kiro \
  --out-dir docs/superpowers/plans/_preprod_0_3_101_macos_sim_realistic
```

### D) ship_check + warm_contract

```bash
python scripts/scubiee_mcp_ship_check.py
python scripts/warm_contract_acceptance.py --no-stop --idle-s 60
```

ship_check must exit 0. warm_contract HTTP-after-idle may be >1s on a cold machine; **MCP post_idle_map is the SLA**.

### E) Mac-only pytest (this host cannot run these)

```bash
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
python -m pytest \
  tests/mac_production_test.py \
  tests/test_coreml_mac.py \
  tests/test_mlx_backend.py \
  tests/test_cross_platform_profiles.py \
  tests/test_embed_keepalive.py \
  tests/test_locate_worker_prewarm.py \
  -q --tb=short
```

Apple Silicon: profile stays **`mlx`**. Intel: `coreml` or `cpu` is OK; say which.

---

## What to report back

Fill this (do not paste huge logs):

```text
Mac model / chip:
scubiee --version:
setup --status profile:
ORT/MLX providers:
Lane A post_idle_map_ms / retrieve_mode:
Lane A map_second_ms:
Live Cursor unique map after 120s idle_ms:
Card sources (bm25/graph/dense present?):
ship_check ok:
Kiro Lane B (if run) map_second_ms:
Failures:
```

**Fail closed if:** profile is `cpu` on Apple Silicon; unique maps after idle >1s with MCP connected (after one honest retry if a keepalive tick was mid-encode); `retrieve_mode` is pseudo/capability; host-sim used `CTX_SIM_DEV=1`.
