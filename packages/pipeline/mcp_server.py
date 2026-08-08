"""Backward-compat entry: ``python -m pipeline mcp`` → session-native locate MCP.

The one shipped Context Engine MCP is ``pipeline.mcp_locate``
(search / read / status). This module exists so older ``pipeline mcp``
invocations still land on that surface.
"""

from __future__ import annotations

from pipeline.mcp_locate import create_mcp, main

__all__ = ["create_mcp", "main"]


if __name__ == "__main__":
    main()
