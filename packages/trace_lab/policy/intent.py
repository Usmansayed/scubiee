"""Query intent + exclude sets from user paragraph only (not seed code)."""

from __future__ import annotations

from dataclasses import dataclass, field

from conductor.bm25_index import tokenize
from trace_lab.retrieve import query_intent as _legacy_intent


@dataclass
class TraceSpec:
    mode: str  # flow|config|refs|site|entry
    user_query: str
    exclude_names: set[str] = field(default_factory=set)
    include_names: set[str] = field(default_factory=set)
    hop_cap: int = 6


_EXCLUDE_MARKERS = (
    ("no telemetry", {"track", "analytics", "metric", "metrics", "log", "logger"}),
    ("without telemetry", {"track", "analytics", "metric", "metrics", "log", "logger"}),
    ("telemetry noise", {"track", "analytics", "metric", "metrics", "log", "logger"}),
    ("no logging", {"log", "logger", "info", "debug", "warn", "error"}),
    ("without logging", {"log", "logger"}),
    ("no side effect", {"log", "logger", "track", "analytics"}),
    ("without side effect", {"log", "logger", "track"}),
    ("side effects", {"log", "logger", "track", "analytics", "charge", "send", "mailer"}),
    ("pricing only", {"charge", "pay", "payment", "mailer", "send", "schedule"}),
    ("pricing-only", {"charge", "pay", "payment", "mailer", "send", "schedule"}),
    ("ok-logging", {"log", "logger"}),
)


def parse_trace_spec(user_query: str) -> TraceSpec:
    """Build TraceSpec from the user paragraph alone."""
    q = (user_query or "").strip()
    ql = q.lower()
    mode = _legacy_intent(q)
    flow_cues = {
        "auth",
        "authenticate",
        "jwt",
        "token",
        "login",
        "checkout",
        "payment",
        "webhook",
        "search",
        "job",
        "worker",
        "flow",
        "verify",
        "decode",
        "credential",
        "bearer",
        "middleware",
    }
    toks = set(tokenize(ql))
    if mode == "config" and (
        toks & flow_cues
        or any(c in ql for c in ("how does", "full path", "starting from"))
    ):
        mode = "flow"
    if "only care" in ql and mode == "config":
        mode = "flow"

    excludes: set[str] = set()
    for marker, names in _EXCLUDE_MARKERS:
        if marker in ql:
            excludes |= names
    if "pricing" in ql and ("only" in ql or "slice" in ql or "focus" in ql):
        excludes |= {"charge", "pay", "payment", "mailer", "send", "schedule"}
    # Natural-language exclude / out-of-scope cues
    if "do not pull" in ql or "don't pull" in ql:
        excludes |= {"log", "logger", "track", "analytics", "charge", "send", "mailer", "billing"}
    if "exclude" in ql:
        if toks & {"log", "logging", "logger"} or "ok-logging" in ql:
            excludes |= {"log", "logger"}
        if toks & {"analytics", "tracking", "track"}:
            excludes |= {"track", "analytics"}
    if "orchestration" in ql and ("out" in ql or "keep" in ql or "unless" in ql):
        excludes |= {
            "charge",
            "pay",
            "payment",
            "begin",
            "validate",
            "schedule",
            "send",
            "mailer",
            "reserve",
        }
    if "credential" in ql and ("only" in ql or "only care" in ql or "path" in ql):
        excludes |= {"log", "logger", "track", "analytics", "charge", "send"}

    hop = {"refs": 1, "site": 2, "config": 3, "entry": 4, "flow": 6}.get(mode, 6)
    return TraceSpec(mode=mode, user_query=q, exclude_names=excludes, hop_cap=hop)
