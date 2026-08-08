"""MCP: context_engine_mcp — session-native code context, switchable surfaces.

Surface is chosen by env ``CTX_MCP_SURFACE``; every surface starts from one
semantic ``search``:

  read  (default): search | read | status
    read folds focus/expand/recall — budgeted, session-deduped span fetch with
    optional 1-hop graph neighbors.

  graph: search | neighbors | graph | status
    two tiny graphify-style tools: neighbors (1-hop callers/callees) and graph
    (NL structural/relationship query).

  rich: search | grep | usages | read | expand | outline | neighbors | graph |
        imports | status
    one specialized tool per use-case, each flexible — the "many perfect tools"
    surface.

  search: search | status
    just the one semantic tool, leaned on hard via docs + encouragement.

Data-backed from ~200 TraceLab sessions: locate+read are ~46% of agent tool
calls and native read/grep dominate the rest — so tools must cover semantic-find
(search), exact-find (grep/usages), span-read (read/expand), file shape
(outline), dependencies (imports) and the graph (neighbors/graph).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "packages") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages"))

try:
    from mcp.server.fastmcp import FastMCP
except Exception:  # pragma: no cover
    FastMCP = None  # type: ignore

try:
    from pydantic import BaseModel, ConfigDict, Field, ValidationError
except Exception:  # pragma: no cover
    BaseModel = object  # type: ignore
    ConfigDict = dict  # type: ignore
    Field = lambda *a, **k: None  # type: ignore
    ValidationError = Exception  # type: ignore


_SURFACES = {"read", "graph", "rich", "search", "grep"}


def _active_surface() -> str:
    val = (os.environ.get("CTX_MCP_SURFACE") or "read").strip().lower()
    if val in {"graphify"}:
        return "graph"
    return val if val in _SURFACES else "read"


# ---- server instructions (per surface) -------------------------------------

SERVER_INSTRUCTIONS_READ = """\
Context Engine = code-context tools. When you need to FIND or UNDERSTAND code —
especially on a new/vague/unfamiliar task — reach for these FIRST. For
meaning-based lookups they are faster/cheaper than Grep/Read sweeps. Grep is a
fallback, not the opening move.

THREE TOOLS, WHEN TO USE WHICH:
  - New / vague / "where does X happen"        -> search(query, k, fetch)  [START HERE]
  - Open/understand a specific thing to edit   -> read(target, neighbors, max_chars)
  - Health / which tools exist                 -> status()

search: semantic (embeddings + BM25 + graph). read: get the RIGHT span once,
session-deduped (re-reading returns an "unchanged" stub), neighbors=true adds
1-hop callers/callees. Don't lead with a blind Grep/Glob. Shell for tests/build/
git is expected. Leave budgets at default (CTX_TOKEN_MODE=savings).
"""

SERVER_INSTRUCTIONS_GRAPH = """\
Context Engine = code-context tools. Reach for these FIRST on new/vague tasks;
they beat Grep/Read sweeps for meaning and structure.

  - New / vague / "where does X happen"        -> search(query, k, fetch)  [START HERE]
  - "what calls / uses / imports X"            -> neighbors(target)        [the graph]
  - "how does X connect to Y / what's related" -> graph(question)          [the graph]
  - Health / which tools exist                 -> status()

Prefer search for meaning, neighbors for usages, graph for relationships. Open a
file with your native reader only after these point you at the right span. Don't
open with a blind Grep/Glob. Shell for tests/build/git is expected.
"""

SERVER_INSTRUCTIONS_RICH = """\
Context Engine = a full code-context toolkit. Reach for these FIRST on any
find/understand task — they are faster/cheaper than Grep/Read sweeps and each is
built for one job. Grep/native-read are a fallback, not the opening move.

PICK THE RIGHT TOOL:
  - Meaning / "where does X happen"        -> search(query, k, fetch)   [START HERE]
  - Exact string / literal / regex         -> grep(pattern, glob)
  - Every use of a symbol (call sites)     -> usages(symbol)
  - Open a specific span to edit           -> read(target|path, neighbors)
  - Re-open a span you already saw         -> expand(handle)
  - A file's structure (defs/classes)      -> outline(path)
  - Callers / callees (1-hop graph)        -> neighbors(target)
  - "how does X connect to Y" (structure)  -> graph(question)
  - What a file depends on / imports       -> imports(path)
  - Health / which tools exist             -> status()

read is session-deduped (re-reading a span returns an "unchanged" stub). Use
grep/usages instead of native grep; use read/outline instead of native full-file
reads. Shell for tests/build/git is expected. Budgets default (savings mode).
"""

SERVER_INSTRUCTIONS_SEARCH = """\
Context Engine = ONE semantic code search. Use it FIRST and OFTEN — it is the
fast way to find code by meaning (embeddings + BM25 + graph, fused), and it beats
grepping or reading files blind.

  search(query, k, fetch): k = how many hits (r5=5, r10=10). fetch=true inlines
  the code body so you usually don't need a separate read step.

Reach for search on every new/vague/"where is X" question. Widen k or sharpen the
query if thin. Only drop to native Grep/Read for an exact string or once search
truly comes up empty — and say so briefly. Shell for tests/build/git is expected.
"""


SERVER_INSTRUCTIONS_GREP = """\
Context Engine here = ONE tool: `grep` — fast, exact/literal (regex) text search
over the repo. Use it whenever you need a precise string: an import line, a
config key, a function name, a specific token.

  grep(pattern, glob, max_hits): RETURNS hits[{file,line,text}].

Reach for grep instead of shelling out to a native grep — it is scoped to the
indexed repo and returns tidy hits. For meaning-based / "where does X happen"
discovery, use your other tools; grep is for exact matches. Shell for tests/
build/git is expected.
"""


def _server_instructions(surface: str) -> str:
    return {
        "graph": SERVER_INSTRUCTIONS_GRAPH,
        "rich": SERVER_INSTRUCTIONS_RICH,
        "search": SERVER_INSTRUCTIONS_SEARCH,
        "grep": SERVER_INSTRUCTIONS_GREP,
    }.get(surface, SERVER_INSTRUCTIONS_READ)


# Back-compat alias (imported by some tests/tools).
SERVER_INSTRUCTIONS = SERVER_INSTRUCTIONS_READ


def _stderr(*args, **kwargs) -> None:
    kwargs.setdefault("file", sys.stderr)
    kwargs.setdefault("flush", True)
    print(*args, **kwargs)


def _default_repo() -> Path:
    env = os.environ.get("CTX_REPO") or os.environ.get("CONTEXT_ENGINE_REPO")
    if env:
        return Path(env).resolve()
    return Path.cwd().resolve()


def _dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str)


def _err(tool: str, error: str, *, hint: str = "", **extra: Any) -> str:
    payload: dict[str, Any] = {"ok": False, "tool": tool, "error": error, **extra}
    if hint:
        payload["hint"] = hint
    return _dumps(payload)


def _looks_like_path(s: str) -> bool:
    s = (s or "").strip()
    if not s or " " in s:
        return False
    return "/" in s or s.endswith(
        (".py", ".ts", ".tsx", ".js", ".md", ".json", ".toml", ".cfg", ".txt")
    )


def _slim_spans(spans: list[dict[str, Any]], *, keep: int, body_chars: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in (spans or [])[:keep]:
        out.append(
            {
                "file": s.get("path") or s.get("file"),
                "start_line": s.get("start_line"),
                "end_line": s.get("end_line"),
                "why": (s.get("why") or s.get("label") or "")[:120],
                "code": (s.get("text") or s.get("excerpt") or "")[:body_chars],
            }
        )
    return out


def _slim_grep(hits: Any, *, keep: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for h in (hits if isinstance(hits, list) else [])[:keep]:
        if isinstance(h, dict):
            out.append(
                {
                    "file": h.get("file") or h.get("path"),
                    "line": h.get("line") or h.get("start_line"),
                    "text": (h.get("text") or h.get("preview") or "")[:160],
                }
            )
    return out


def _slim_outline(symbols: Any, *, keep: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in (symbols if isinstance(symbols, list) else [])[:keep]:
        if isinstance(s, dict):
            out.append(
                {
                    "name": s.get("name") or s.get("symbol") or s.get("label"),
                    "kind": s.get("kind") or s.get("type"),
                    "start_line": s.get("start_line") or s.get("line"),
                    "end_line": s.get("end_line"),
                }
            )
        else:
            out.append({"name": str(s)})
    return out


def _resolve_to_file(repo: Path, target: str) -> str:
    """Best-effort: a path stays a path; a symbol/phrase resolves via search."""
    t = (target or "").strip()
    if not t:
        return ""
    if _looks_like_path(t):
        return t.replace("\\", "/")
    try:
        from pipeline.locate import _search_hits

        hits = _search_hits(repo, t, top_k=1)
        if hits:
            return str(hits[0].get("file") or "")
    except Exception:  # noqa: BLE001
        pass
    return ""


def _resolve_span_in_path(repo: Path, path_n: str, query: str) -> tuple[int, int]:
    if not query:
        return 0, 0
    try:
        from pipeline.locate import _search_hits

        for h in _search_hits(repo, query, top_k=24):
            hf = str(h.get("file") or "").replace("\\", "/")
            if hf == path_n or hf.endswith("/" + path_n) or path_n.endswith(hf):
                s = int(h.get("start_line") or 0)
                if s:
                    return s, int(h.get("end_line") or 0)
    except Exception:  # noqa: BLE001
        pass
    return 0, 0


def _client_for(repo: Path):
    from pipeline.client import EngineClient
    from pipeline.daemon import ensure_daemon

    ensure_daemon(repo, force_if_hung=False)
    return EngineClient()


# ---- arg models ------------------------------------------------------------

class SearchArgs(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(..., min_length=1, max_length=2000, description="NL or symbol query.")
    k: int = Field(8, ge=1, le=25, description="How many hits (r5=5, r10=10).")
    fetch: bool = Field(False, description="Inline each hit's code body (bounded).")
    max_chars: int = Field(1200, ge=200, le=6000, description="Per-hit body budget when fetch.")
    response_format: Literal["json", "markdown"] = Field("json", description="json|markdown")


class ReadArgs(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    target: str = Field("", max_length=512, description="Symbol / phrase / 'path' / 'path:line'.")
    path: str = Field("", max_length=512, description="Explicit repo-relative file.")
    query: str = Field("", max_length=2000, description="When path= set, pick the span for this.")
    handle: str = Field("", max_length=64, description="Re-materialize a prior span handle.")
    neighbors: bool = Field(False, description="Add capped 1-hop callers/callees.")
    max_chars: int = Field(2000, ge=200, le=12000, description="Body budget for the span.")
    response_format: Literal["json", "markdown"] = Field("json", description="json|markdown")


class ExpandArgs(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    handle: str = Field(..., min_length=3, max_length=64, description="Span handle to re-open.")
    max_chars: int = Field(4000, ge=200, le=12000, description="Max body chars.")
    response_format: Literal["json", "markdown"] = Field("json", description="json|markdown")


class GrepArgs(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    pattern: str = Field(..., min_length=1, max_length=512, description="Literal/regex string.")
    glob: str = Field("*.py", max_length=128, description="File glob, e.g. *.py.")
    max_hits: int = Field(20, ge=1, le=60, description="Max matches to return.")
    response_format: Literal["json", "markdown"] = Field("json", description="json|markdown")


class UsagesArgs(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    symbol: str = Field(..., min_length=1, max_length=200, description="Identifier to find uses of.")
    keep: int = Field(6, ge=1, le=12, description="How many usage spans to return.")
    max_hits: int = Field(20, ge=1, le=60, description="Raw occurrence cap.")
    max_chars: int = Field(400, ge=120, le=2000, description="Per-usage body budget.")
    response_format: Literal["json", "markdown"] = Field("json", description="json|markdown")


class OutlineArgs(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    path: str = Field(..., min_length=1, max_length=512, description="Repo-relative file to outline.")
    keep: int = Field(60, ge=1, le=200, description="Max symbols to list.")
    response_format: Literal["json", "markdown"] = Field("json", description="json|markdown")


class NeighborsArgs(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    target: str = Field(..., min_length=1, max_length=512, description="Symbol or file to expand around.")
    keep: int = Field(4, ge=1, le=8, description="How many neighbor spans.")
    max_chars: int = Field(500, ge=120, le=2000, description="Per-neighbor body budget.")
    response_format: Literal["json", "markdown"] = Field("json", description="json|markdown")


class GraphArgs(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    question: str = Field(..., min_length=1, max_length=2000, description="NL structural question.")
    keep: int = Field(6, ge=1, le=10, description="How many spans to return.")
    max_chars: int = Field(400, ge=120, le=2000, description="Per-span body budget.")
    response_format: Literal["json", "markdown"] = Field("json", description="json|markdown")


class ImportsArgs(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    path: str = Field(..., min_length=1, max_length=512, description="File whose imports to follow.")
    query: str = Field("", max_length=2000, description="Optional bias for which imports matter.")
    keep: int = Field(6, ge=1, le=12, description="How many imported spans to return.")
    max_chars: int = Field(400, ge=120, le=2000, description="Per-span body budget.")
    response_format: Literal["json", "markdown"] = Field("json", description="json|markdown")


# ---- markdown ---------------------------------------------------------------

def _to_markdown(card: dict[str, Any]) -> str:
    lines = [f"# {card.get('tool', 'result')}", ""]
    if card.get("ok") is False:
        lines.append(f"**Error:** {card.get('error')}")
        if card.get("hint"):
            lines.append(f"**Hint:** {card['hint']}")
        return "\n".join(lines)
    if card.get("results"):
        lines.append("## Results")
        for r in card["results"]:
            lines.append(
                f"- #{r.get('rank')} `{r.get('file')}` "
                f"L{r.get('start_line')}-{r.get('end_line')} — {r.get('why') or ''}"
            )
            if r.get("code"):
                lines += ["```", str(r["code"])[:1200], "```"]
        lines.append("")
    if card.get("handle") and card.get("tool") in {"read", "expand"}:
        lines.append(
            f"## Span `{card.get('handle')}` `{card.get('file')}` "
            f"L{card.get('start_line')}-{card.get('end_line')} ({card.get('status')})"
        )
        if card.get("code"):
            lines += ["```", str(card["code"])[:3000], "```"]
        elif card.get("unchanged"):
            lines.append("_unchanged — already in session_")
        lines.append("")
    if card.get("hits"):
        lines.append("## Matches")
        for h in card["hits"]:
            lines.append(f"- `{h.get('file')}`:{h.get('line')} — {h.get('text') or ''}")
        lines.append("")
    if card.get("symbols"):
        lines.append("## Outline")
        for s in card["symbols"]:
            lines.append(f"- {s.get('kind') or ''} `{s.get('name')}` L{s.get('start_line')}")
        lines.append("")
    for key, title in (
        ("alternatives", "Other hits"),
        ("neighbors", "Neighbors (1-hop)"),
        ("spans", "Spans"),
        ("usages", "Usages"),
    ):
        if card.get(key):
            lines.append(f"## {title}")
            for n in card[key]:
                lines.append(
                    f"- `{n.get('file')}` L{n.get('start_line')}-{n.get('end_line')}"
                    f" — {n.get('why') or ''}"
                )
                if n.get("code"):
                    lines += ["```", str(n["code"])[:600], "```"]
            lines.append("")
    if card.get("next"):
        lines.append(f"\n_{card['next']}_")
    return "\n".join(lines)


def _format(card: dict[str, Any], fmt: str) -> str:
    if fmt == "markdown":
        return _to_markdown(card)
    return _dumps(card)


# ---- server -----------------------------------------------------------------

def create_mcp(name: str = "context_engine_mcp") -> "FastMCP":
    if FastMCP is None:
        raise RuntimeError("pip install mcp")
    surface = _active_surface()
    mcp = FastMCP(name, instructions=_server_instructions(surface))

    def _tool(tool_name: str, title: str, fn) -> None:
        mcp.tool(
            name=tool_name,
            annotations={
                "title": title,
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        )(fn)

    # ---- search (all surfaces) --------------------------------------------
    def search_impl(
        query: Annotated[str, Field(description="NL or symbol query. Soft/new asks welcome.")],
        k: Annotated[int, Field(description="How many hits (r5=5, r10=10).")] = 8,
        fetch: Annotated[bool, Field(description="Inline each hit's code body.")] = False,
        max_chars: Annotated[int, Field(description="Per-hit body budget when fetch=true.")] = 1200,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
    ) -> str:
        """WHEN: default reach-for — any soft/ad-hoc query or a new search.

        Semantic search fused from embeddings + BM25 + graph. RETURNS:
        results[{rank,file,start_line,end_line,score,why,(code if fetch)}].
        """
        try:
            args = SearchArgs(
                query=query, k=k, fetch=fetch, max_chars=max_chars,
                response_format=response_format,  # type: ignore[arg-type]
            )
        except ValidationError as exc:
            return _err("search", str(exc), hint="query required; k in 1..25.")
        repo = _default_repo()
        try:
            from pipeline.locate import _read_excerpt, _search_hits

            hits = _search_hits(repo, args.query, top_k=args.k)
            results: list[dict[str, Any]] = []
            for rank, h in enumerate(hits[: args.k], 1):
                f = h.get("file")
                item: dict[str, Any] = {
                    "rank": rank, "file": f,
                    "start_line": h.get("start_line"), "end_line": h.get("end_line"),
                    "score": round(float(h.get("score") or 0.0), 4),
                    "why": h.get("why") or "",
                }
                if args.fetch and f:
                    ex = _read_excerpt(
                        repo, str(f), int(h.get("start_line") or 0),
                        int(h.get("end_line") or 0), max_chars=args.max_chars,
                    )
                    item["code"] = ex.get("excerpt") or ex.get("text") or ""
                results.append(item)
            out = {
                "ok": True, "tool": "search", "query": args.query, "k": args.k,
                "fetch": args.fetch, "count": len(results), "results": results,
                "next": "fetch=true to inline bodies; raise k / sharpen if thin.",
            }
            return _format(out, args.response_format)
        except Exception as exc:  # noqa: BLE001
            return _err("search", str(exc), hint="Check status()/CTX_REPO; ensure index is warm.")

    # ---- read (read, rich) -------------------------------------------------
    def read_impl(
        target: Annotated[str, Field(description="Symbol / phrase / 'path' / 'path:line'.")] = "",
        path: Annotated[str, Field(description="Explicit repo-relative file (skips search).")] = "",
        query: Annotated[str, Field(description="When path= set, pick the span for this.")] = "",
        handle: Annotated[str, Field(description="Re-materialize a prior span handle.")] = "",
        neighbors: Annotated[bool, Field(description="Add capped 1-hop callers/callees.")] = False,
        max_chars: Annotated[int, Field(description="Body budget for the span.")] = 2000,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
    ) -> str:
        """WHEN: open a specific thing before editing — a symbol, a search hit, or a
        known file. Session-deduped: re-reading a span returns an "unchanged" stub.
        neighbors=true attaches 1-hop callers/callees.
        """
        try:
            args = ReadArgs(
                target=target, path=path, query=query, handle=handle,
                neighbors=neighbors, max_chars=max_chars,
                response_format=response_format,  # type: ignore[arg-type]
            )
        except ValidationError as exc:
            return _err("read", str(exc), hint="Pass target= or path= or handle=.")
        repo = _default_repo()

        if args.handle:
            try:
                from pipeline.session_store import expand as _expand

                card = _expand(repo, args.handle, max_chars=args.max_chars)
                if not card.get("ok"):
                    return _err("read", str(card.get("error") or "unknown handle"),
                                handle=args.handle, hint="Search again; handle may be stale.")
                out = {
                    "ok": True, "tool": "read", "mode": "handle", "handle": args.handle,
                    "file": card.get("path"), "start_line": card.get("start_line"),
                    "end_line": card.get("end_line"), "status": "materialized",
                    "code": card.get("text") or card.get("excerpt") or "",
                }
                return _format(out, args.response_format)
            except Exception as exc:  # noqa: BLE001
                return _err("read", str(exc), handle=args.handle)

        path_s = (args.path or "").replace("\\", "/").strip()
        target_s = (args.target or "").strip()
        q = (args.query or "").strip()
        alternatives: list[dict[str, Any]] = []

        if not path_s and _looks_like_path(target_s):
            if ":" in target_s and not target_s.endswith(":"):
                head, _, tail = target_s.rpartition(":")
                if tail.isdigit():
                    path_s = head
            path_s = path_s or target_s

        start_l, end_l = 0, 0
        if path_s:
            start_l, end_l = _resolve_span_in_path(repo, path_s, q or target_s)
            resolved_from = "path"
            file_s = path_s
        else:
            tq = target_s or q
            if not tq:
                return _err("read", "target, path, or handle required",
                            hint="read(target='WarmSearchEngine.search') or read(path='pkg/x.py').")
            try:
                from pipeline.locate import _search_hits

                hits = _search_hits(repo, tq, top_k=8)
            except Exception as exc:  # noqa: BLE001
                return _err("read", str(exc), hint="Ensure the search index is warm.")
            if not hits:
                return _err("read", f"no span found for {tq!r}",
                            hint="Try search(query) first, then read(target=<a hit's file>).")
            top = hits[0]
            file_s = str(top.get("file") or "")
            start_l = int(top.get("start_line") or 0)
            end_l = int(top.get("end_line") or 0)
            resolved_from = "search"
            for h in hits[1:3]:
                alternatives.append({
                    "file": h.get("file"), "start_line": h.get("start_line"),
                    "end_line": h.get("end_line"), "why": (h.get("why") or "")[:140],
                })

        try:
            from pipeline.locate import _read_excerpt

            ex = _read_excerpt(repo, file_s, start_l, end_l, max_chars=args.max_chars)
        except Exception as exc:  # noqa: BLE001
            return _err("read", str(exc), file=file_s)
        code = ex.get("excerpt") or ex.get("text") or ""
        start_l = int(ex.get("start_line") or start_l or 0)
        end_l = int(ex.get("end_line") or end_l or 0)

        try:
            from pipeline.session_store import put_span

            span = put_span(
                repo, path=file_s, start_line=start_l, end_line=end_l, text=code,
                why=target_s or q or file_s, source="read",
                topic=target_s or q or file_s, excerpt_chars=100,
            )
            handle_s = span.get("handle")
            status_s = span.get("status")
        except Exception:  # noqa: BLE001
            handle_s, status_s = None, "stored"

        unchanged = status_s == "already_in_session"
        out = {
            "ok": True, "tool": "read", "mode": resolved_from, "handle": handle_s,
            "file": file_s, "start_line": start_l, "end_line": end_l,
            "status": status_s, "unchanged": unchanged,
            "code": "" if unchanged else code,
        }
        if unchanged:
            out["hint"] = "already in session — you have this span; don't re-read it."
        if alternatives:
            out["alternatives"] = alternatives

        if args.neighbors and file_s:
            try:
                gn = _client_for(repo).graph_neighbors(
                    [file_s], query=target_s or q or "", keep=4, max_chars=400, repo=str(repo),
                )
                nbrs = _slim_spans(gn.get("spans") or [], keep=4, body_chars=400)
                if nbrs:
                    out["neighbors"] = nbrs
            except Exception:  # noqa: BLE001
                out["neighbors_note"] = "neighbors unavailable (graph not warm)"

        out["next"] = "Edit now. read(neighbors=true) for callers; expand(handle) to re-open."
        return _format(out, args.response_format)

    # ---- expand (rich) -----------------------------------------------------
    def expand_impl(
        handle: Annotated[str, Field(description="Span handle from a prior read/search.")],
        max_chars: Annotated[int, Field(description="Max body chars to materialize.")] = 4000,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
    ) -> str:
        """WHEN: re-open the full body of a span you already saw (by handle) — avoids
        re-reading the file. RETURNS: path + lines + code.
        """
        try:
            args = ExpandArgs(handle=handle, max_chars=max_chars,
                              response_format=response_format)  # type: ignore[arg-type]
        except ValidationError as exc:
            return _err("expand", str(exc), hint="Pass a handle from read/search.")
        repo = _default_repo()
        try:
            from pipeline.session_store import expand as _expand

            card = _expand(repo, args.handle, max_chars=args.max_chars)
            if not card.get("ok"):
                return _err("expand", str(card.get("error") or "unknown handle"),
                            handle=args.handle, hint="search()/read() to create spans.")
            out = {
                "ok": True, "tool": "expand", "handle": args.handle,
                "file": card.get("path"), "start_line": card.get("start_line"),
                "end_line": card.get("end_line"), "status": "materialized",
                "code": card.get("text") or "",
            }
            return _format(out, args.response_format)
        except Exception as exc:  # noqa: BLE001
            return _err("expand", str(exc), handle=args.handle)

    # ---- grep (rich) -------------------------------------------------------
    def grep_impl(
        pattern: Annotated[str, Field(description="Literal/regex string to match.")],
        glob: Annotated[str, Field(description="File glob, e.g. *.py.")] = "*.py",
        max_hits: Annotated[int, Field(description="Max matches to return.")] = 20,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
    ) -> str:
        """WHEN: you need an EXACT string / literal / regex (an import line, a config
        key, a specific token). Faster and more precise than semantic search for
        exact matches. RETURNS: hits[{file,line,text}].
        """
        try:
            args = GrepArgs(pattern=pattern, glob=glob, max_hits=max_hits,
                           response_format=response_format)  # type: ignore[arg-type]
        except ValidationError as exc:
            return _err("grep", str(exc), hint="pattern required.")
        repo = _default_repo()
        try:
            res = _client_for(repo).grep(
                args.pattern, glob=args.glob, max_hits=args.max_hits, path=str(repo),
            )
        except Exception as exc:  # noqa: BLE001
            return _err("grep", str(exc), hint="Ensure the engine is warm.")
        hits = _slim_grep(res.get("hits") or res.get("matches"), keep=args.max_hits)
        out = {
            "ok": True, "tool": "grep", "pattern": args.pattern, "glob": args.glob,
            "count": len(hits), "hits": hits,
            "next": "read(path, query) or usages(symbol) to go deeper; search() for meaning.",
        }
        return _format(out, args.response_format)

    # ---- usages (rich) -----------------------------------------------------
    def usages_impl(
        symbol: Annotated[str, Field(description="Identifier to find every use of.")],
        keep: Annotated[int, Field(description="How many usage spans (1..12).")] = 6,
        max_hits: Annotated[int, Field(description="Raw occurrence cap.")] = 20,
        max_chars: Annotated[int, Field(description="Per-usage body budget.")] = 400,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
    ) -> str:
        """WHEN: "where is this symbol used / called" — identifier-aware occurrences
        with small surrounding spans. Use instead of grepping a bare name.
        RETURNS: usages[{file,start_line,end_line,why,code}].
        """
        try:
            args = UsagesArgs(symbol=symbol, keep=keep, max_hits=max_hits,
                             max_chars=max_chars, response_format=response_format)  # type: ignore[arg-type]
        except ValidationError as exc:
            return _err("usages", str(exc), hint="symbol required.")
        repo = _default_repo()
        try:
            res = _client_for(repo).grep_ident(
                args.symbol, max_hits=args.max_hits, max_chars=args.max_chars,
                keep=args.keep, path=str(repo),
            )
        except Exception as exc:  # noqa: BLE001
            return _err("usages", str(exc), hint="Ensure the engine is warm.")
        spans = res.get("spans")
        if spans:
            uses = _slim_spans(spans, keep=args.keep, body_chars=args.max_chars)
        else:
            uses = _slim_grep(res.get("hits") or res.get("matches"), keep=args.keep)
        out = {
            "ok": True, "tool": "usages", "symbol": args.symbol,
            "count": len(uses), "usages": uses,
            "next": "read(path, query) to open a call site; neighbors(target) for callers.",
        }
        return _format(out, args.response_format)

    # ---- outline (rich) ----------------------------------------------------
    def outline_impl(
        path: Annotated[str, Field(description="Repo-relative file to outline.")],
        keep: Annotated[int, Field(description="Max symbols to list.")] = 60,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
    ) -> str:
        """WHEN: understand a file's shape fast — its classes/functions and their
        line ranges — without reading the whole file. RETURNS: symbols[{name,kind,
        start_line,end_line}].
        """
        try:
            args = OutlineArgs(path=path, keep=keep,
                              response_format=response_format)  # type: ignore[arg-type]
        except ValidationError as exc:
            return _err("outline", str(exc), hint="path required.")
        repo = _default_repo()
        try:
            res = _client_for(repo).outline(args.path.replace("\\", "/"), repo=str(repo))
        except Exception as exc:  # noqa: BLE001
            return _err("outline", str(exc), hint="Ensure the engine is warm.")
        symbols = _slim_outline(res.get("symbols") or res.get("outline"), keep=args.keep)
        out = {
            "ok": True, "tool": "outline", "path": res.get("path") or args.path,
            "count": len(symbols), "symbols": symbols,
            "next": "read(path, query='<symbol>') to open one; usages(symbol) for call sites.",
        }
        return _format(out, args.response_format)

    # ---- neighbors (graph, rich) ------------------------------------------
    def neighbors_impl(
        target: Annotated[str, Field(description="Symbol or repo-relative file to expand around.")],
        keep: Annotated[int, Field(description="How many neighbor spans (1..8).")] = 4,
        max_chars: Annotated[int, Field(description="Per-neighbor body budget.")] = 500,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
    ) -> str:
        """WHEN: "what calls / uses / imports X" — the 1-hop graph around a symbol or
        file. RETURNS: neighbors[{file,start_line,end_line,why,code}].
        """
        try:
            args = NeighborsArgs(target=target, keep=keep, max_chars=max_chars,
                                response_format=response_format)  # type: ignore[arg-type]
        except ValidationError as exc:
            return _err("neighbors", str(exc), hint="Pass a symbol or a repo-relative file.")
        repo = _default_repo()
        file_s = _resolve_to_file(repo, args.target)
        if not file_s:
            return _err("neighbors", f"could not resolve {args.target!r} to a file",
                        hint="Try search(query) first, then neighbors(target=<a hit's file>).")
        try:
            gn = _client_for(repo).graph_neighbors(
                [file_s], query=args.target, keep=args.keep, max_chars=args.max_chars, repo=str(repo),
            )
        except Exception as exc:  # noqa: BLE001
            return _err("neighbors", str(exc), hint="Ensure the graph index is warm.")
        nbrs = _slim_spans(gn.get("spans") or [], keep=args.keep, body_chars=args.max_chars)
        out = {
            "ok": True, "tool": "neighbors", "target": args.target, "file": file_s,
            "count": len(nbrs), "neighbors": nbrs,
            "next": "read() a neighbor to edit; search() to widen.",
        }
        return _format(out, args.response_format)

    # ---- graph (graph, rich) ----------------------------------------------
    def graph_impl(
        question: Annotated[str, Field(description="NL structural/relationship question.")],
        keep: Annotated[int, Field(description="How many spans (1..10).")] = 6,
        max_chars: Annotated[int, Field(description="Per-span body budget.")] = 400,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
    ) -> str:
        """WHEN: relationship / "how does A reach B", "what's wired to this" — follows
        graph affinity, not just text meaning. RETURNS: spans[{file,start_line,
        end_line,why,code}].
        """
        try:
            args = GraphArgs(question=question, keep=keep, max_chars=max_chars,
                            response_format=response_format)  # type: ignore[arg-type]
        except ValidationError as exc:
            return _err("graph", str(exc), hint="Pass a natural-language question.")
        repo = _default_repo()
        try:
            gq = _client_for(repo).query_graph(
                args.question, keep=args.keep, max_chars=args.max_chars, repo=str(repo),
            )
        except Exception as exc:  # noqa: BLE001
            return _err("graph", str(exc), hint="Ensure the graph index is warm.")
        spans = _slim_spans(gq.get("spans") or [], keep=args.keep, body_chars=args.max_chars)
        out = {
            "ok": True, "tool": "graph", "question": args.question,
            "count": len(spans), "spans": spans,
            "next": "neighbors(target=<a file>) to expand one node; search() for meaning.",
        }
        return _format(out, args.response_format)

    # ---- imports (rich) ----------------------------------------------------
    def imports_impl(
        path: Annotated[str, Field(description="File whose imports/dependencies to follow.")],
        query: Annotated[str, Field(description="Optional bias for which imports matter.")] = "",
        keep: Annotated[int, Field(description="How many imported spans (1..12).")] = 6,
        max_chars: Annotated[int, Field(description="Per-span body budget.")] = 400,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
    ) -> str:
        """WHEN: "what does this file depend on / pull in" — follows imports to the
        relevant defining spans. RETURNS: spans[{file,start_line,end_line,why,code}].
        """
        try:
            args = ImportsArgs(path=path, query=query, keep=keep, max_chars=max_chars,
                              response_format=response_format)  # type: ignore[arg-type]
        except ValidationError as exc:
            return _err("imports", str(exc), hint="path required.")
        repo = _default_repo()
        try:
            fi = _client_for(repo).follow_imports(
                args.path.replace("\\", "/"), query=args.query, keep=args.keep,
                max_chars=args.max_chars, repo=str(repo),
            )
        except Exception as exc:  # noqa: BLE001
            return _err("imports", str(exc), hint="Ensure the engine is warm.")
        spans = _slim_spans(fi.get("spans") or [], keep=args.keep, body_chars=args.max_chars)
        out = {
            "ok": True, "tool": "imports", "path": args.path,
            "count": len(spans), "spans": spans,
            "next": "read() an import to edit; neighbors(target) for the reverse (callers).",
        }
        return _format(out, args.response_format)

    # ---- status (all surfaces) --------------------------------------------
    def status_impl() -> str:
        """WHEN: health check or to see session size / which tools exist."""
        from pipeline.client import EngineClient
        from pipeline.session_store import load_store, token_mode

        tool_lists = {
            "read": ["search", "read", "status"],
            "graph": ["search", "neighbors", "graph", "status"],
            "rich": ["search", "grep", "usages", "read", "expand", "outline",
                     "neighbors", "graph", "imports", "status"],
            "search": ["search", "status"],
            "grep": ["grep", "status"],
        }
        try:
            eng = EngineClient()
            repo = _default_repo()
            store = load_store(repo)
            return _dumps({
                "ok": eng.healthy(), "tool": "status", "server": "context_engine_mcp",
                "surface": surface, "engine": {"healthy": eng.healthy()},
                "repo": str(repo), "token_mode": token_mode(),
                "tools": tool_lists.get(surface, tool_lists["read"]),
                "session": {
                    "topic": store.get("topic"),
                    "n_spans": len(store.get("spans") or {}),
                    "ledger": store.get("ledger") or {},
                },
            })
        except Exception as exc:  # noqa: BLE001
            return _err("status", str(exc))

    # ---- register per surface ---------------------------------------------
    if surface != "grep":
        _tool("search", "Semantic code search (simple, flexible)", search_impl)
    if surface == "read":
        _tool("read", "Read the right span (deduped, + neighbors)", read_impl)
    elif surface == "grep":
        _tool("grep", "Exact/literal text search", grep_impl)
    elif surface == "graph":
        _tool("neighbors", "1-hop graph neighbors (callers/callees)", neighbors_impl)
        _tool("graph", "NL structural/relationship query (graph)", graph_impl)
    elif surface == "rich":
        _tool("grep", "Exact/literal text search", grep_impl)
        _tool("usages", "Identifier usages (call sites)", usages_impl)
        _tool("read", "Read the right span (deduped, + neighbors)", read_impl)
        _tool("expand", "Re-open a span by handle", expand_impl)
        _tool("outline", "File structure (defs/classes)", outline_impl)
        _tool("neighbors", "1-hop graph neighbors (callers/callees)", neighbors_impl)
        _tool("graph", "NL structural/relationship query (graph)", graph_impl)
        _tool("imports", "Follow a file's imports/dependencies", imports_impl)
    # surface == "search": only search + status
    _tool("status", "Engine + session status", status_impl)

    return mcp


def main() -> None:
    repo = _default_repo()
    os.environ.setdefault("CTX_REPO", str(repo))
    os.environ.setdefault("CTX_TOKEN_MODE", "savings")
    os.environ.setdefault("CTX_SESSION_GOVERNOR", "1")
    surface = _active_surface()
    tool_lists = {
        "read": "search,read,status",
        "graph": "search,neighbors,graph,status",
        "rich": "search,grep,usages,read,expand,outline,neighbors,graph,imports,status",
        "search": "search,status",
        "grep": "grep,status",
    }
    _stderr(
        f"[context_engine_mcp] surface={surface} tools={tool_lists.get(surface)} "
        f"repo={repo} token_mode={os.environ.get('CTX_TOKEN_MODE')}"
    )
    create_mcp().run(transport="stdio")


if __name__ == "__main__":
    main()
