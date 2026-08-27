"""Product branding constants — Scubiee only (no legacy aliases)."""

from __future__ import annotations

from pathlib import Path

# MCP server key in mcp.json / connect
MCP_SERVER_NAME = "scubiee"
MCP_SERVER_NAMES: tuple[str, ...] = (MCP_SERVER_NAME,)

# On-disk data directories
DATA_DIR_NAME = ".scubiee"
DATA_DIR_NAMES: tuple[str, ...] = (DATA_DIR_NAME,)

# Rule section markers
MARKER_START = "<!-- scubiee:start -->"
MARKER_END = "<!-- scubiee:end -->"

CONTINUE_YAML_MARKER = "# scubiee"

LOG_PREFIX = "[scubiee]"


def strip_legacy_mcp_keys(servers: dict) -> bool:
    """No-op kept for call-site compatibility (no legacy keys anymore)."""
    return False


def migrate_home_dir(home: Path | None = None) -> Path:
    """Return the Scubiee home directory ``~/.scubiee`` (or ``$CTX_HOME``)."""
    base = home or Path.home()
    return (base / DATA_DIR_NAME).resolve()


def resolve_repo_data_dir(root: Path) -> Path:
    """Repo-local data directory ``<repo>/.scubiee``."""
    return root.resolve() / DATA_DIR_NAME
