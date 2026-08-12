# Trial log extract — ce_search vs ce_nav (20260810T214438Z)

Raw counts mined from `*-arm.json` / conversation blobs for the search-vs-read decision.

## ce_search

```
work_tokens=3096363  complete=True  quality=True  wall_s≈452.9
tool_calls=473  first_edit_idx=178

by tool:
  146  native:edit
  133  native:read
   69  native:grep
   60  mcp:search
   24  native:shell
   21  native:glob
   20  native:updateTodos

pre-first-edit:
  72 native:read, 40 mcp:search, 32 native:grep, 14 native:glob, …

mcp search: 60 calls / 20 unique queries
mcp read: 0
unchanged/already_in_session markers: 0
```

## ce_nav

```
work_tokens=7807353  complete=True  quality=True  wall_s≈736.4
tool_calls=568  first_edit_idx=238

by tool:
  312  mcp:read
  133  native:edit
   33  mcp:files
   24  mcp:search
   24  native:shell
   21  mcp:expand
   18  native:updateTodos
    3  mcp:recall

pre-first-edit:
  180 mcp:read, 22 mcp:files, 16 mcp:search, 12 mcp:expand, …

mcp search: 24 calls / 8 unique queries
mcp read: 312 calls / 40 unique targets / 272 duplicates
unchanged/already_in_session markers: ≈89
thrash_blocked: 1

top duplicate mcp:read targets:
  dispatch_registry.py ×36
  tools.py ×21
  handlers.py ×21
  coordination_intelligence/service.py ×18
  agent_guidance.py ×15
  AGENT_GUIDE.md ×15
  executor.py ×15
  tool_catalog.py ×12
```

## Delta

- work_tokens: nav − search = **+4,711,000** (~**+152%** vs search)
- first_edit: nav later by **60** steps
- both: work_complete + quality_pass, cross_arm_contamination=[]
