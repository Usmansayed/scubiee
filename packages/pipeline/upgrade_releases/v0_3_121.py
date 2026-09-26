"""Release 0.3.121 — sync request returns, small edits publish."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.121",
    notes=(
        "POST /v1/sync no longer walks newcomers or embeds on the request "
        "thread; it returns deferred within the capacity wait. The change "
        "poll still checks indexed files while an MCP client is connected. "
        "A one-file edit syncs during a locate streak. pack and expand reject "
        "k<1 before the AST warm gate. A second collect names already_packed."
    ),
)
def v0_3_121() -> None:
    return None
