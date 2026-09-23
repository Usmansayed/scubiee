"""Release 0.3.109 — leftover pip copies actually uninstall."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.109",
    notes=(
        "pip uninstall of an older conda copy no longer inherits PYTHONPATH "
        "from the uv tool, which made pip remove the tool copy and report "
        "success while the conda package stayed installed. If the package "
        "is still importable after pip, its dist-info RECORD is removed "
        "inside that prefix."
    ),
)
def v0_3_109() -> None:
    return None
