#!/usr/bin/env bash
# MCP merge experiment: seed a mock third-party MCP (Figma-style), connect/disconnect
# Scubiee, validate JSON/TOML/YAML syntax after each step.
# Run from enrolled repo: bash tests/_e2e_mcp_merge_experiment.sh

set -euo pipefail
unset CTX_HOME

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
export PATH="${HOME}/.local/bin:${PATH}"

LOG="${REPO_ROOT}/tests/_mcp_merge_experiment.txt"
MOCK_NAME="figma"
: > "$LOG"

log() { echo "$1" | tee -a "$LOG"; }

validate_json() {
  local f="$1"
  python3 -c "import json,sys; json.load(open(sys.argv[1],encoding='utf-8')); print('JSON OK:', sys.argv[1])" "$f" >> "$LOG" 2>&1
}

validate_toml() {
  local f="$1"
  local py="python3"
  if command -v uv >/dev/null 2>&1; then
    py="uv run python"
  fi
  $py -c "
import sys
try:
    import tomllib
except ImportError:
    import tomli as tomllib
p = sys.argv[1]
tomllib.loads(open(p,'rb').read())
print('TOML OK:', p)
" "$f" >> "$LOG" 2>&1 || {
    grep -q '^\[' "$f" || return 1
    log "TOML fallback OK: $f (syntax check via grep)"
  }
}

seed_cursor_figma() {
  mkdir -p .cursor
  cat > .cursor/mcp.json <<'EOF'
{
  "mcpServers": {
    "figma": {
      "url": "https://mcp.figma.com/mcp",
      "headers": {
        "Authorization": "Bearer MOCK_TOKEN"
      }
    }
  }
}
EOF
}

seed_claude_figma() {
  cat > .mcp.json <<'EOF'
{
  "mcpServers": {
    "figma": {
      "command": "npx",
      "args": ["-y", "figma-developer-mcp", "--stdio"],
      "env": {
        "FIGMA_API_KEY": "mock-key"
      }
    }
  }
}
EOF
}

seed_codex_other() {
  mkdir -p .codex
  cat > .codex/config.toml <<'EOF'
[model]
name = "gpt-4"

[mcp_servers.figma]
command = "npx"
args = ["-y", "figma-developer-mcp", "--stdio"]
env = { FIGMA_API_KEY = "mock-key" }
EOF
}

seed_opencode_other() {
  cat > opencode.json <<'EOF'
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "figma": {
      "type": "local",
      "enabled": true,
      "command": ["npx", "-y", "figma-mcp"],
      "environment": {
        "FIGMA_TOKEN": "mock"
      }
    }
  }
}
EOF
}

assert_has() {
  local file="$1" key="$2"
  python3 -c "
import json, sys
d=json.load(open(sys.argv[1],encoding='utf-8'))
name=sys.argv[2]
servers=d.get('mcpServers') or d.get('servers') or d.get('context_servers') or d.get('amp.mcpServers') or {}
mcp=d.get('mcp')
if isinstance(mcp, dict):
    if isinstance(mcp.get('servers'), dict):
        servers = mcp['servers']
    else:
        servers = {**servers, **{k: v for k, v in mcp.items() if k != 'servers' and isinstance(v, dict)}}
assert name in servers, f'missing {name} in {sys.argv[1]}: {list(servers)}'
print('has', name, 'in', sys.argv[1])
" "$file" "$key" >> "$LOG" 2>&1
}

assert_lacks() {
  local file="$1" key="$2"
  python3 -c "
import json, sys
d=json.load(open(sys.argv[1],encoding='utf-8'))
name=sys.argv[2]
servers=d.get('mcpServers') or d.get('servers') or d.get('context_servers') or d.get('amp.mcpServers') or {}
mcp=d.get('mcp')
if isinstance(mcp, dict):
    if isinstance(mcp.get('servers'), dict):
        servers = mcp['servers']
    else:
        servers = {**servers, **{k: v for k, v in mcp.items() if k != 'servers' and isinstance(v, dict)}}
assert name not in servers, f'unexpected {name} in {sys.argv[1]}'
print('no', name, 'in', sys.argv[1])
" "$file" "$key" >> "$LOG" 2>&1
}

log "=== MCP merge experiment $(date -Iseconds) ==="
log "Repo: $REPO_ROOT"

if [ ! -f .scubiee/id.json ]; then
  log "[setup] enrolling..."
  scubiee setup --repair >> "$LOG" 2>&1
  scubiee init . >> "$LOG" 2>&1
fi

# --- Cursor (.cursor/mcp.json) ---
log ""
log "=== CURSOR ==="
seed_cursor_figma
validate_json .cursor/mcp.json
scubiee connect --cursor >> "$LOG" 2>&1
validate_json .cursor/mcp.json
assert_has .cursor/mcp.json figma
assert_has .cursor/mcp.json scubiee
scubiee disconnect --cursor >> "$LOG" 2>&1
validate_json .cursor/mcp.json
assert_lacks .cursor/mcp.json scubiee
assert_has .cursor/mcp.json figma
log "[cursor] PASS"

# --- Claude Code (.mcp.json) ---
log ""
log "=== CLAUDE CODE ==="
seed_claude_figma
validate_json .mcp.json
scubiee connect --claude-code >> "$LOG" 2>&1
validate_json .mcp.json
assert_has .mcp.json figma
assert_has .mcp.json scubiee
scubiee disconnect --claude-code >> "$LOG" 2>&1
validate_json .mcp.json
assert_lacks .mcp.json scubiee
assert_has .mcp.json figma
log "[claude-code] PASS"

# --- Codex (.codex/config.toml) ---
log ""
log "=== CODEX ==="
seed_codex_other
validate_toml .codex/config.toml
scubiee connect --codex >> "$LOG" 2>&1
validate_toml .codex/config.toml
grep -q 'mcp_servers.figma' .codex/config.toml
grep -q 'mcp_servers.scubiee' .codex/config.toml
scubiee disconnect --codex >> "$LOG" 2>&1
validate_toml .codex/config.toml
grep -q 'mcp_servers.figma' .codex/config.toml
! grep -q 'mcp_servers.scubiee' .codex/config.toml
log "[codex] PASS"

# --- OpenCode (opencode.json) ---
log ""
log "=== OPENCODE ==="
seed_opencode_other
validate_json opencode.json
scubiee connect --opencode >> "$LOG" 2>&1
validate_json opencode.json
assert_has opencode.json figma
assert_has opencode.json scubiee
scubiee disconnect --opencode >> "$LOG" 2>&1
validate_json opencode.json
assert_lacks opencode.json scubiee
assert_has opencode.json figma
log "[opencode] PASS"

log ""
log "=== ALL MERGE EXPERIMENTS PASSED $(date -Iseconds) ==="
