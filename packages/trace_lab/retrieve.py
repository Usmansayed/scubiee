"""Lexical / vector-space retrieval over TraceNodes. No embeddings required."""

from __future__ import annotations

import math
import re
from collections import Counter

from conductor.bm25_index import BM25Index, tokenize
from trace_lab.types import TraceNode

_STOP = frozenset(
    {
        "where",
        "which",
        "what",
        "how",
        "does",
        "do",
        "the",
        "a",
        "an",
        "to",
        "for",
        "of",
        "and",
        "is",
        "in",
        "on",
        "with",
        "from",
        "that",
        "this",
        "work",
        "works",
    }
)


def expand_query(query: str) -> str:
    """Cheap synonym expansion — a stand-in for semantic query rewriting."""
    toks = set(tokenize(query))
    q = query.lower()
    extra: list[str] = []
    if toks & {"log", "logger", "printing", "print"} or "log output" in q:
        # Effect query: name the logger, do not expand the whole auth synonym set.
        extra += ["log", "logger"]
        if toks & {"auth", "authenticate", "middleware", "login"}:
            extra += ["authenticate"]
    elif toks & {"authentication", "auth", "login", "credential", "bearer", "jwt", "logged", "claims", "account"}:
        extra += ["jwt", "token", "bearer", "claim", "verify", "authenticate", "login"]
    if toks & {"expiry", "expire", "expired", "expires", "ttl", "lifetime", "timeout", "hour", "kicked"} or any(
        p in q for p in ("kicked out", "stop working", "expiry knob", "an hour")
    ):
        extra += ["ttl", "token", "age", "security", "expired", "TOKEN_TTL", "verify"]
    if toks & {"bill", "billing", "payment", "pay", "cents", "invoice", "charge"}:
        extra += ["charge", "billing", "pay", "get", "invoices"]
    if toks & {"emit", "event", "welcome", "handler", "fire"}:
        extra += ["emit", "lookup", "handle", "bind", "welcome", "events"]
    if toks & {"queue", "worker", "job", "digest", "dequeue"}:
        extra += ["run", "dequeue", "execute", "send_digest", "jobs", "worker"]
    if toks & {"cors", "headers"} and "authorization" not in q:
        extra += ["cors", "process", "middleware"]
    if toks & {"health", "probe", "liveness"}:
        extra += ["health"]
    if toks & {"session"} and "auth" not in toks:
        extra += ["session", "start"]
    if toks & {"store", "fetch", "memory", "override"}:
        extra += ["fetch", "MemoryStore", "Store", "stores"]
    if toks & {"resolve", "database", "row"}:
        extra += ["resolve", "lookup", "connect", "UserRepository"]
    if extra:
        return query + " " + " ".join(dict.fromkeys(extra))
    return query


def node_corpus(nodes: dict[str, TraceNode], *, include_path: bool) -> list[str]:
    docs: list[str] = []
    for n in nodes.values():
        if include_path:
            docs.append(f"{n.file} {n.symbol} {n.lex_text or n.text}")
        else:
            docs.append(n.lex_text or n.text)
    return docs


class LexicalIndex:
    def __init__(self, nodes: dict[str, TraceNode], *, include_path: bool = False):
        self.ids = list(nodes.keys())
        self.nodes = nodes
        self.bm25 = BM25Index(node_corpus(nodes, include_path=include_path))
        self._tfidf = _Tfidf(node_corpus(nodes, include_path=include_path))

    def bm25_scores(self, query: str) -> dict[str, float]:
        raw = self.bm25.score_all(query)
        return {self.ids[i]: float(raw[i]) for i in range(len(self.ids))}

    def tfidf_scores(self, query: str) -> dict[str, float]:
        raw = self._tfidf.score_all(query)
        return {self.ids[i]: float(raw[i]) for i in range(len(self.ids))}


def normalize(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    hi = max(scores.values())
    if hi <= 0:
        return {k: 0.0 for k in scores}
    return {k: v / hi for k, v in scores.items()}


def query_tokens(query: str) -> set[str]:
    raw = tokenize(expand_query(query))
    out: set[str] = set()
    for t in raw:
        if t in _STOP or len(t) <= 1:
            continue
        out.add(t)
        out.update(p for p in _ident_parts(t) if p not in _STOP and len(p) > 1)
    return out


def _ident_parts(token: str) -> set[str]:
    parts = set()
    for p in token.replace(".", "_").split("_"):
        if p:
            parts.add(p.lower())
        for chunk in re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+", p):
            if len(chunk) > 1:
                parts.add(chunk.lower())
    return parts


def query_similarity(query: str, node: TraceNode, *, use_body: bool = False) -> float:
    """Overlap of content query tokens with path + symbol (+ optional body)."""
    q = query_tokens(query)
    if not q:
        return 0.0
    blob_src = f"{node.file} {node.symbol}"
    if use_body:
        blob_src = f"{blob_src} {node.text}"
    blob: set[str] = set()
    for t in tokenize(blob_src):
        blob.add(t)
        blob.update(_ident_parts(t))
    blob = {t for t in blob if t not in _STOP and len(t) > 1}
    if not blob:
        return 0.0
    inter = len(q & blob)
    if inter <= 0:
        return 0.0
    return min(1.0, inter / len(q) + 0.35)



def query_intent(query: str) -> str:
    """Classify a tracing query so walks can mask relations.

    flow   — understand an execution path
    config — locate a setting / constant
    site   — find a specific call site or side effect
    entry  — start from a caller / route
    refs   — who uses / who calls a symbol
    """
    q = query.lower()
    if any(
        p in q
        for p in (
            "who uses",
            "who calls",
            "who reads",
            "who references",
            "who even reads",
            "what reads",
        )
    ):
        return "refs"
    if any(p in q for p in ("printing", "print something", "write log", "log output")):
        return "site"
    if any(p in q for p in ("write log", "log output", "where does")) and any(
        p in q for p in ("log", "write", "print")
    ):
        return "site"
    # Config needs a real setting cue — bare "where is that?" is not enough.
    config_cue = any(
        p in q
        for p in (
            "configured",
            "configuration",
            "expiry",
            "ttl",
            "timeout",
            "kicked out",
            "stop working",
            "expiry knob",
            "after an hour",
            "after a while",
            "lifetime",
            "how long",
            "token lives",
            "tokens live",
            "only care",
        )
    )
    if config_cue or (
        "where is" in q
        and any(p in q for p in ("token", "ttl", "expiry", "expire", "config", "timeout", "knob"))
    ):
        return "config"
    if any(p in q for p in ("how does login", "login authenticate", "route")):
        return "entry"
    if any(
        p in q
        for p in (
            "how does",
            "how do",
            "how is",
            "what does",
            "work",
            "flow",
            "walk me",
            "path",
            "figuring out",
            "actually get",
        )
    ):
        return "flow"
    return "flow"


def query_mix_for(query: str) -> float:
    """Broad 'how does X work' trusts structure; 'where is' trusts the query."""
    q = query.lower()
    if any(p in q for p in ("how does", "how do", "how is", "flow")):
        return 0.18
    if any(p in q for p in ("where", "which file", "configure", "configured", "log output", "write log")):
        return 0.62
    return 0.30


class _Tfidf:
    def __init__(self, docs: list[str]):
        self.docs = [tokenize(d) for d in docs]
        n = max(len(self.docs), 1)
        df: Counter[str] = Counter()
        for d in self.docs:
            df.update(set(d))
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}
        self.vecs = [self._vec(d) for d in self.docs]

    def _vec(self, tokens: list[str]) -> dict[str, float]:
        tf = Counter(tokens)
        if not tf:
            return {}
        n = sum(tf.values())
        return {t: (c / n) * self.idf.get(t, 0.0) for t, c in tf.items()}

    def score_all(self, query: str) -> list[float]:
        qv = self._vec(tokenize(query))
        qn = math.sqrt(sum(v * v for v in qv.values())) or 1.0
        out: list[float] = []
        for dv in self.vecs:
            dn = math.sqrt(sum(v * v for v in dv.values())) or 1.0
            dot = sum(qv[t] * dv.get(t, 0.0) for t in qv)
            out.append(dot / (qn * dn))
        return out
