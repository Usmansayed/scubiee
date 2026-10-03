"""Backward-compat entry: ``scubiee-mcp`` / ``python -m pipeline mcp`` → Map V3.

The one shipped Scubiee MCP map server is now ``pipeline.map_v3_server``
(one ``map`` tool with configs find|focus|related|graph, plus gate|status).
This module exists so the ``scubiee-mcp`` console script and older
``pipeline mcp`` invocations still land on the shipped server.
"""

from __future__ import annotations

from pipeline.map_v3_server import main

__all__ = ["main"]


if __name__ == "__main__":
    main()
