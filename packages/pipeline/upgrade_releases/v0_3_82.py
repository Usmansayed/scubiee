"""Release 0.3.82 — fix EngineHttp tenacity.retry shadow by ``retry`` param."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.82",
    notes=(
        "Fix EngineHttp.post_json(retry=True): parameter shadowed tenacity.retry "
        "(TypeError bool not callable). Serialize all ORT/DML embeds on a single "
        "worker thread + keepalive tick timeout so map cannot hang behind keepalive."
    ),
)
class Release_0_3_82:
    pass
