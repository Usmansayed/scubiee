"""Release 0.3.58 — same D_channel_best ranking, inverted BM25 + no rescan."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release("0.3.58", notes="Same D_channel_best scores via inverted BM25; skip duplicate search(); reuse channel pool")
class Release_0_3_58:
    pass
