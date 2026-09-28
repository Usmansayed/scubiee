# A/B trial 3: Scubiee vs native (warm engine / watchdog) + context audit

**Task:** How does the warm engine on :8765 get started, kept alive, and used for search?

**Agents:** [Scubiee](f4fe1685-943f-462c-8b8b-3be5b588b45f) vs [Native](cc833a42-5695-4808-b847-4324d57b10c9)

## Efficiency

| | Scubiee | Native |
|---|---|---|
| tool_calls | 29 | 30 |
| chars ingested (claimed) | ~118k | ~185k (source spans ~55k) |
| fairer source-read estimate | ~59k spans + ~55k map/pack JSON | ~55k spans + broad Grep noise |
| files span-read | ~7 core | ~10 core |

Raw totals favor Scubiee less than prior trials once map/pack JSON is counted; native burned a large `:8765` Grep.

## Context audit (judge verified)

| Claim | Scubiee | Native | Code check |
|---|---|---|---|
| Default `127.0.0.1:8765` (`DEFAULT_URL` / `DEFAULT_PORT`) | yes | yes | **PASS** `client.py:29`, `server.py:20` |
| `start_daemon` → `engine run` + sets `CTX_ENGINE_URL` | yes | yes | **PASS** `daemon.py:270+` |
| Watchdog polls `/health`, 2 fails → `force_restart_daemon` | yes | yes | **PASS** `watchdog.py` |
| Idle unload ≠ watchdog (`apply_idle_policy`) | partial | yes (explicit) | **PASS** native clearer; Scubiee under-emphasized |
| `search_repo` only uses server if env/`server_url` set (no silent DEFAULT_URL) | **yes (called out)** | yes (inventory) | **PASS** `searcher.py:132-134` — important nuance both got |
| `EngineClient` defaults to `:8765` | yes | yes | **PASS** |
| `POST /v1/search` | yes | yes | **PASS** `server.py:340` |
| `WarmSearchEngine.search` / `RuntimeManager` | weak | yes | Native deeper on in-process path |
| CLI `engine start` → daemon + watchdog | yes | yes | **PASS** |

### Context quality score (0–5)

| Dimension | Scubiee | Native |
|---|---|---|
| Correctness of core path | 5 | 5 |
| Critical nuance (`search_repo` vs `EngineClient` URL) | 5 | 4 |
| Completeness (idle vs watchdog split) | 3 | 5 |
| Hallucinations found | 0 | 0 |
| Signal density (useful facts / chars) | higher if pack JSON excluded | lower (Grep dump) |

**Verdict on context:** Both inventories are accurate against the repo. Native is slightly more complete (idle policy + `WarmSearchEngine`/`ce_service`). Scubiee correctly stressed the `search_repo` vs `EngineClient` default-URL trap. No invented APIs.

## Across 3 trials (tokens only)

| Trial | Scubiee chars | Native chars | Winner |
|---|---|---|---|
| 1 connect | ~46k | ~92k | Scubiee ~2× |
| 2 session | ~28k | ~38k | Scubiee ~1.4× |
| 3 engine | ~118k* | ~185k* | Scubiee on raw; closer on span-only |

\*Trial 3 includes locate JSON / Grep noise — compare context quality above, not raw chars alone.
