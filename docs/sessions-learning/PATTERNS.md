# Patterns mined from all sessions (auto-generated)

Source: `data/sessions.jsonl` (regenerate: `python docs/sessions-learning/mine_patterns.py`).
Total cells: 124.

## Dev-task arms (tokens, calls, correctness)

| arm | n | tok mean | tok med | api mean | map mean | grep mean | success |
|---|--:|--:|--:|--:|--:|--:|:--:|
| mini | 7 | 495506 | 456232 | 13 | 1 | 4 | 7/7 |
| mini_plus | 2 | 389318 | 389318 | 10 | 1 | 2 | 1/2 |
| mini_v3 | 19 | 348427 | 328086 | 10 | 1 | 2 | 18/19 |
| newmap | 15 | 410831 | 353116 | 10 | 3 | 0 | 15/15 |
| without | 10 | 802736 | 702633 | 18 | 0 | 6 | 9/10 |

## mini_v3 vs newmap, matched (run, task, rep)

| run | task | rep | mini_v3 tok | newmap tok | newmap cheaper | both pass |
|---|---|--:|--:|--:|:--:|:--:|
| 20261001T173822 | cache_aware_savings | 1 | 462,220 | 544,249 | n | n |
| 20261001T181831 | cache_aware_savings | 1 | 400,364 | 692,488 | n | Y |
| 20261001T191233 | cache_aware_savings | 1 | 318,481 | 546,890 | n | Y |
| 20261001T195500 | cache_aware_savings | 1 | 404,813 | 271,702 | Y | Y |
| 20261001T204350 | cache_aware_savings | 1 | 328,086 | 765,982 | n | Y |
| 20261002T055341 | cache_aware_savings | 1 | 480,211 | 292,292 | Y | Y |
| 20261002T061103 | cache_aware_savings | 1 | 289,505 | 554,355 | n | Y |
| 20261002T061103 | cache_aware_savings | 2 | 238,665 | 578,385 | n | Y |
| 20261002T061103 | cache_aware_savings | 3 | 445,176 | 675,780 | n | Y |
| 20261001T173135 | dirty_files_cap | 1 | 258,057 | 353,116 | n | Y |
| 20261001T182749 | dirty_files_cap | 1 | 249,463 | 254,872 | n | Y |
| 20261001T192151 | dirty_files_cap | 1 | 147,004 | 122,271 | Y | Y |
| 20261001T200122 | dirty_files_cap | 1 | 147,465 | 128,712 | Y | Y |
| 20261001T205047 | dirty_files_cap | 1 | 248,622 | 221,315 | Y | Y |
| 20261002T060212 | dirty_files_cap | 1 | 401,189 | 160,057 | Y | Y |

newmap cheaper in 6/15 matched pairs.

## find follow-up (newmap): locate calls between first find and first edit

find alone sufficed (0 follow-up locate calls) in 2/14 newmap cells.

- 20261001T173135 dirty_files_cap: 4 follow-up (map:around, map:refs, map:refs, map:refs)
- 20261001T173822 cache_aware_savings: 2 follow-up (map:refs, map:open)
- 20261001T181831 cache_aware_savings: 1 follow-up (map:view)
- 20261001T182749 dirty_files_cap: 3 follow-up (map:refs, map:refs, map:view)
- 20261001T191233 cache_aware_savings: 3 follow-up (map:view, map:view, map:refs)
- 20261001T192151 dirty_files_cap: 0 follow-up (none)
- 20261001T195500 cache_aware_savings: 1 follow-up (map:view)
- 20261001T200122 dirty_files_cap: 0 follow-up (none)
- 20261001T204350 cache_aware_savings: 2 follow-up (map:view, map:refs)
- 20261001T205047 dirty_files_cap: 3 follow-up (map:refs, map:refs, map:refs)
- 20261002T055341 cache_aware_savings: 2 follow-up (map:view, map:find)
- 20261002T061103 cache_aware_savings: 2 follow-up (map:view, map:find)
- 20261002T061103 cache_aware_savings: 3 follow-up (map:view, map:view, map:find)
- 20261002T061103 cache_aware_savings: 1 follow-up (map:view)

## newmap map-config usage (all cells)

| config | calls |
|---|--:|
| find | 17 |
| refs | 14 |
| view | 13 |
| around | 1 |
| open | 1 |

## Retrieval-challenge arms (recall / precision)

| arm | n | recall | precision | tok mean |
|---|--:|--:|--:|--:|
| guided | 9 | 1 | 0 | 381159 |
| map_v3 | 3 | 1 | 1 | 176132 |
| mini_v3 | 3 | 1 | 1 | 196093 |
| two_layer | 9 | 1 | 1 | 359345 |
| two_layer_v2 | 12 | 1 | 1 | 339870 |
| without | 9 | 1 | 0 | 359170 |
