# Sessions log (auto-generated)

Generated 2026-10-02T14:36:58+00:00 from `.ab_workspaces\claude_sdk_harness`.
210 cells across 57 runs (50 with measured cells, 7 empty-scaffold runs omitted below). Regenerate with `python docs/sessions-learning/extract_sessions.py`.

Columns: arm | task | tokens | api_calls | map | grep | edit | oracle/recall | tool sequence

## 20260929T161856Z_packbodies  _(untagged)_

- **heatmap_only** | None | tok=- | api=- | map=0 grep=0 edit=0 | oracle=None/False
  - seq: -
- **with_bodies** | None | tok=- | api=- | map=0 grep=0 edit=0 | oracle=None/True
  - seq: -

## 20260929T162905Z_packbodies  _(untagged)_

- **heatmap_only** | None | tok=- | api=- | map=0 grep=0 edit=0 | oracle=None/True
  - seq: -
- **with_bodies** | None | tok=- | api=- | map=0 grep=0 edit=0 | oracle=None/True
  - seq: -

## 20260930T124113Z_3arm  _(untagged)_

- **A_without** | None | tok=- | api=- | map=0 grep=0 edit=0 | oracle=None/True
  - seq: -
- **B_map_only** | None | tok=- | api=- | map=0 grep=0 edit=0 | oracle=None/True
  - seq: -
- **C_map_session** | None | tok=- | api=- | map=0 grep=0 edit=0 | oracle=None/True
  - seq: -

## 20260930T131625Z_bigAB  _(untagged)_

- **A_without** | None | tok=- | api=- | map=0 grep=0 edit=0 | oracle=None/False
  - seq: -
- **B_map_only** | None | tok=- | api=- | map=0 grep=0 edit=0 | oracle=None/False
  - seq: -

## 20260930T142534Z_smallStrict  _(untagged)_

- **A_without** | None | tok=- | api=- | map=0 grep=0 edit=0 | oracle=None/True
  - seq: -
- **B_map_strict** | None | tok=- | api=- | map=0 grep=0 edit=0 | oracle=None/False
  - seq: -

## 20260930T144826Z_smallGuided  _(untagged)_

- **A_without** | None | tok=- | api=- | map=0 grep=0 edit=0 | oracle=None/True
  - seq: -
- **B_map_guided** | None | tok=- | api=- | map=0 grep=0 edit=0 | oracle=None/True
  - seq: -

## 20260930T151708Z_rules4  _(untagged)_

- **A_without** | None | tok=- | api=- | map=0 grep=0 edit=0 | oracle=None/True
  - seq: -
- **B_map_flexible** | None | tok=- | api=- | map=0 grep=0 edit=0 | oracle=None/False
  - seq: -
- **C_map_strict** | None | tok=- | api=- | map=0 grep=0 edit=0 | oracle=None/True
  - seq: -
- **D_map_guided** | None | tok=- | api=- | map=0 grep=0 edit=0 | oracle=None/True
  - seq: -

## 20260930T154207Z_gVs  _(untagged)_

- **G_map_guided** | None | tok=- | api=- | map=0 grep=0 edit=0 | oracle=None/False
  - seq: -
- **S_map_strict** | None | tok=- | api=- | map=0 grep=0 edit=0 | oracle=None/True
  - seq: -

## 20260930T171309Z_retrieval  _(retrieval_challenge)_

- **without** | idle_engine_self_retire | tok=278,477 | api=- | map=0 grep=7 edit=0 | recall=1.0 prec=0.25
  - seq: -
- **guided** | idle_engine_self_retire | tok=347,682 | api=- | map=2 grep=2 edit=0 | recall=1.0 prec=0.333
  - seq: -
- **two_layer** | idle_engine_self_retire | tok=265,768 | api=- | map=2 grep=1 edit=0 | recall=1.0 prec=0.5
  - seq: -
- **without** | dirty_path_first_char | tok=263,232 | api=- | map=0 grep=6 edit=0 | recall=1.0 prec=1.0
  - seq: -
- **guided** | dirty_path_first_char | tok=350,751 | api=- | map=2 grep=2 edit=0 | recall=1.0 prec=0.5
  - seq: -
- **two_layer** | dirty_path_first_char | tok=441,359 | api=- | map=2 grep=3 edit=0 | recall=1.0 prec=1.0
  - seq: -

## 20260930T172308Z_retrieval  _(retrieval_challenge)_

- **without** | idle_engine_self_retire | tok=973,962 | api=- | map=0 grep=11 edit=0 | recall=1.0 prec=0.2
  - seq: Grep -> Grep -> Grep -> Grep -> Grep -> Read -> Read -> Grep -> Grep -> Read -> Grep -> Grep -> Grep -> Read
- **guided** | idle_engine_self_retire | tok=300,252 | api=- | map=2 grep=4 edit=0 | recall=1.0 prec=0.25 cfg=?:2
  - seq: map:? -> map:? -> Read -> Read -> Grep -> Read -> Grep -> Grep -> Grep -> Read -> Write
- **two_layer** | idle_engine_self_retire | tok=456,737 | api=- | map=2 grep=4 edit=0 | recall=1.0 prec=0.333 cfg=?:2
  - seq: map:? -> map:? -> Read -> Read -> Read -> Read -> Grep -> Grep -> Grep -> Grep -> Write

## 20260930T184945Z_retrieval  _(retrieval_challenge)_

- **guided** | idle_engine_self_retire | tok=439,264 | api=13 | map=2 grep=4 edit=0 | recall=1.0 prec=0.333 cfg=?:2
  - seq: map:? -> map:? -> Read -> Read -> Grep -> Grep -> Read -> Grep -> Read -> Grep -> Write
- **guided** | idle_engine_self_retire | tok=454,634 | api=13 | map=2 grep=4 edit=0 | recall=1.0 prec=0.25 cfg=?:2
  - seq: map:? -> map:? -> Read -> Read -> Read -> Grep -> Grep -> Grep -> Grep -> Read -> Read -> Glob -> Glob -> Glob
- **guided** | idle_engine_self_retire | tok=343,396 | api=10 | map=2 grep=2 edit=0 | recall=1.0 prec=0.25 cfg=?:2
  - seq: map:? -> map:? -> Read -> Read -> Read -> Grep -> Read -> Read -> Grep -> Read -> Read -> Write
- **two_layer** | idle_engine_self_retire | tok=309,686 | api=9 | map=2 grep=2 edit=0 | recall=1.0 prec=0.5 cfg=?:2
  - seq: map:? -> map:? -> Read -> Read -> Read -> Grep -> Read -> Read -> Grep -> Write
- **two_layer** | idle_engine_self_retire | tok=270,912 | api=8 | map=2 grep=1 edit=0 | recall=1.0 prec=0.333 cfg=?:2
  - seq: map:? -> map:? -> Read -> Read -> Read -> Read -> Grep -> Write
- **two_layer** | idle_engine_self_retire | tok=433,979 | api=12 | map=2 grep=5 edit=0 | recall=1.0 prec=0.333 cfg=?:2
  - seq: map:? -> map:? -> Read -> Read -> Grep -> Read -> Read -> Grep -> Grep -> Grep -> Read -> Grep -> Write
- **two_layer_v2** | idle_engine_self_retire | tok=262,766 | api=8 | map=2 grep=1 edit=0 | recall=1.0 prec=0.333 cfg=?:2
  - seq: map:? -> map:? -> Read -> Read -> Read -> Grep -> Read -> Read -> Write
- **two_layer_v2** | idle_engine_self_retire | tok=294,873 | api=9 | map=2 grep=1 edit=0 | recall=1.0 prec=0.333 cfg=?:2
  - seq: map:? -> map:? -> Read -> Read -> Read -> Grep -> Read -> Write
- **two_layer_v2** | idle_engine_self_retire | tok=367,737 | api=10 | map=2 grep=2 edit=0 | recall=1.0 prec=0.25 cfg=?:2
  - seq: map:? -> map:? -> Read -> Read -> Read -> Read -> Grep -> Read -> Read -> Grep -> Read -> Write
- **guided** | dirty_path_first_char | tok=319,927 | api=10 | map=2 grep=0 edit=0 | recall=1.0 prec=1.0 cfg=?:2
  - seq: map:? -> map:? -> Read -> Read -> Glob -> Bash -> Read -> Read -> Write
- **guided** | dirty_path_first_char | tok=461,011 | api=14 | map=2 grep=2 edit=0 | recall=0.0 prec=0.0 cfg=?:2
  - seq: map:? -> map:? -> Grep -> Read -> Read -> Bash -> Glob -> Bash -> Bash -> Bash -> Read -> Grep -> Read
- **guided** | dirty_path_first_char | tok=413,514 | api=12 | map=2 grep=3 edit=0 | recall=1.0 prec=0.5 cfg=?:2
  - seq: map:? -> map:? -> Read -> Read -> Glob -> Read -> Glob -> Read -> Glob -> Glob -> Grep -> Grep -> Grep -> Write
- **two_layer** | dirty_path_first_char | tok=367,481 | api=11 | map=2 grep=3 edit=0 | recall=1.0 prec=1.0 cfg=?:2
  - seq: map:? -> map:? -> Read -> Grep -> Glob -> Grep -> Read -> Grep -> Bash -> Bash -> Write
- **two_layer** | dirty_path_first_char | tok=357,341 | api=11 | map=2 grep=1 edit=0 | recall=1.0 prec=0.5 cfg=?:2
  - seq: map:? -> map:? -> Read -> Glob -> Glob -> Glob -> Glob -> Bash -> Read -> Grep -> Write
- **two_layer** | dirty_path_first_char | tok=330,844 | api=10 | map=2 grep=3 edit=0 | recall=1.0 prec=1.0 cfg=?:2
  - seq: map:? -> map:? -> Read -> Glob -> Glob -> Glob -> Read -> Grep -> Grep -> Grep -> Write
- **two_layer_v2** | dirty_path_first_char | tok=258,202 | api=8 | map=2 grep=0 edit=0 | recall=1.0 prec=1.0 cfg=?:2
  - seq: map:? -> map:? -> Read -> Read -> Glob -> Bash -> Write
- **two_layer_v2** | dirty_path_first_char | tok=426,744 | api=13 | map=2 grep=3 edit=0 | recall=1.0 prec=1.0 cfg=?:2
  - seq: map:? -> map:? -> Read -> Grep -> Grep -> Glob -> Read -> Read -> Glob -> Glob -> Bash -> Read -> Grep -> Read
- **two_layer_v2** | dirty_path_first_char | tok=333,499 | api=10 | map=2 grep=2 edit=0 | recall=1.0 prec=1.0 cfg=?:2
  - seq: map:? -> map:? -> Read -> Read -> Glob -> Grep -> Grep -> Bash -> Write

## 20260930T191159Z_retrieval  _(retrieval_challenge)_

- **without** | dirty_path_first_char | tok=281,435 | api=7 | map=0 grep=4 edit=0 | recall=1.0 prec=0.5
  - seq: Grep -> Grep -> Read -> Read -> Grep -> Read -> Grep -> Read -> Write
- **without** | dirty_path_first_char | tok=177,504 | api=5 | map=0 grep=3 edit=0 | recall=1.0 prec=1.0
  - seq: Grep -> Grep -> Read -> Read -> Read -> Grep -> Write
- **without** | dirty_path_first_char | tok=212,217 | api=6 | map=0 grep=5 edit=0 | recall=1.0 prec=0.25
  - seq: Grep -> Grep -> Read -> Read -> Grep -> Grep -> Grep -> Write
- **two_layer_v2** | dirty_path_first_char | tok=388,484 | api=12 | map=2 grep=4 edit=0 | recall=1.0 prec=0.5 cfg=?:2
  - seq: map:? -> map:? -> Read -> Grep -> Glob -> Grep -> Grep -> Glob -> Read -> Grep -> Glob -> Bash -> Read -> Write
- **two_layer_v2** | dirty_path_first_char | tok=462,382 | api=13 | map=2 grep=3 edit=0 | recall=1.0 prec=1.0 cfg=?:2
  - seq: map:? -> map:? -> Read -> Grep -> Glob -> Grep -> Glob -> Grep -> Read -> Read -> Bash -> Bash -> Bash -> Bash
- **two_layer_v2** | dirty_path_first_char | tok=455,117 | api=14 | map=2 grep=2 edit=0 | recall=1.0 prec=0.5 cfg=?:2
  - seq: map:? -> map:? -> Grep -> Grep -> Read -> Read -> Read -> Glob -> Glob -> Glob -> Read -> Read -> Glob -> Read
- **without** | idle_engine_self_retire | tok=346,643 | api=10 | map=0 grep=9 edit=0 | recall=1.0 prec=0.25
  - seq: Grep -> Grep -> Grep -> Grep -> Grep -> Grep -> Grep -> Read -> Read -> Grep -> Read -> Grep -> Read -> Write
- **without** | idle_engine_self_retire | tok=346,819 | api=9 | map=0 grep=11 edit=0 | recall=1.0 prec=0.2
  - seq: Grep -> Grep -> Grep -> Grep -> Grep -> Grep -> Grep -> Grep -> Grep -> Grep -> Read -> Read -> Grep -> Read
- **without** | idle_engine_self_retire | tok=352,240 | api=10 | map=0 grep=9 edit=0 | recall=1.0 prec=0.25
  - seq: Grep -> Grep -> Grep -> Grep -> Grep -> Grep -> Read -> Grep -> Grep -> Grep -> Read -> Read -> Read -> Write
- **two_layer_v2** | idle_engine_self_retire | tok=270,447 | api=8 | map=2 grep=2 edit=0 | recall=1.0 prec=0.2 cfg=?:2
  - seq: map:? -> map:? -> Read -> Read -> Grep -> Read -> Grep -> Read -> Write
- **two_layer_v2** | idle_engine_self_retire | tok=297,611 | api=9 | map=2 grep=2 edit=0 | recall=1.0 prec=0.333 cfg=?:2
  - seq: map:? -> map:? -> Read -> Read -> Read -> Grep -> Grep -> Read -> Write
- **two_layer_v2** | idle_engine_self_retire | tok=260,578 | api=8 | map=2 grep=1 edit=0 | recall=1.0 prec=0.333 cfg=?:2
  - seq: map:? -> map:? -> Read -> Read -> Read -> Grep -> Read -> Read -> Write

## 20260930T193909Z_devmini  _(dev_task_mini_bridge)_

- **without** | cache_aware_savings | tok=1,721,571 | api=32 | map=0 grep=7 edit=7 | oracle=1.0/True
  - seq: Grep -> Read -> Grep -> Grep -> Read -> Grep -> Skill -> Skill -> Grep -> Grep -> Grep -> Edit -> Read -> Edit
- **mini** | cache_aware_savings | tok=834,091 | api=19 | map=1 grep=9 edit=3 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Grep -> Grep -> Glob -> Grep -> Grep -> Grep -> Grep -> Read -> Bash -> Skill -> Grep -> Grep

## 20260930T195647Z_devmini_dirty_files_cap  _(dev_task_mini_bridge)_

- **without** | dirty_files_cap | tok=610,091 | api=18 | map=0 grep=13 edit=1 | oracle=1.0/True
  - seq: Grep -> Grep -> Grep -> Grep -> Grep -> Grep -> Read -> Grep -> Grep -> Grep -> Grep -> Grep -> Grep -> Grep
- **mini** | dirty_files_cap | tok=354,847 | api=11 | map=1 grep=6 edit=1 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Grep -> Grep -> Grep -> Grep -> Grep -> Grep -> Edit -> Bash -> Read

## 20260930T201857Z_devmini_health_reason_flag  _(dev_task_mini_bridge)_

- **without** | health_reason_flag | tok=275,670 | api=9 | map=0 grep=4 edit=1 | oracle=1.0/True
  - seq: Grep -> Grep -> Grep -> Read -> Grep -> Edit -> Read -> Bash
- **without** | health_reason_flag | tok=1,861,476 | api=40 | map=0 grep=8 edit=4 | oracle=1.0/False
  - seq: Grep -> Grep -> Read -> Grep -> Grep -> Read -> Grep -> Grep -> Edit -> Read -> Edit -> Read -> Bash -> Bash
- **mini** | health_reason_flag | tok=829,146 | api=21 | map=1 grep=2 edit=2 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Read -> Grep -> Grep -> Edit -> Read -> Edit -> Bash -> Bash -> Bash -> Bash -> Bash -> Read
- **mini** | health_reason_flag | tok=456,232 | api=14 | map=1 grep=2 edit=2 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Read -> Grep -> Grep -> Edit -> Read -> Read -> Edit -> Bash -> Bash -> Bash

## 20260930T204146Z_devmini_dirty_files_cap  _(dev_task_mini_bridge)_

- **without** | dirty_files_cap | tok=205,050 | api=7 | map=0 grep=4 edit=1 | oracle=1.0/True
  - seq: Grep -> Grep -> Read -> Grep -> Grep -> Edit
- **mini** | dirty_files_cap | tok=208,396 | api=7 | map=0 grep=4 edit=1 | oracle=1.0/True
  - seq: Grep -> Grep -> Read -> Grep -> Grep -> Read -> Edit

## 20260930T204654Z_devmini_health_reason_flag  _(dev_task_mini_bridge)_

- **without** | health_reason_flag | tok=204,328 | api=7 | map=0 grep=4 edit=1 | oracle=1.0/True
  - seq: Grep -> Grep -> Grep -> Read -> Grep -> Edit
- **mini** | health_reason_flag | tok=173,348 | api=6 | map=1 grep=1 edit=1 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Grep -> Edit

## 20260930T205112Z_devmini_cache_aware_savings  _(dev_task_mini_bridge)_

- **without** | cache_aware_savings | tok=529,443 | api=13 | map=0 grep=4 edit=4 | oracle=1.0/True
  - seq: Grep -> Read -> Skill -> Grep -> Grep -> Grep -> Edit -> Edit -> Edit -> Edit -> Read -> Bash
- **mini** | cache_aware_savings | tok=612,483 | api=14 | map=1 grep=3 edit=4 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Skill -> Grep -> Grep -> Read -> Grep -> Edit -> Edit -> Edit -> Edit -> Read

## 20260930T211515Z_devmini_cache_aware_savings  _(dev_task_mini_bridge)_

- **without** | cache_aware_savings | tok=795,175 | api=17 | map=0 grep=3 edit=7 | oracle=1.0/True
  - seq: Grep -> Read -> Grep -> Read -> Bash -> Grep -> Bash -> Read -> Edit -> Edit -> Edit -> Edit -> Edit -> Edit
- **mini_v3** | cache_aware_savings | tok=392,246 | api=10 | map=1 grep=0 edit=6 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Edit -> Edit -> Edit -> Edit -> Edit -> Edit

## 20260930T213705Z_devmini_cache_aware_savings  _(dev_task_mini_bridge)_

- **without** | cache_aware_savings | tok=826,310 | api=16 | map=0 grep=6 edit=6 | oracle=1.0/True
  - seq: Grep -> Read -> Skill -> Grep -> Grep -> Grep -> Grep -> Grep -> Read -> Edit -> Edit -> Edit -> Edit -> Edit
- **without** | cache_aware_savings | tok=998,251 | api=17 | map=0 grep=8 edit=7 | oracle=1.0/True
  - seq: Grep -> Grep -> Read -> Grep -> Grep -> Read -> Grep -> Grep -> Glob -> Grep -> Read -> Read -> Read -> Edit
- **mini_v3** | cache_aware_savings | tok=476,516 | api=13 | map=1 grep=3 edit=4 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Skill -> Skill -> Grep -> Grep -> Grep -> Edit -> Edit -> Edit -> Edit
- **mini_v3** | cache_aware_savings | tok=785,531 | api=18 | map=1 grep=11 edit=2 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Grep -> Grep -> Grep -> Grep -> Read -> Grep -> Grep -> Skill -> Glob -> Grep -> Read -> Grep

## 20261001T173135Z_devmini_dirty_files_cap  _(dev_task_mini_bridge)_

- **mini_v3** | dirty_files_cap | tok=258,057 | api=8 | map=1 grep=2 edit=1 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Grep -> Read -> Read -> Grep -> Read -> Edit
- **newmap** | dirty_files_cap | tok=353,116 | api=11 | map=5 grep=2 edit=1 | oracle=1.0/True cfg=find:1,around:1,refs:3
  - seq: map:find -> map:around -> map:refs -> map:refs -> map:refs -> Glob -> Grep -> Read -> Edit

## 20261001T173822Z_devmini_cache_aware_savings  _(dev_task_mini_bridge)_

- **mini_v3** | cache_aware_savings | tok=462,220 | api=12 | map=2 grep=4 edit=2 | oracle=0.33/False cfg=?:2
  - seq: map:? -> Read -> map:? -> Read -> Grep -> Grep -> Grep -> Edit -> Edit -> Grep
- **newmap** | cache_aware_savings | tok=544,249 | api=13 | map=3 grep=0 edit=6 | oracle=1.0/True cfg=find:1,refs:1,open:1
  - seq: map:find -> Read -> map:refs -> map:open -> Edit -> Edit -> Edit -> Edit -> Edit -> Edit -> Read

## 20261001T181831Z_devmini_cache_aware_savings  _(dev_task_mini_bridge)_

- **mini_v3** | cache_aware_savings | tok=400,364 | api=11 | map=1 grep=0 edit=6 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Skill -> Edit -> Edit -> Edit -> Edit -> Edit -> Edit
- **newmap** | cache_aware_savings | tok=692,488 | api=17 | map=5 grep=0 edit=6 | oracle=1.0/True cfg=find:1,view:2,refs:2
  - seq: map:find -> map:view -> Read -> Skill -> Edit -> Edit -> Edit -> Edit -> Edit -> Edit -> map:refs -> map:refs -> map:view -> Read

## 20261001T182749Z_devmini_dirty_files_cap  _(dev_task_mini_bridge)_

- **mini_v3** | dirty_files_cap | tok=249,463 | api=8 | map=1 grep=2 edit=1 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Grep -> Read -> Grep -> Edit
- **newmap** | dirty_files_cap | tok=254,872 | api=8 | map=4 grep=1 edit=1 | oracle=1.0/True cfg=find:1,refs:2,view:1
  - seq: map:find -> map:refs -> map:refs -> Grep -> map:view -> Edit

## 20261001T191233Z_devmini_cache_aware_savings  _(dev_task_mini_bridge)_

- **mini_v3** | cache_aware_savings | tok=318,481 | api=9 | map=1 grep=0 edit=4 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Skill -> Edit -> Edit -> Edit -> Edit
- **newmap** | cache_aware_savings | tok=546,890 | api=14 | map=4 grep=0 edit=6 | oracle=1.0/True cfg=find:1,view:2,refs:1
  - seq: map:find -> map:view -> map:view -> Skill -> Skill -> map:refs -> Edit -> Edit -> Edit -> Edit -> Edit -> Edit

## 20261001T192151Z_devmini_dirty_files_cap  _(dev_task_mini_bridge)_

- **mini_v3** | dirty_files_cap | tok=147,004 | api=5 | map=1 grep=0 edit=1 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Edit
- **newmap** | dirty_files_cap | tok=122,271 | api=4 | map=1 grep=0 edit=1 | oracle=1.0/True cfg=find:1
  - seq: map:find -> Edit

## 20261001T195500Z_devmini_cache_aware_savings  _(dev_task_mini_bridge)_

- **mini_v3** | cache_aware_savings | tok=404,813 | api=11 | map=1 grep=2 edit=3 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Skill -> Skill -> Grep -> Grep -> Edit -> Edit -> Edit
- **newmap** | cache_aware_savings | tok=271,702 | api=7 | map=2 grep=0 edit=3 | oracle=1.0/True cfg=find:1,view:1
  - seq: map:find -> map:view -> Edit -> Edit -> Edit

## 20261001T200122Z_devmini_dirty_files_cap  _(dev_task_mini_bridge)_

- **mini_v3** | dirty_files_cap | tok=147,465 | api=5 | map=1 grep=0 edit=1 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Edit
- **newmap** | dirty_files_cap | tok=128,712 | api=4 | map=1 grep=0 edit=1 | oracle=1.0/True cfg=find:1
  - seq: map:find -> Edit

## 20261001T204350Z_devmini_cache_aware_savings  _(dev_task_mini_bridge)_

- **mini_v3** | cache_aware_savings | tok=328,086 | api=9 | map=1 grep=0 edit=5 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Edit -> Edit -> Edit -> Edit -> Edit
- **newmap** | cache_aware_savings | tok=765,982 | api=17 | map=3 grep=2 edit=7 | oracle=1.0/True cfg=find:1,view:1,refs:1
  - seq: map:find -> map:view -> Skill -> Grep -> Grep -> Read -> Read -> map:refs -> Edit -> Edit -> Edit -> Edit -> Edit -> Edit

## 20261001T205047Z_devmini_dirty_files_cap  _(dev_task_mini_bridge)_

- **mini_v3** | dirty_files_cap | tok=248,622 | api=8 | map=1 grep=2 edit=1 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Grep -> Read -> Grep -> Edit
- **newmap** | dirty_files_cap | tok=221,315 | api=7 | map=4 grep=0 edit=1 | oracle=1.0/True cfg=find:1,refs:3
  - seq: map:find -> map:refs -> map:refs -> map:refs -> Edit

## 20261002T055341Z_devmini_cache_aware_savings  _(dev_task_mini_bridge)_

- **mini_plus** | cache_aware_savings | tok=507,538 | api=13 | map=1 grep=1 edit=7 | oracle=0.33/False cfg=?:1
  - seq: map:? -> Read -> Skill -> Glob -> Edit -> Edit -> Edit -> Edit -> Edit -> Edit -> Edit
- **mini_v3** | cache_aware_savings | tok=480,211 | api=12 | map=1 grep=0 edit=8 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Edit -> Edit -> Edit -> Edit -> Edit -> Edit -> Edit -> Edit
- **newmap** | cache_aware_savings | tok=292,292 | api=8 | map=3 grep=0 edit=2 | oracle=1.0/True cfg=find:2,view:1
  - seq: map:find -> map:view -> Read -> map:find -> Edit -> Edit

## 20261002T060212Z_devmini_dirty_files_cap  _(dev_task_mini_bridge)_

- **mini_plus** | dirty_files_cap | tok=271,097 | api=8 | map=1 grep=3 edit=1 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Grep -> Grep -> Grep -> Read -> Edit
- **mini_v3** | dirty_files_cap | tok=401,189 | api=12 | map=1 grep=4 edit=1 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Grep -> Read -> Grep -> Grep -> Grep -> Read -> Read -> Edit
- **newmap** | dirty_files_cap | tok=160,057 | api=5 | map=2 grep=0 edit=1 | oracle=1.0/True cfg=refs:1,view:1
  - seq: map:refs -> map:view -> Edit

## 20261002T061103Z_devmini_cache_aware_savings  _(dev_task_mini_bridge)_

- **mini_v3** | cache_aware_savings | tok=289,505 | api=8 | map=1 grep=0 edit=3 | oracle=0.67/True cfg=?:1
  - seq: map:? -> Read -> Skill -> Edit -> Edit -> Edit
- **mini_v3** | cache_aware_savings | tok=238,665 | api=7 | map=1 grep=0 edit=2 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Skill -> Edit -> Edit
- **mini_v3** | cache_aware_savings | tok=445,176 | api=12 | map=1 grep=0 edit=7 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Skill -> Edit -> Edit -> Edit -> Edit -> Edit -> Edit -> Edit
- **newmap** | cache_aware_savings | tok=554,355 | api=13 | map=3 grep=1 edit=6 | oracle=1.0/True cfg=find:2,view:1
  - seq: map:find -> map:view -> Read -> map:find -> Grep -> Edit -> Edit -> Edit -> Edit -> Edit -> Edit
- **newmap** | cache_aware_savings | tok=578,385 | api=14 | map=4 grep=0 edit=6 | oracle=1.0/True cfg=find:2,view:2
  - seq: map:find -> map:view -> map:view -> Skill -> map:find -> Read -> Edit -> Edit -> Edit -> Edit -> Edit -> Edit
- **newmap** | cache_aware_savings | tok=675,780 | api=14 | map=2 grep=1 edit=3 | oracle=1.0/True cfg=find:1,view:1
  - seq: map:find -> map:view -> Read -> Skill -> Grep -> Read -> Read -> Read -> Read -> Edit -> Edit -> Edit

## 20261002T062735Z_devmini_dirty_files_cap  _(dev_task_mini_bridge)_

- **mini_v3** | dirty_files_cap | tok=146,505 | api=5 | map=1 grep=0 edit=1 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Edit

## 20261002T071147Z_retrieval  _(retrieval_challenge)_

- **mini_v3** | faiss_reimport_segfault | tok=181,275 | api=6 | map=2 grep=0 edit=0 | recall=1.0 prec=1.0 cfg=?:2
  - seq: map:? -> map:? -> Read -> Write
- **map_v3** | faiss_reimport_segfault | tok=154,364 | api=5 | map=1 grep=0 edit=0 | recall=1.0 prec=0.333 cfg=find:1
  - seq: map:find -> Read -> Write
- **mini_v3** | idle_engine_self_retire | tok=227,603 | api=7 | map=1 grep=1 edit=0 | recall=1.0 prec=0.5 cfg=?:1
  - seq: map:? -> Read -> Read -> Read -> Grep -> Read -> Read -> Write
- **map_v3** | idle_engine_self_retire | tok=219,510 | api=7 | map=4 grep=0 edit=0 | recall=1.0 prec=0.333 cfg=find:1,focus:3
  - seq: map:find -> map:focus -> map:focus -> map:focus -> Write
- **mini_v3** | dirty_path_first_char | tok=179,400 | api=6 | map=1 grep=0 edit=0 | recall=1.0 prec=1.0 cfg=?:1
  - seq: map:? -> Read -> Read -> Write
- **map_v3** | dirty_path_first_char | tok=154,522 | api=5 | map=2 grep=0 edit=0 | recall=1.0 prec=1.0 cfg=find:1,focus:1
  - seq: map:find -> map:focus -> Write

## 20261002T074646Z_retrieval  _(retrieval_challenge)_

- **mini_v3** | dirty_path_first_char | tok=212,248 | api=7 | map=1 grep=2 edit=0 | recall=1.0 prec=1.0 cfg=?:1
  - seq: map:? -> Grep -> Grep -> Read -> Write
- **map_v3** | dirty_path_first_char | tok=159,943 | api=5 | map=2 grep=0 edit=0 | recall=1.0 prec=0.5 cfg=find:1,focus:1
  - seq: map:find -> map:focus -> Write
- **mini_v3** | idle_engine_self_retire | tok=288,488 | api=9 | map=1 grep=1 edit=0 | recall=1.0 prec=0.5 cfg=?:1
  - seq: map:? -> Read -> Read -> Read -> Grep -> Read -> Write
- **map_v3** | idle_engine_self_retire | tok=162,413 | api=5 | map=2 grep=0 edit=0 | recall=1.0 prec=0.2 cfg=find:1,focus:1
  - seq: map:find -> map:focus -> Write
- **mini_v3** | faiss_reimport_segfault | tok=145,856 | api=5 | map=1 grep=0 edit=0 | recall=1.0 prec=1.0 cfg=?:1
  - seq: map:? -> Read -> Write
- **map_v3** | faiss_reimport_segfault | tok=149,735 | api=5 | map=2 grep=0 edit=0 | recall=1.0 prec=1.0 cfg=find:1,focus:1
  - seq: map:find -> map:focus -> Write

## 20261002T085747Z_retrieval  _(retrieval_challenge)_

- **mini_v3** | first_map_skips_graph | tok=438,661 | api=12 | map=1 grep=8 edit=0 | recall=0.5 prec=0.667 cfg=?:1
  - seq: map:? -> Read -> Read -> Grep -> Grep -> Grep -> Grep -> Grep -> Read -> Grep -> Read -> Grep -> Grep -> Read
- **map_v3** | first_map_skips_graph | tok=610,589 | api=14 | map=5 grep=4 edit=0 | recall=1.0 prec=0.667 cfg=find:4,focus:1
  - seq: map:find -> map:find -> map:focus -> map:find -> map:find -> Grep -> Grep -> Read -> Grep -> Read -> Grep -> Write
- **mini_v3** | idle_engine_self_retire | tok=261,975 | api=8 | map=1 grep=2 edit=0 | recall=1.0 prec=0.25 cfg=?:1
  - seq: map:? -> Read -> Grep -> Read -> Read -> Read -> Grep -> Read -> Write
- **map_v3** | idle_engine_self_retire | tok=193,462 | api=6 | map=3 grep=0 edit=0 | recall=1.0 prec=0.25 cfg=find:2,focus:1
  - seq: map:find -> map:focus -> map:find -> Write
- **mini_v3** | cold_start_status_warming | tok=155,176 | api=5 | map=1 grep=0 edit=0 | recall=0.0 prec=0.0 cfg=?:1
  - seq: map:? -> Read -> Read -> Read -> Write
- **map_v3** | cold_start_status_warming | tok=119,745 | api=4 | map=1 grep=0 edit=0 | recall=0.0 prec=0.0 cfg=find:1
  - seq: map:find -> Write
- **mini_v3** | dirty_path_first_char | tok=210,907 | api=7 | map=1 grep=2 edit=0 | recall=1.0 prec=1.0 cfg=?:1
  - seq: map:? -> Grep -> Grep -> Read -> Write
- **map_v3** | dirty_path_first_char | tok=120,077 | api=4 | map=1 grep=0 edit=0 | recall=1.0 prec=0.5 cfg=find:1
  - seq: map:find -> Write
- **mini_v3** | faiss_reimport_segfault | tok=146,165 | api=5 | map=1 grep=0 edit=0 | recall=1.0 prec=1.0 cfg=?:1
  - seq: map:? -> Read -> Write
- **map_v3** | faiss_reimport_segfault | tok=120,408 | api=4 | map=1 grep=0 edit=0 | recall=1.0 prec=1.0 cfg=find:1
  - seq: map:find -> Write
- **mini_v3** | ir_indexed_once_per_sync | tok=185,973 | api=6 | map=1 grep=0 edit=0 | recall=1.0 prec=1.0 cfg=?:1
  - seq: map:? -> Read -> Read -> Write
- **map_v3** | ir_indexed_once_per_sync | tok=187,821 | api=6 | map=3 grep=0 edit=0 | recall=1.0 prec=0.333 cfg=find:1,focus:2
  - seq: map:find -> map:focus -> map:focus -> Write
- **mini_v3** | memory_budget_resets_threads | tok=253,438 | api=8 | map=1 grep=5 edit=0 | recall=1.0 prec=0.4 cfg=?:1
  - seq: map:? -> Grep -> Grep -> Grep -> Grep -> Grep -> Read -> Read -> Read -> Write
- **map_v3** | memory_budget_resets_threads | tok=245,854 | api=7 | map=4 grep=0 edit=0 | recall=1.0 prec=0.5 cfg=find:1,focus:3
  - seq: map:find -> map:focus -> map:focus -> map:focus -> Write
- **mini_v3** | watchdog_no_autoload_while_mcp | tok=466,261 | api=12 | map=1 grep=4 edit=0 | recall=1.0 prec=0.25 cfg=?:1
  - seq: map:? -> Read -> Read -> Read -> Grep -> Grep -> Read -> Read -> Grep -> Read -> Read -> Read -> Grep -> Read
- **map_v3** | watchdog_no_autoload_while_mcp | tok=362,914 | api=10 | map=5 grep=0 edit=0 | recall=1.0 prec=0.167 cfg=find:1,focus:3,graph:1
  - seq: map:find -> map:focus -> map:focus -> Read -> map:graph -> map:focus -> Read -> Write

## 20261002T091837Z_devmini_dirty_files_cap  _(dev_task_mini_bridge)_

- **mini_v3** | dirty_files_cap | tok=147,600 | api=5 | map=1 grep=0 edit=1 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Edit
- **map_v3** | dirty_files_cap | tok=244,069 | api=7 | map=1 grep=2 edit=1 | oracle=1.0/True cfg=find:1
  - seq: map:find -> Grep -> Grep -> Read -> Edit

## 20261002T092054Z_devmini_health_reason_flag  _(dev_task_mini_bridge)_

- **mini_v3** | health_reason_flag | tok=269,078 | api=9 | map=1 grep=4 edit=1 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Grep -> Grep -> Grep -> Grep -> Edit
- **map_v3** | health_reason_flag | tok=216,135 | api=7 | map=3 grep=0 edit=1 | oracle=1.0/True cfg=find:1,focus:2
  - seq: map:find -> map:focus -> Read -> map:focus -> Edit

## 20261002T092328Z_devmini_cache_aware_savings  _(dev_task_mini_bridge)_

- **mini_v3** | cache_aware_savings | tok=273,502 | api=8 | map=1 grep=0 edit=2 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Skill -> Skill -> Edit -> Edit
- **map_v3** | cache_aware_savings | tok=512,565 | api=12 | map=1 grep=4 edit=2 | oracle=1.0/True cfg=find:1
  - seq: map:find -> Read -> Skill -> Glob -> Grep -> Grep -> Grep -> Read -> Edit -> Edit

## 20261002T092922Z_comprehension  _(comprehension_eval)_

- **mini_v3** | comprehension | tok=0 | api=1 | map=0 grep=0 edit=0 | oracle=0.0/False
  - seq: -
- **map_v3** | comprehension | tok=0 | api=1 | map=0 grep=0 edit=0 | oracle=0.0/False
  - seq: -

## 20261002T102921Z_retrieval  _(retrieval_challenge)_

- **map_v3_a** | idle_engine_self_retire | tok=170,454 | api=5 | map=2 grep=0 edit=0 | recall=1.0 prec=0.333 cfg=find:1,focus:1
  - seq: map:find -> map:focus -> Write
- **map_v3_b** | idle_engine_self_retire | tok=194,873 | api=6 | map=2 grep=0 edit=0 | recall=1.0 prec=0.25 cfg=find:1,focus:1
  - seq: map:find -> map:focus -> Read -> Write
- **map_v3_c** | idle_engine_self_retire | tok=228,381 | api=7 | map=1 grep=2 edit=0 | recall=1.0 prec=0.2 cfg=find:1
  - seq: map:find -> Grep -> Read -> Read -> Read -> Grep -> Write
- **map_v3_a** | first_map_skips_graph | tok=538,141 | api=14 | map=3 grep=10 edit=0 | recall=0.0 prec=0.0 cfg=find:2,view:1
  - seq: map:find -> Grep -> Grep -> Grep -> map:find -> map:view -> Grep -> Grep -> Grep -> Grep -> Grep -> Grep -> Grep
- **map_v3_b** | first_map_skips_graph | tok=531,027 | api=14 | map=1 grep=11 edit=0 | recall=0.0 prec=0.0 cfg=find:1
  - seq: map:find -> Grep -> Grep -> Grep -> Grep -> Grep -> Grep -> Grep -> Read -> Grep -> Grep -> Grep -> Grep
- **map_v3_c** | first_map_skips_graph | tok=448,060 | api=13 | map=1 grep=5 edit=0 | recall=0.5 prec=0.5 cfg=find:1
  - seq: map:find -> Grep -> Grep -> Grep -> Read -> Grep -> Read -> Grep -> Read -> Read -> Write

## 20261002T104141Z_retrieval  _(retrieval_challenge)_

- **map_v3_a** | idle_engine_self_retire | tok=162,487 | api=5 | map=2 grep=0 edit=0 | recall=1.0 prec=0.25 cfg=find:1,focus:1
  - seq: map:find -> map:focus -> Write
- **map_v3_d** | idle_engine_self_retire | tok=267,381 | api=8 | map=2 grep=2 edit=0 | recall=1.0 prec=0.25 cfg=graph:1,focus:1
  - seq: map:graph -> map:focus -> Grep -> Read -> Grep -> Write
- **map_v3_a** | first_map_skips_graph | tok=618,253 | api=14 | map=1 grep=11 edit=0 | recall=0.0 prec=0.0 cfg=find:1
  - seq: map:find -> Grep -> Grep -> Grep -> Grep -> Read -> Grep -> Grep -> Grep -> Grep -> Grep -> Grep -> Grep
- **map_v3_d** | first_map_skips_graph | tok=486,630 | api=14 | map=2 grep=10 edit=0 | recall=0.0 prec=0.0 cfg=graph:1,find:1
  - seq: map:graph -> map:find -> Grep -> Grep -> Grep -> Grep -> Grep -> Grep -> Grep -> Grep -> Grep -> Read -> Grep

## 20261002T111343Z_retrieval  _(retrieval_challenge)_

- **map_v3_a** | idle_engine_self_retire | tok=161,105 | api=5 | map=2 grep=0 edit=0 | recall=1.0 prec=0.333 cfg=find:1,focus:1
  - seq: map:find -> map:focus -> Write
- **map_v3_s** | idle_engine_self_retire | tok=244,445 | api=7 | map=2 grep=2 edit=0 | recall=1.0 prec=0.333 cfg=graph:1,focus:1
  - seq: map:graph -> map:focus -> Grep -> Grep -> Write

## 20261002T112251Z_retrieval  _(retrieval_challenge)_

- **map_v3_a** | idle_engine_self_retire | tok=169,585 | api=5 | map=2 grep=0 edit=0 | recall=1.0 prec=0.2 cfg=find:1,focus:1
  - seq: map:find -> map:focus -> Write
- **map_v3_a** | idle_engine_self_retire | tok=162,930 | api=5 | map=2 grep=0 edit=0 | recall=1.0 prec=0.25 cfg=find:2
  - seq: map:find -> map:find -> Write
- **map_v3_s** | idle_engine_self_retire | tok=166,542 | api=5 | map=2 grep=0 edit=0 | recall=1.0 prec=0.25 cfg=graph:1,focus:1
  - seq: map:graph -> map:focus -> Write
- **map_v3_s** | idle_engine_self_retire | tok=163,156 | api=5 | map=2 grep=0 edit=0 | recall=1.0 prec=0.25 cfg=graph:1,focus:1
  - seq: map:graph -> map:focus -> Write

## 20261002T113103Z_retrieval  _(retrieval_challenge)_

- **map_v3_a** | faiss_reimport_segfault | tok=159,746 | api=5 | map=2 grep=0 edit=0 | recall=1.0 prec=1.0 cfg=find:1,focus:1
  - seq: map:find -> map:focus -> Write
- **map_v3_a** | faiss_reimport_segfault | tok=159,743 | api=5 | map=2 grep=0 edit=0 | recall=1.0 prec=1.0 cfg=find:1,focus:1
  - seq: map:find -> map:focus -> Write
- **map_v3_s** | faiss_reimport_segfault | tok=192,660 | api=6 | map=1 grep=1 edit=0 | recall=1.0 prec=0.5 cfg=find:1
  - seq: map:find -> Read -> Grep -> Write
- **map_v3_s** | faiss_reimport_segfault | tok=121,480 | api=4 | map=1 grep=0 edit=0 | recall=1.0 prec=0.5 cfg=find:1
  - seq: map:find -> Write
- **map_v3_a** | memory_budget_resets_threads | tok=205,952 | api=6 | map=3 grep=0 edit=0 | recall=1.0 prec=0.4 cfg=find:1,focus:2
  - seq: map:find -> map:focus -> map:focus -> Write
- **map_v3_a** | memory_budget_resets_threads | tok=309,698 | api=9 | map=2 grep=3 edit=0 | recall=1.0 prec=0.667 cfg=find:1,focus:1
  - seq: map:find -> map:focus -> Grep -> Grep -> Read -> Grep -> Write
- **map_v3_s** | memory_budget_resets_threads | tok=209,113 | api=6 | map=2 grep=0 edit=0 | recall=1.0 prec=0.5 cfg=graph:1,focus:1
  - seq: map:graph -> map:focus -> Read -> Write
- **map_v3_s** | memory_budget_resets_threads | tok=169,860 | api=5 | map=2 grep=0 edit=0 | recall=1.0 prec=0.4 cfg=graph:1,focus:1
  - seq: map:graph -> map:focus -> Write
- **map_v3_a** | first_map_skips_graph | tok=538,558 | api=14 | map=2 grep=9 edit=0 | recall=0.0 prec=0.0 cfg=find:2
  - seq: map:find -> map:find -> Grep -> Grep -> Grep -> Grep -> Grep -> Grep -> Read -> Grep -> Read -> Grep -> Grep
- **map_v3_a** | first_map_skips_graph | tok=480,277 | api=12 | map=2 grep=3 edit=0 | recall=1.0 prec=0.667 cfg=find:2
  - seq: map:find -> map:find -> Grep -> Read -> Grep -> Read -> Read -> Grep -> Read -> Write
- **map_v3_s** | first_map_skips_graph | tok=476,055 | api=12 | map=1 grep=7 edit=0 | recall=0.75 prec=0.429 cfg=find:1
  - seq: map:find -> Grep -> Read -> Read -> Read -> Grep -> Grep -> Grep -> Read -> Grep -> Grep -> Grep -> Write
- **map_v3_s** | first_map_skips_graph | tok=595,682 | api=14 | map=1 grep=8 edit=0 | recall=0.5 prec=0.667 cfg=find:1
  - seq: map:find -> Read -> Grep -> Grep -> Grep -> Grep -> Grep -> Grep -> Grep -> Read -> Grep -> Read -> Write

## 20261002T114531Z_devmini_dirty_files_cap  _(dev_task_mini_bridge)_

- **map_v3_a** | dirty_files_cap | tok=257,597 | api=7 | map=0 grep=4 edit=1 | oracle=1.0/True
  - seq: Grep -> Read -> Grep -> Grep -> Grep -> Edit
- **map_v3_a** | dirty_files_cap | tok=124,502 | api=4 | map=1 grep=0 edit=1 | oracle=1.0/True cfg=find:1
  - seq: map:find -> Edit
- **map_v3_s** | dirty_files_cap | tok=293,325 | api=8 | map=1 grep=5 edit=1 | oracle=1.0/True cfg=find:1
  - seq: map:find -> Grep -> Read -> Read -> Grep -> Glob -> Grep -> Grep -> Edit
- **map_v3_s** | dirty_files_cap | tok=317,327 | api=9 | map=0 grep=5 edit=1 | oracle=1.0/True
  - seq: Grep -> Grep -> Read -> Grep -> Grep -> Read -> Grep -> Edit

## 20261002T134207Z_retrieval  _(retrieval_challenge)_

- **map_v3_a** | memory_budget_resets_threads | tok=171,413 | api=5 | map=2 grep=0 edit=0 | recall=0.5 prec=0.25 cfg=find:1,focus:1
  - seq: map:find -> map:focus -> Write
- **map_v3_a** | memory_budget_resets_threads | tok=169,972 | api=5 | map=2 grep=0 edit=0 | recall=0.5 prec=0.2 cfg=find:1,focus:1
  - seq: map:find -> map:focus -> Write
- **map_v3_u** | memory_budget_resets_threads | tok=166,267 | api=5 | map=2 grep=0 edit=0 | recall=1.0 prec=1.0 cfg=graph:1,focus:1
  - seq: map:graph -> map:focus -> Write
- **map_v3_u** | memory_budget_resets_threads | tok=206,724 | api=6 | map=2 grep=0 edit=0 | recall=1.0 prec=0.5 cfg=graph:1,focus:1
  - seq: map:graph -> map:focus -> Read -> Write
- **map_v3_a** | idle_engine_self_retire | tok=169,789 | api=5 | map=2 grep=0 edit=0 | recall=1.0 prec=0.25 cfg=find:1,focus:1
  - seq: map:find -> map:focus -> Write
- **map_v3_a** | idle_engine_self_retire | tok=165,662 | api=5 | map=2 grep=0 edit=0 | recall=1.0 prec=0.333 cfg=find:1,focus:1
  - seq: map:find -> map:focus -> Write
- **map_v3_u** | idle_engine_self_retire | tok=317,084 | api=9 | map=2 grep=2 edit=0 | recall=1.0 prec=0.25 cfg=graph:1,focus:1
  - seq: map:graph -> map:focus -> Grep -> Read -> Grep -> Read -> Write
- **map_v3_u** | idle_engine_self_retire | tok=163,602 | api=5 | map=2 grep=0 edit=0 | recall=1.0 prec=0.333 cfg=graph:1,focus:1
  - seq: map:graph -> map:focus -> Write

## 20261002T141705Z_retrieval  _(retrieval_challenge)_

- **mini_v3** | first_map_skips_graph | tok=553,512 | api=14 | map=2 grep=8 edit=0 | recall=0.0 prec=0.0 cfg=?:2
  - seq: map:? -> Read -> Read -> Read -> Grep -> Grep -> map:? -> Grep -> Grep -> Grep -> Read -> Grep -> Grep -> Grep
- **mini_v3** | first_map_skips_graph | tok=564,141 | api=14 | map=4 grep=6 edit=0 | recall=0.0 prec=0.0 cfg=?:4
  - seq: map:? -> map:? -> Read -> Read -> Grep -> Read -> map:? -> map:? -> Grep -> Grep -> Grep -> Grep -> Grep
- **map_v3** | first_map_skips_graph | tok=655,116 | api=14 | map=2 grep=9 edit=0 | recall=0.0 prec=0.0 cfg=graph:1,focus:1
  - seq: map:graph -> map:focus -> Grep -> Grep -> Grep -> Grep -> Read -> Grep -> Grep -> Grep -> Read -> Grep -> Grep
- **map_v3** | first_map_skips_graph | tok=567,545 | api=14 | map=2 grep=10 edit=0 | recall=0.0 prec=0.0 cfg=graph:1,focus:1
  - seq: map:graph -> map:focus -> Grep -> Grep -> Grep -> Grep -> Read -> Grep -> Grep -> Grep -> Grep -> Grep -> Grep
- **mini_v3** | faiss_reimport_segfault | tok=145,775 | api=5 | map=1 grep=0 edit=0 | recall=1.0 prec=1.0 cfg=?:1
  - seq: map:? -> Read -> Write
- **mini_v3** | faiss_reimport_segfault | tok=178,230 | api=6 | map=1 grep=1 edit=0 | recall=1.0 prec=1.0 cfg=?:1
  - seq: map:? -> Read -> Grep -> Write
- **map_v3** | faiss_reimport_segfault | tok=122,395 | api=4 | map=1 grep=0 edit=0 | recall=1.0 prec=1.0 cfg=find:1
  - seq: map:find -> Write
- **map_v3** | faiss_reimport_segfault | tok=156,007 | api=5 | map=2 grep=0 edit=0 | recall=1.0 prec=0.5 cfg=find:1,focus:1
  - seq: map:find -> map:focus -> Write
- **mini_v3** | memory_budget_resets_threads | tok=229,209 | api=7 | map=1 grep=1 edit=0 | recall=1.0 prec=0.667 cfg=?:1
  - seq: map:? -> Read -> Read -> Read -> Grep -> Read -> Write
- **mini_v3** | memory_budget_resets_threads | tok=275,013 | api=8 | map=1 grep=1 edit=0 | recall=1.0 prec=0.4 cfg=?:1
  - seq: map:? -> Read -> Read -> Read -> Grep -> Read -> Read -> Write
- **map_v3** | memory_budget_resets_threads | tok=162,790 | api=5 | map=2 grep=0 edit=0 | recall=1.0 prec=0.4 cfg=graph:1,focus:1
  - seq: map:graph -> map:focus -> Write
- **map_v3** | memory_budget_resets_threads | tok=287,235 | api=8 | map=2 grep=2 edit=0 | recall=1.0 prec=1.0 cfg=graph:1,focus:1
  - seq: map:graph -> map:focus -> Read -> Grep -> Grep -> Write

## 20261002T143215Z_devmini_dirty_files_cap  _(dev_task_mini_bridge)_

- **mini_v3** | dirty_files_cap | tok=505,252 | api=13 | map=1 grep=6 edit=1 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Grep -> Read -> Grep -> Glob -> Grep -> Grep -> Grep -> Edit -> Read
- **mini_v3** | dirty_files_cap | tok=147,701 | api=5 | map=1 grep=0 edit=1 | oracle=1.0/True cfg=?:1
  - seq: map:? -> Read -> Edit
- **map_v3** | dirty_files_cap | tok=153,737 | api=5 | map=1 grep=0 edit=1 | oracle=1.0/True cfg=find:1
  - seq: map:find -> Read -> Edit
- **map_v3** | dirty_files_cap | tok=158,778 | api=5 | map=0 grep=2 edit=1 | oracle=1.0/True
  - seq: Grep -> Read -> Grep -> Edit
