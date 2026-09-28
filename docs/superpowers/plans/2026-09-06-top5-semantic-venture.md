# Top-5 semantic tracer venture bakeoff

Boards: verify_hard.json, verify_ood_v2.json, verify_prod.json, verify_ood_v10_realistic.json · cases 86 · **seed-hard 29** · elapsed 1187.52s

**Stack gate:** PASSED — `real:fastembed` dim=768 on DML; product FAISS 8 hits; `require_real_embeds=True`.  
Prior un-gated report is **INVALID** (`2026-09-06-top5-semantic-venture.INVALID.md`): FAISS helper used a bad kwarg and always returned 0 hits.

**Winner on seed-hard (Δ must-recall vs composite):** `venture_multiview`

**Caveat:** Δ must numbers match the prior (broken-FAISS) run closely — FAISS hits often map to files outside the fixture AST corpus, so proposal still leans on EmbedField affinities. Stack is live; FAISS→fixture-node join still needs work.

Implements architectures from `SCUBIEE_TOP5_SEMANTIC_TRACER_EXPERIMENTS.md` (A1 propose+verify, A2 frontier, A3 multiview, A4 trace-state, A5 learned proxy, A6 combo).

## Seed-hard summary (primary)

| Arm | Δ must | Must | F1 | Prec | Must@10 | Mean hot | Acc |
|-----|--------|------|----|------|---------|----------|-----|
| `venture_multiview` | +0.0797 | 0.6810 | 0.6937 | 0.7625 | 0.7350 | 4.9 | 0.0345 |
| `venture_trace_state` | +0.0575 | 0.6588 | 0.6236 | 0.6479 | 0.7128 | 5.7 | 0.0345 |
| `venture_propose_path1` | +0.0201 | 0.6214 | 0.6794 | 0.8557 | 0.6755 | 4.1 | 0.0000 |
| `venture_propose_plus_frontier` | +0.0201 | 0.6214 | 0.6753 | 0.8443 | 0.6686 | 4.2 | 0.0000 |
| `venture_propose_verify` | +0.0201 | 0.6214 | 0.6746 | 0.8436 | 0.6755 | 4.2 | 0.0000 |
| `venture_learned_heat` | +0.0115 | 0.6128 | 0.6702 | 0.8557 | 0.6668 | 4.1 | 0.0000 |
| `poly_embed` | +0.0069 | 0.6082 | 0.6927 | 0.8947 | 0.7179 | 3.9 | 0.1034 |
| `venture_semantic_frontier` | -0.0000 | 0.6013 | 0.6756 | 0.8920 | 0.6484 | 3.9 | 0.0000 |
| `semantic_tracer_fuse` | -0.0000 | 0.6013 | 0.6756 | 0.8920 | 0.6484 | 3.9 | 0.0000 |
| `composite_v1` | -0.0000 | 0.6013 | 0.6748 | 0.8913 | 0.6553 | 3.9 | 0.0000 |
| `hyb_fuse_demote_noise_plus` | -0.0201 | 0.5812 | 0.6608 | 0.8733 | 0.6484 | 3.9 | 0.0000 |

## All cases summary

| Arm | Must | F1 | Prec | Acc |
|-----|------|----|------|-----|
| `venture_multiview` | 0.8924 | 0.7755 | 0.7373 | 0.4651 |
| `venture_trace_state` | 0.8849 | 0.7310 | 0.6677 | 0.4651 |
| `venture_propose_path1` | 0.8723 | 0.7881 | 0.7980 | 0.5465 |
| `venture_propose_plus_frontier` | 0.8723 | 0.7842 | 0.7893 | 0.5349 |
| `venture_propose_verify` | 0.8723 | 0.7825 | 0.7872 | 0.5349 |
| `venture_learned_heat` | 0.8694 | 0.7840 | 0.7957 | 0.5349 |
| `venture_semantic_frontier` | 0.8656 | 0.7911 | 0.8158 | 0.5581 |
| `semantic_tracer_fuse` | 0.8656 | 0.7911 | 0.8158 | 0.5581 |
| `composite_v1` | 0.8656 | 0.7893 | 0.8137 | 0.5581 |
| `hyb_fuse_demote_noise_plus` | 0.8491 | 0.7793 | 0.8072 | 0.5465 |
| `poly_embed` | 0.8315 | 0.7852 | 0.8234 | 0.4767 |

## Seed-hard per case (recovery)

### `verify_hard.json:h05` miss=['TOKEN_TTL']
- `composite_v1`: must=0.83 recovered=[] still_missing=['TOKEN_TTL'] hot=5
- `venture_multiview`: must=0.83 recovered=[] still_missing=['TOKEN_TTL'] hot=5
- `venture_propose_verify`: must=0.83 recovered=[] still_missing=['TOKEN_TTL'] hot=5
- `venture_propose_plus_frontier`: must=0.83 recovered=[] still_missing=['TOKEN_TTL'] hot=5

### `verify_hard.json:h06` miss=['log']
- `composite_v1`: must=0.75 recovered=[] still_missing=['log'] hot=3
- `venture_multiview`: must=0.75 recovered=[] still_missing=['log'] hot=3
- `venture_propose_verify`: must=0.75 recovered=[] still_missing=['log'] hot=3
- `venture_propose_plus_frontier`: must=0.75 recovered=[] still_missing=['log'] hot=3

### `verify_hard.json:h08` miss=['connect', 'TOKEN_TTL', 'User.lookup', 'UserRepository.resolve', 'JwtService.verify']
- `composite_v1`: must=0.17 recovered=[] still_missing=['connect', 'TOKEN_TTL', 'User.lookup', 'UserRepository.resolve', 'JwtService.verify'] hot=1
- `venture_multiview`: must=0.33 recovered=['JwtService.verify'] still_missing=['connect', 'TOKEN_TTL', 'User.lookup', 'UserRepository.resolve'] hot=2
- `venture_propose_verify`: must=0.17 recovered=[] still_missing=['connect', 'TOKEN_TTL', 'User.lookup', 'UserRepository.resolve', 'JwtService.verify'] hot=1
- `venture_propose_plus_frontier`: must=0.17 recovered=[] still_missing=['connect', 'TOKEN_TTL', 'User.lookup', 'UserRepository.resolve', 'JwtService.verify'] hot=1

### `verify_hard.json:h16` miss=['track', 'log']
- `composite_v1`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=4
- `venture_multiview`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=4
- `venture_propose_verify`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=4
- `venture_propose_plus_frontier`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=4

### `verify_hard.json:h17` miss=['track', 'log']
- `composite_v1`: must=0.60 recovered=[] still_missing=['track', 'log'] hot=4
- `venture_multiview`: must=0.60 recovered=[] still_missing=['track', 'log'] hot=4
- `venture_propose_verify`: must=0.60 recovered=[] still_missing=['track', 'log'] hot=4
- `venture_propose_plus_frontier`: must=0.60 recovered=[] still_missing=['track', 'log'] hot=4

### `verify_hard.json:h19` miss=['track', 'log']
- `composite_v1`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=4
- `venture_multiview`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=4
- `venture_propose_verify`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=4
- `venture_propose_plus_frontier`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=4

### `verify_hard.json:h21` miss=['track', 'log']
- `composite_v1`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=4
- `venture_multiview`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=5
- `venture_propose_verify`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=5
- `venture_propose_plus_frontier`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=5

### `verify_hard.json:h22` miss=['log']
- `composite_v1`: must=0.75 recovered=[] still_missing=['log'] hot=4
- `venture_multiview`: must=0.75 recovered=[] still_missing=['log'] hot=5
- `venture_propose_verify`: must=0.75 recovered=[] still_missing=['log'] hot=4
- `venture_propose_plus_frontier`: must=0.75 recovered=[] still_missing=['log'] hot=4

### `verify_hard.json:h23` miss=['track', 'log']
- `composite_v1`: must=0.33 recovered=[] still_missing=['track', 'log'] hot=1
- `venture_multiview`: must=0.33 recovered=[] still_missing=['track', 'log'] hot=2
- `venture_propose_verify`: must=0.33 recovered=[] still_missing=['track', 'log'] hot=1
- `venture_propose_plus_frontier`: must=0.33 recovered=[] still_missing=['track', 'log'] hot=1

### `verify_hard.json:h24` miss=['track', 'log']
- `composite_v1`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=4
- `venture_multiview`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=5
- `venture_propose_verify`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=5
- `venture_propose_plus_frontier`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=5

### `verify_hard.json:h25` miss=['track', 'log']
- `composite_v1`: must=0.60 recovered=[] still_missing=['track', 'log'] hot=4
- `venture_multiview`: must=0.60 recovered=[] still_missing=['track', 'log'] hot=5
- `venture_propose_verify`: must=0.60 recovered=[] still_missing=['track', 'log'] hot=5
- `venture_propose_plus_frontier`: must=0.60 recovered=[] still_missing=['track', 'log'] hot=5

### `verify_hard.json:h27` miss=['track', 'log']
- `composite_v1`: must=0.50 recovered=[] still_missing=['track', 'log'] hot=2
- `venture_multiview`: must=0.50 recovered=[] still_missing=['track', 'log'] hot=3
- `venture_propose_verify`: must=0.50 recovered=[] still_missing=['track', 'log'] hot=2
- `venture_propose_plus_frontier`: must=0.50 recovered=[] still_missing=['track', 'log'] hot=2

### `verify_hard.json:h29` miss=['TOKEN_TTL']
- `composite_v1`: must=0.67 recovered=[] still_missing=['TOKEN_TTL'] hot=11
- `venture_multiview`: must=0.67 recovered=[] still_missing=['TOKEN_TTL'] hot=11
- `venture_propose_verify`: must=0.67 recovered=[] still_missing=['TOKEN_TTL'] hot=11
- `venture_propose_plus_frontier`: must=0.67 recovered=[] still_missing=['TOKEN_TTL'] hot=10

### `verify_hard.json:h31` miss=['track', 'log']
- `composite_v1`: must=0.71 recovered=[] still_missing=['track', 'log'] hot=6
- `venture_multiview`: must=0.71 recovered=[] still_missing=['track', 'log'] hot=6
- `venture_propose_verify`: must=0.71 recovered=[] still_missing=['track', 'log'] hot=6
- `venture_propose_plus_frontier`: must=0.71 recovered=[] still_missing=['track', 'log'] hot=6

### `verify_hard.json:h32` miss=['TOKEN_TTL', 'ingest']
- `composite_v1`: must=0.33 recovered=[] still_missing=['TOKEN_TTL', 'ingest'] hot=1
- `venture_multiview`: must=0.67 recovered=['TOKEN_TTL'] still_missing=['ingest'] hot=3
- `venture_propose_verify`: must=0.33 recovered=[] still_missing=['TOKEN_TTL', 'ingest'] hot=1
- `venture_propose_plus_frontier`: must=0.33 recovered=[] still_missing=['TOKEN_TTL', 'ingest'] hot=1

### `verify_hard.json:h35` miss=['query']
- `composite_v1`: must=0.75 recovered=[] still_missing=['query'] hot=3
- `venture_multiview`: must=0.75 recovered=[] still_missing=['query'] hot=5
- `venture_propose_verify`: must=0.75 recovered=[] still_missing=['query'] hot=3
- `venture_propose_plus_frontier`: must=0.75 recovered=[] still_missing=['query'] hot=3

### `verify_hard.json:h37` miss=['log']
- `composite_v1`: must=0.89 recovered=[] still_missing=['log'] hot=8
- `venture_multiview`: must=0.89 recovered=[] still_missing=['log'] hot=8
- `venture_propose_verify`: must=0.89 recovered=[] still_missing=['log'] hot=8
- `venture_propose_plus_frontier`: must=0.89 recovered=[] still_missing=['log'] hot=8

### `verify_hard.json:h38` miss=['log']
- `composite_v1`: must=0.80 recovered=[] still_missing=['log'] hot=8
- `venture_multiview`: must=0.80 recovered=[] still_missing=['log'] hot=8
- `venture_propose_verify`: must=0.80 recovered=[] still_missing=['log'] hot=8
- `venture_propose_plus_frontier`: must=0.80 recovered=[] still_missing=['log'] hot=8

### `verify_hard.json:h39` miss=['store']
- `composite_v1`: must=0.67 recovered=[] still_missing=['store'] hot=2
- `venture_multiview`: must=0.67 recovered=[] still_missing=['store'] hot=3
- `venture_propose_verify`: must=0.67 recovered=[] still_missing=['store'] hot=3
- `venture_propose_plus_frontier`: must=0.67 recovered=[] still_missing=['store'] hot=3

### `verify_hard.json:h43` miss=['receive']
- `composite_v1`: must=0.67 recovered=[] still_missing=['receive'] hot=2
- `venture_multiview`: must=0.67 recovered=[] still_missing=['receive'] hot=4
- `venture_propose_verify`: must=0.67 recovered=[] still_missing=['receive'] hot=4
- `venture_propose_plus_frontier`: must=0.67 recovered=[] still_missing=['receive'] hot=4

### `verify_hard.json:h44` miss=['schedule']
- `composite_v1`: must=0.67 recovered=[] still_missing=['schedule'] hot=2
- `venture_multiview`: must=0.67 recovered=[] still_missing=['schedule'] hot=3
- `venture_propose_verify`: must=0.67 recovered=[] still_missing=['schedule'] hot=2
- `venture_propose_plus_frontier`: must=0.67 recovered=[] still_missing=['schedule'] hot=2

### `verify_hard.json:h45` miss=['track', 'record', 'charge', 'log']
- `composite_v1`: must=0.20 recovered=[] still_missing=['track', 'record', 'charge', 'log'] hot=1
- `venture_multiview`: must=0.40 recovered=['charge'] still_missing=['track', 'record', 'log'] hot=2
- `venture_propose_verify`: must=0.20 recovered=[] still_missing=['track', 'record', 'charge', 'log'] hot=1
- `venture_propose_plus_frontier`: must=0.20 recovered=[] still_missing=['track', 'record', 'charge', 'log'] hot=1

### `verify_hard.json:h46` miss=['track']
- `composite_v1`: must=0.67 recovered=[] still_missing=['track'] hot=8
- `venture_multiview`: must=0.67 recovered=[] still_missing=['track'] hot=9
- `venture_propose_verify`: must=0.67 recovered=[] still_missing=['track'] hot=8
- `venture_propose_plus_frontier`: must=0.67 recovered=[] still_missing=['track'] hot=8

### `verify_hard.json:h47` miss=['JwtService.verify', 'verify_sig']
- `composite_v1`: must=0.33 recovered=[] still_missing=['JwtService.verify', 'verify_sig'] hot=1
- `venture_multiview`: must=1.00 recovered=['JwtService.verify', 'verify_sig'] still_missing=[] hot=3
- `venture_propose_verify`: must=0.67 recovered=['verify_sig'] still_missing=['JwtService.verify'] hot=2
- `venture_propose_plus_frontier`: must=0.67 recovered=['verify_sig'] still_missing=['JwtService.verify'] hot=2

### `verify_hard.json:h49` miss=['track', 'log']
- `composite_v1`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=4
- `venture_multiview`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=4
- `venture_propose_verify`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=4
- `venture_propose_plus_frontier`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=4

### `verify_ood_v2.json:o17` miss=['fetch_docs', 'query', 'rank']
- `composite_v1`: must=0.25 recovered=[] still_missing=['fetch_docs', 'query', 'rank'] hot=1
- `venture_multiview`: must=0.75 recovered=['query', 'rank'] still_missing=['fetch_docs'] hot=3
- `venture_propose_verify`: must=0.50 recovered=['query'] still_missing=['fetch_docs', 'rank'] hot=2
- `venture_propose_plus_frontier`: must=0.50 recovered=['query'] still_missing=['fetch_docs', 'rank'] hot=2

### `verify_prod.json:p19` miss=['track', 'log']
- `composite_v1`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=4
- `venture_multiview`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=5
- `venture_propose_verify`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=4
- `venture_propose_plus_frontier`: must=0.67 recovered=[] still_missing=['track', 'log'] hot=4

### `verify_ood_v10_realistic.json:real02` miss=['charge', 'validate', 'reserve', 'send', 'schedule']
- `composite_v1`: must=0.44 recovered=[] still_missing=['charge', 'validate', 'reserve', 'send', 'schedule'] hot=6
- `venture_multiview`: must=0.89 recovered=['charge', 'validate', 'reserve', 'schedule'] still_missing=['send'] hot=10
- `venture_propose_verify`: must=0.44 recovered=[] still_missing=['charge', 'validate', 'reserve', 'send', 'schedule'] hot=6
- `venture_propose_plus_frontier`: must=0.44 recovered=[] still_missing=['charge', 'validate', 'reserve', 'send', 'schedule'] hot=6

### `verify_ood_v10_realistic.json:real04` miss=['send']
- `composite_v1`: must=0.86 recovered=[] still_missing=['send'] hot=6
- `venture_multiview`: must=0.86 recovered=[] still_missing=['send'] hot=7
- `venture_propose_verify`: must=0.86 recovered=[] still_missing=['send'] hot=6
- `venture_propose_plus_frontier`: must=0.86 recovered=[] still_missing=['send'] hot=6

