"""Release 0.3.105 — expand directions match the graph; map uses the warm daemon."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.105",
    notes=(
        "expand callees keeps direct calls, ranked in the seed file ahead of other "
        "packages. effects returns log/print/send only, or an empty delta. "
        "CLI map searches the warm daemon and keeps hit line spans, and retries "
        "while FastEmbed is still loading inside the ready budget."
    ),
)
def v0_3_105() -> None:
    return None
