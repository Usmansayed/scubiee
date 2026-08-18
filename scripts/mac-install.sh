#!/usr/bin/env bash
# Reliable Mac install when npm/PyPI are unavailable or PEP 668 blocks global pip.
set -euo pipefail

VENV="${CTX_VENV:-$HOME/.context-engine/venv}"
REPO="${CTX_GIT_ORIGIN:-https://github.com/Usmansayed/new-context-engine.git}"
TAG="${CTX_VERSION:-v0.2.5}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Install Python 3.10+ first: brew install python@3.12" >&2
  exit 1
fi

python3 -m venv "$VENV"
# shellcheck disable=SC1090
source "$VENV/bin/activate"
python -m pip install --upgrade pip
python -m pip install "scubiee[coreml] @ git+${REPO}@${TAG}"
python -m pipeline setup

echo ""
echo "Add to ~/.zshrc:"
echo "  export PATH=\"$VENV/bin:\$PATH\""
echo ""
echo "Then: ctx init /path/to/your/repo && ctx engine ensure /path/to/your/repo"
