import json
from pathlib import Path
from collections import Counter

base = Path("out/experiments/sdk_mcp_dev_trial/20260808T064743Z")
rows = []
for name in ("context_engine", "graphify"):
    d = json.loads((base / f"{name}-arm.json").read_text(encoding="utf-8"))
    u = d.get("usage") or {}
    mcp = d.get("mcp_call_names") or []
    nat = Counter(d.get("native_tool_names") or [])
    tests = d.get("tests") or {}
    rows.append((name, u, mcp, nat, d.get("work_complete"), d.get("status"), tests.get("passed"), d.get("wall_ms")))

print("=" * 72)
for name, u, mcp, nat, wc, st, tp, wall in rows:
    grep = nat.get("grep", 0)
    print(f"ARM {name}")
    print(f"  work_complete={wc}  status={st}  tests_passed={tp}  wall_ms={wall}")
    print(f"  tokens: total={u.get('total_tokens')}  input={u.get('input_tokens')}  "
          f"output={u.get('output_tokens')}  cache_read={u.get('cache_read_tokens')}")
    print(f"  MCP calls={len(mcp)}  grep={grep}  read={nat.get('read',0)}  "
          f"glob={nat.get('glob',0)}  shell={nat.get('shell',0)}  edit={nat.get('edit',0)}")
    print(f"  MCP breakdown={dict(Counter(mcp))}")
    print()

ce, gf = rows[0][1], rows[1][1]
ct, gt = ce.get("total_tokens") or 0, gf.get("total_tokens") or 0
print(f"context_engine total={ct:,}  graphify total={gt:,}")
print(f"delta (CE - GF) = {ct - gt:,}")
if gt:
    print(f"context_engine is {100 * (ct - gt) / gt:+.1f}% vs graphify")
