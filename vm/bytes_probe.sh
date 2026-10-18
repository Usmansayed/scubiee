#!/usr/bin/env bash
# Measure indexable bytes for repos whose chunk counts we know (sizing the init ETA).
set -u
apt-get -qq update >/dev/null && apt-get -qq install -y git >/dev/null 2>&1
pip install -q $(ls -t /vm/dist/scubiee-*.whl | head -1) >/dev/null 2>&1
for repo in pallets/flask psf/requests pallets/click; do
  name=$(basename $repo)
  git clone -q --depth 1 https://github.com/$repo /work/$name
  python - "$name" <<'EOF'
import sys, time
from pathlib import Path
from pipeline.paths import collect_index_relpaths
root = Path("/work") / sys.argv[1]
t = time.perf_counter()
rels = collect_index_relpaths(root)
walk = time.perf_counter() - t
size = sum((root / r).stat().st_size for r in rels)
lines = sum(sum(1 for _ in (root / r).open("rb")) for r in rels)
print(f"{sys.argv[1]}: files={len(rels)} bytes={size} lines={lines} walk_s={walk:.2f}")
EOF
done
