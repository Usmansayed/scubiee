# Map k=12 vs map k=8 + pack_context

Cases: **20** · wall **29.82s**

**Starting-point winner (symbol→file):** `map8_pack`
**File coverage leader:** `map_k12`

## Means

| Arm | Must-file | Must-symbol | What agent gets |
|-----|-----------|-------------|-----------------|
| map k=12 (raw cards) | 0.863 | 0.25 | file list (symbols usually empty) |
| map k=12 + chunk pick (no pack) | 0.7 | 0.679 | 3 symbol locs, no bodies/chain |
| map k=8 + chunks + **pack_context** | 0.767 | 0.696 | chunks + bodies + call chain |

## Read

- Raw map@12 wins **files** if symbols empty — good neighborhood, not exact funcs.
- Chunk-pick from wider map ≈ chunk-pick from map@8 if top files overlap.
- pack_context wins if it lifts **symbol** recall and/or delivers bodies (exact starting code).

## Per case (sym/file)

- t01 map12=0.75 chunks12=0.25/0.5 pack=0.25/0.5 n=4
- t02 map12=1.0 chunks12=0.333/1.0 pack=0.667/1.0 n=2
- t03 map12=1.0 chunks12=1.0/0.333 pack=1.0/0.333 n=4
- t04 map12=0.667 chunks12=0.0/0.667 pack=0.0/0.667 n=4
- t05 map12=0.5 chunks12=0.0/0.5 pack=0.0/0.5 n=4
- t06 map12=1.0 chunks12=1.0/0.5 pack=1.0/1.0 n=2
- t07 map12=1.0 chunks12=0.5/1.0 pack=0.5/1.0 n=3
- t08 map12=0.5 chunks12=1.0/0.5 pack=1.0/0.5 n=2
- t09 map12=1.0 chunks12=1.0/1.0 pack=1.0/1.0 n=4
- t10 map12=1.0 chunks12=1.0/0.5 pack=1.0/0.5 n=4
- t11 map12=1.0 chunks12=1.0/0.5 pack=1.0/0.5 n=4
- t12 map12=1.0 chunks12=1.0/1.0 pack=1.0/1.0 n=4
- t13 map12=1.0 chunks12=1.0/0.5 pack=1.0/1.0 n=4
- t14 map12=0.667 chunks12=1.0/0.333 pack=1.0/0.667 n=4
- t15 map12=1.0 chunks12=0.0/1.0 pack=0.0/1.0 n=4
- t16 map12=0.667 chunks12=0.5/0.667 pack=0.5/0.667 n=1
- t17 map12=1.0 chunks12=1.0/1.0 pack=1.0/1.0 n=4
- t18 map12=1.0 chunks12=1.0/1.0 pack=1.0/1.0 n=4
- t19 map12=1.0 chunks12=1.0/1.0 pack=1.0/1.0 n=4
- t20 map12=0.5 chunks12=0.0/0.5 pack=0.0/0.5 n=4