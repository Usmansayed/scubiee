#!/usr/bin/env bash
# Live check: a plain `uv tool install` must not be reported as two installs.
#   powershell -File vm\run.ps1 install_identity_check.sh
set -u
export PATH="$HOME/.local/bin:$PATH"
pip install -q uv >/dev/null 2>&1
uv tool install -q $(ls -t /vm/dist/scubiee-*.whl | head -1) >/dev/null 2>&1
echo "== which: $(command -v scubiee) -> $(readlink -f "$(command -v scubiee)")"
TOOL_PY="$(dirname "$(readlink -f "$(command -v scubiee)")")/python"
echo "== setup warning (empty = none):"
"$TOOL_PY" -c "from pipeline.env_guard import warn_extra_scubiee; warn_extra_scubiee()"
echo "== install identity:"
"$TOOL_PY" -c "import json; from pipeline.env_guard import install_identity_report as r; print(json.dumps(r(), indent=1))"
echo "== doctor:"
mkdir -p /work/x && cd /work/x && git init -q 2>/dev/null
scubiee doctor . > /tmp/doctor.json 2>/dev/null; echo "doctor rc=$?"
python3 -c "import json; d=json.load(open('/tmp/doctor.json')); print('ok =', d.get('ok')); print('install =', json.dumps(d.get('install'), indent=1)); print('issues =', d.get('issues')); print('failing =', [k for k,v in d.items() if isinstance(v, dict) and v.get('ok') is False]); print('top keys =', list(d))"
