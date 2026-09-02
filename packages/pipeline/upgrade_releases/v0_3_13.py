"""Release 0.3.13 — Windows stop reliability, terminal UX, pre-prod hardening."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release("0.3.13", notes="Windows stop exit-15 fix; colorama terminal UX; doctor install identity")
class Release_0_3_13:
    pass
