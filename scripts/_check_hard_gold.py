import json
from pathlib import Path

from trace_lab.corpus import extract_nodes

root = Path(r"C:\Users\usman\Downloads\context-engine\fixtures\trace-lab")
nodes = extract_nodes(root)
board = json.loads((root / "verify_hard.json").read_text(encoding="utf-8"))
missing = []
for c in board["cases"]:
    refs = [("seed", c["seed"])]
    for key in ("must", "should", "must_not"):
        for r in c.get(key) or []:
            refs.append((key, r))
    for key, r in refs:
        nid = f"{r['file']}::{r['symbol']}"
        if nid not in nodes:
            missing.append((c["id"], key, nid))
print("nodes", len(nodes))
print("missing", len(missing))
for m in missing[:40]:
    print(m)
