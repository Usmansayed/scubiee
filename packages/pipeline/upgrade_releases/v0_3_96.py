"""Release 0.3.96 — uncapped CPU/RAM for DirectML Cursor-open warm."""



from __future__ import annotations



from pipeline.upgrade_registry import release





@release(

    "0.3.96",

    notes=(

        "Remove default 25% JobObject CPU hard-cap and 800 MB soft RSS pin that "

        "starved DirectML/ORT cold load (/health timeout, map unreachable after "

        "Cursor open). CTX_ENGINE_CPU_CAP_PCT=0 (uncapped); soft RSS advisory "

        "CTX_CE_RSS_CAP_MB / CTX_SCUBIEE_TOTAL_RSS_MB=4096. Cap still available "

        "via CTX_ENGINE_CPU_CAP_PCT=1..100 when politeness is needed."

    ),

)

class Release_0_3_96:

    pass


