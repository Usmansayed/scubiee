# Trajectory-level mining (auto-generated)

From `data/sessions.jsonl`. Regenerate: `python docs/sessions-learning/mine_trajectories.py`.

## 1. Cost is driven by call count, quantified

- **without** (n=10): corr(api_calls, tokens)=0.974; corr(grep, tokens)=0.38
- **mini** (n=7): corr(api_calls, tokens)=0.978; corr(grep, tokens)=0.365
- **mini_v3** (n=19): corr(api_calls, tokens)=0.988; corr(grep, tokens)=0.724
- **newmap** (n=15): corr(api_calls, tokens)=0.982; corr(grep, tokens)=0.369
- **all dev cells** (n=53): corr(api_calls, tokens)=0.979

## 2. Grep fallback incidence and penalty

- **mini_v3**: 8/19 cells fell back to grep. mean tok with grep=410801 vs no grep=303064
- **newmap**: 5/15 cells fell back to grep. mean tok with grep=520821 vs no grep=355836

## 3. Trajectory shapes, cheapest vs priciest per arm

### mini_v3
cheapest 3:
- 146,505 tok (dirty_files): `map:? Read Edit`
- 147,004 tok (dirty_files): `map:? Read Edit`
- 147,465 tok (dirty_files): `map:? Read Edit`
priciest 3:
- 476,516 tok (cache_aware): `map:? Read Skill*2 Grep*3 Edit*4`
- 480,211 tok (cache_aware): `map:? Read Edit*8`
- 785,531 tok (cache_aware): `map:? Read Grep*4 Read Grep*2 Skill Glob Grep Read Grep*3 Read Edit*2`

### newmap
cheapest 3:
- 122,271 tok (dirty_files): `map:find Edit`
- 128,712 tok (dirty_files): `map:find Edit`
- 160,057 tok (dirty_files): `map:refs map:view Edit`
priciest 3:
- 675,780 tok (cache_aware): `map:find map:view Read Skill Grep Read*4 Edit*3`
- 692,488 tok (cache_aware): `map:find map:view Read Skill Edit*6 map:refs*2 map:view Read Bash`
- 765,982 tok (cache_aware): `map:find map:view Skill Grep*2 Read*2 map:refs Edit*7`

## 4. newmap locate-call budget vs required edit sites

cache_aware_savings edits ~4 symbols in one file; dirty_files_cap edits 1 symbol.
Locate calls = map calls before the first Edit.

- cache_aware 20261001T1738: 3 locate (map:find map:refs map:open) -> tok=544,249
- cache_aware 20261001T1818: 2 locate (map:find map:view) -> tok=692,488
- cache_aware 20261001T1912: 4 locate (map:find map:view map:view map:refs) -> tok=546,890
- cache_aware 20261001T1955: 2 locate (map:find map:view) -> tok=271,702
- cache_aware 20261001T2043: 3 locate (map:find map:view map:refs) -> tok=765,982
- cache_aware 20261002T0553: 3 locate (map:find map:view map:find) -> tok=292,292
- cache_aware 20261002T0611: 3 locate (map:find map:view map:find) -> tok=554,355
- cache_aware 20261002T0611: 4 locate (map:find map:view map:view map:find) -> tok=578,385
- cache_aware 20261002T0611: 2 locate (map:find map:view) -> tok=675,780
- dirty_files 20261001T1731: 5 locate (map:find map:around map:refs map:refs map:refs) -> tok=353,116
- dirty_files 20261001T1827: 4 locate (map:find map:refs map:refs map:view) -> tok=254,872
- dirty_files 20261001T1921: 1 locate (map:find) -> tok=122,271
- dirty_files 20261001T2001: 1 locate (map:find) -> tok=128,712
- dirty_files 20261001T2050: 4 locate (map:find map:refs map:refs map:refs) -> tok=221,315
- dirty_files 20261002T0602: 2 locate (map:refs map:view) -> tok=160,057

## 5. Skill-call noise (claude-api pricing lookups)

- mini_v3: 8/19 cells made Skill calls (cache_aware task asks for pricing; inflates tokens equally in both arms)
- newmap: 5/15 cells made Skill calls (cache_aware task asks for pricing; inflates tokens equally in both arms)

