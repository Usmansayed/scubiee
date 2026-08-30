"""Persistent working-set session: heatmap of files the agent is camping on.

Agents often spend hours in one subgraph. Touch counts from map/focus/workspace
drive a live heatmap + induced graph neighborhood without an LLM.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


def _session_path(repo: Path, session_id: str | None = None) -> Path:
    from pipeline.session_isolation import effective_session_id, session_data_dir
    from pipeline.project_id import repo_runtime_dir

    repo_p = Path(repo).resolve()
    sid = effective_session_id(session_id)
    if sid:
        return session_data_dir(repo_p, sid) / "work_session.json"
    from pipeline.project_id import repo_runtime_dir

    base = repo_runtime_dir(repo_p)
    base.mkdir(parents=True, exist_ok=True)
    name = os.environ.get("CTX_WORK_SESSION") or "work_session.json"
    return base / name


def load_session(repo: Path | str, *, session_id: str | None = None) -> dict[str, Any]:
    repo_p = Path(repo).resolve()
    path = _session_path(repo_p, session_id)
    empty = {
        "repo": str(repo_p),
        "updated_at": time.time(),
        "topic": "",
        "files": {},
        "pins": [],
    }
    if not path.is_file():
        return empty
    from pipeline.session_isolation import session_json_lock

    with session_json_lock(path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("bad session")
            data.setdefault("files", {})
            data.setdefault("pins", [])
            data.setdefault("topic", "")
            return data
        except Exception:  # noqa: BLE001
            return empty


def save_session(
    repo: Path | str,
    data: dict[str, Any],
    *,
    session_id: str | None = None,
) -> Path:
    repo_p = Path(repo).resolve()
    path = _session_path(repo_p, session_id)
    data["repo"] = str(repo_p)
    data["updated_at"] = time.time()
    from pipeline.session_isolation import effective_session_id, session_json_lock

    sid = effective_session_id(session_id)
    if sid:
        data["session_id"] = sid
    with session_json_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return path


def touch(
    repo: Path | str,
    files: list[str] | list[dict[str, Any]],
    *,
    query: str = "",
    weight: int = 1,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Record file touches (from map/focus results)."""
    repo_p = Path(repo).resolve()
    sess = load_session(repo_p, session_id=session_id)
    if query:
        sess["topic"] = (query or "")[:240]
    now = time.time()
    for item in files or []:
        if isinstance(item, dict):
            f = (item.get("file") or item.get("path") or "").replace("\\", "/")
            role = item.get("role") or ""
        else:
            f = str(item).replace("\\", "/")
            role = ""
        if not f:
            continue
        entry = sess["files"].setdefault(
            f, {"hits": 0, "last_ts": 0.0, "roles": [], "queries": []}
        )
        entry["hits"] = int(entry.get("hits") or 0) + max(1, int(weight))
        entry["last_ts"] = now
        if role and role not in entry["roles"]:
            entry["roles"] = (entry.get("roles") or [])[-4:] + [role]
        if query:
            qs = entry.setdefault("queries", [])
            if query not in qs:
                qs.append(query[:160])
                entry["queries"] = qs[-5:]
    save_session(repo_p, sess, session_id=session_id)
    return sess


def pin(repo: Path | str, path: str, *, session_id: str | None = None) -> dict[str, Any]:
    sess = load_session(repo, session_id=session_id)
    p = path.replace("\\", "/")
    pins = sess.setdefault("pins", [])
    if p and p not in pins:
        pins.append(p)
    save_session(repo, sess, session_id=session_id)
    return sess


def clear_session(repo: Path | str, *, session_id: str | None = None) -> dict[str, Any]:
    repo_p = Path(repo).resolve()
    empty = {
        "repo": str(repo_p),
        "updated_at": time.time(),
        "topic": "",
        "files": {},
        "pins": [],
    }
    save_session(repo_p, empty, session_id=session_id)
    return empty


def heatmap(repo: Path | str, *, top_n: int = 20, session_id: str | None = None) -> list[dict[str, Any]]:
    sess = load_session(repo, session_id=session_id)
    rows = []
    now = time.time()
    for f, meta in (sess.get("files") or {}).items():
        hits = int(meta.get("hits") or 0)
        age = max(0.0, now - float(meta.get("last_ts") or now))
        # recency boost: half-life ~2h
        recency = 1.0 / (1.0 + age / 7200.0)
        heat = hits * (0.4 + 0.6 * recency)
        if f in (sess.get("pins") or []):
            heat += 5.0
        rows.append(
            {
                "file": f,
                "hits": hits,
                "heat": round(heat, 2),
                "roles": meta.get("roles") or [],
                "last_queries": meta.get("queries") or [],
                "pinned": f in (sess.get("pins") or []),
            }
        )
    rows.sort(key=lambda r: r["heat"], reverse=True)
    return rows[: max(1, min(int(top_n), 40))]


def working_subgraph(
    repo: Path | str,
    *,
    top_n: int = 12,
    depth: int = 0,
    token_budget: int = 0,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Induced neighborhood around hottest files (Graphify text pack).

    Agent default: heatmap + pins only. Pass depth>=1 (or token_budget>0)
    when the agent explicitly wants a graph neighborhood dump.
    """
    import os

    repo_p = Path(repo).resolve()
    hot_raw = heatmap(repo_p, top_n=top_n, session_id=session_id)
    hot = [
        {
            "file": h.get("file"),
            "heat": h.get("heat"),
            "pinned": h.get("pinned"),
            "hits": h.get("hits"),
        }
        for h in hot_raw
    ]
    seeds = [h["file"] for h in hot if h.get("file")]
    pins = load_session(repo_p, session_id=session_id).get("pins") or []
    for p in pins:
        if p not in seeds:
            seeds.insert(0, p)

    savings = (os.environ.get("CTX_TOKEN_MODE") or "savings").lower() in {
        "savings",
        "save",
    }
    # TraceLab: workspace is orientation (heatmap), not a graph novel.
    want_graph = int(depth or 0) >= 1 or int(token_budget or 0) > 0
    if savings and not want_graph:
        graph_text = ""
    else:
        graph_text = ""
        try:
            from pipeline.graphify_mcp_tools import query_graph_text

            labels = []
            for s in seeds[:8]:
                stem = Path(s).stem
                if stem and stem not in {"__init__", "__main__"}:
                    labels.append(stem)
            question = (
                " ".join(labels)
                if labels
                else (load_session(repo_p, session_id=session_id).get("topic") or "working set")
            )
            gb = int(token_budget) if token_budget else (800 if savings else 3500)
            graph_text = query_graph_text(
                repo_p,
                question,
                depth=max(1, min(int(depth or 1), 4)),
                token_budget=max(400, min(gb, 6000)),
            )
        except Exception as exc:  # noqa: BLE001
            graph_text = f"(graph unavailable: {exc})"

    sess = load_session(repo_p, session_id=session_id)
    out: dict[str, Any] = {
        "ok": True,
        "tool": "workspace",
        "topic": sess.get("topic") or "",
        "heatmap": hot,
        "seeds": seeds[:12],
        "pins": pins,
        "updated_at": sess.get("updated_at"),
        "next": (
            "Hot zone listed. Prefer focus(query) inside this set. "
            "map(query) only for a new topic. pin paths you will edit. "
            "Pass depth=1 only if you need the graph neighborhood."
        ),
    }
    if graph_text:
        out["subgraph"] = graph_text
    return out
