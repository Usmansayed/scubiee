"""Per-version upgrade release template.

Copy to ``vX_Y_Z.py`` and register steps for the new package version.
"""

from __future__ import annotations

from pipeline.upgrade_registry import (
    migrate_component,
    preserve_component,
    release,
    reinstall_component,
    update_component,
)

# Example step declarations — delete or edit for your release.
# MCP_PINS = update_component("mcp_pins", reason="...", pin_format=2)
# GATE_RULES = preserve_component("gate_rules")
# INDEX_SCHEMA = migrate_component("index_schema", reason="...")
# EMBEDDINGS = reinstall_component("embeddings", reason="new embed model")
# ACCEL = preserve_component("accel")
# HOME_LAYOUT = preserve_component("home_layout")
# DAEMON = reinstall_component("daemon", reason="restart on new package")


@release("0.0.0", notes="TEMPLATE — replace version and steps before shipping")
class ReleaseTemplate:
    """Only components listed here are touched; everything else is preserved."""

    pass
