"""Session-native context store: spans, handles, ledger, recall/expand.

Keeps full span text server-side. Agents get compact handles + short excerpts.
Repeat fetches of the same content_hash return already_in_session stubs.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any


def _store_path(repo: Path) -> Path:
    base = repo / ".context-engine"
    base.mkdir(parents=True, exist_ok=True)
    name = os.environ.get("CTX_SESSION_STORE") or "session_store.json"
    return base / name


def _empty(repo: Path) -> dict[str, Any]:
    return {
        "repo": str(repo.resolve()),
        "updated_at": time.time(),
        "topic": "",
        "turn": 0,
        "spans": {},
        "facts": [],
        "ledger": {"served_handles": [], "approx_prompt_tokens": 0},
        "by_hash": {},  # content_hash -> handle
        "by_key": {},  # path:start:end -> handle
        "locate_thrash": {"soft": [], "exact": [], "seen": []},
    }


def load_store(repo: Path | str) -> dict[str, Any]:
    repo_p = Path(repo).resolve()
    path = _store_path(repo_p)
    if not path.is_file():
        return _empty(repo_p)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("bad store")
        for k, v in _empty(repo_p).items():
            data.setdefault(k, v)
        return data
    except Exception:  # noqa: BLE001
        return _empty(repo_p)


def save_store(repo: Path | str, data: dict[str, Any]) -> Path:
    repo_p = Path(repo).resolve()
    path = _store_path(repo_p)
    data["repo"] = str(repo_p)
    data["updated_at"] = time.time()
    # cap spans
    spans = data.get("spans") or {}
    if len(spans) > 200:
        ordered = sorted(
            spans.items(),
            key=lambda kv: float((kv[1] or {}).get("last_served_ts") or 0),
        )
        keep = dict(ordered[-200:])
        data["spans"] = keep
        data["by_hash"] = {
            h: hid for hid, sp in keep.items() for h in [sp.get("content_hash")] if h
        }
        data["by_key"] = {
            f"{sp.get('path')}:{sp.get('start_line')}:{sp.get('end_line')}": hid
            for hid, sp in keep.items()
        }
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return path


def clear_store(repo: Path | str) -> dict[str, Any]:
    repo_p = Path(repo).resolve()
    empty = _empty(repo_p)
    save_store(repo_p, empty)
    return empty


def content_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()[:24]


def _new_handle(store: dict[str, Any]) -> str:
    n = len(store.get("spans") or {}) + 1
    return f"sp_{n:04d}_{hashlib.sha1(str(time.time()).encode()).hexdigest()[:6]}"


def _excerpt(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[: max(0, max_chars - 1)] + "…"


def token_mode() -> str:
    return (os.environ.get("CTX_TOKEN_MODE") or "savings").strip().lower()


def savings_defaults(mode: str = "map") -> dict[str, int]:
    """Budget defaults for ~50% retrieval-append target."""
    tm = token_mode()
    if tm in {"rich", "full", "debug"}:
        if mode == "map":
            return {"excerpt_chars": 1600, "max_targets": 6, "graph_budget": 4000, "top_k": 12}
        return {"excerpt_chars": 1200, "max_targets": 3, "graph_budget": 1600, "top_k": 8}
    # savings (default)
    if mode == "map":
        return {"excerpt_chars": 900, "max_targets": 5, "graph_budget": 2500, "top_k": 10}
    # savings (default): tiny face, graph optional via workspace/related
    return {"excerpt_chars": 480, "max_targets": 3, "graph_budget": 600, "top_k": 8}


def put_span(
    repo: Path | str,
    *,
    path: str,
    start_line: int = 0,
    end_line: int = 0,
    text: str = "",
    why: str = "",
    source: str = "",
    role: str = "",
    topic: str = "",
    excerpt_chars: int = 80,
) -> dict[str, Any]:
    """Store span body server-side; return compact card with handle."""
    repo_p = Path(repo).resolve()
    store = load_store(repo_p)
    path_s = (path or "").replace("\\", "/")
    text_s = text or ""
    h = content_hash(text_s)
    key = f"{path_s}:{int(start_line or 0)}:{int(end_line or 0)}"

    existing = store.get("by_hash", {}).get(h) or store.get("by_key", {}).get(key)
    if existing and existing in (store.get("spans") or {}):
        sp = store["spans"][existing]
        sp["serve_count"] = int(sp.get("serve_count") or 0) + 1
        sp["last_served_ts"] = time.time()
        ledger = store.setdefault("ledger", {"served_handles": [], "approx_prompt_tokens": 0})
        served = ledger.setdefault("served_handles", [])
        if existing not in served:
            served.append(existing)
            served[:] = served[-100:]
        if topic:
            store["topic"] = topic[:240]
        save_store(repo_p, store)
        return {
            "status": "already_in_session",
            "handle": existing,
            "path": sp.get("path"),
            "start_line": sp.get("start_line"),
            "end_line": sp.get("end_line"),
            "content_hash": h,
            "why": why or sp.get("why") or "",
            "role": role or sp.get("role") or "",
            "source": source or sp.get("source") or "",
            "excerpt": None,
            "hint": "already_in_session — call expand(handle) only if you need the body again",
            "serve_count": sp["serve_count"],
        }

    handle = _new_handle(store)
    store.setdefault("spans", {})[handle] = {
        "path": path_s,
        "start_line": int(start_line or 0),
        "end_line": int(end_line or 0),
        "content_hash": h,
        "text": text_s,
        "why": (why or "")[:200],
        "role": (role or "")[:40],
        "source": (source or "")[:40],
        "created_ts": time.time(),
        "last_served_ts": time.time(),
        "serve_count": 1,
    }
    store.setdefault("by_hash", {})[h] = handle
    store.setdefault("by_key", {})[key] = handle
    if topic:
        store["topic"] = topic[:240]
    ledger = store.setdefault("ledger", {"served_handles": [], "approx_prompt_tokens": 0})
    served = ledger.setdefault("served_handles", [])
    served.append(handle)
    served[:] = served[-100:]
    # rough token estimate of what we *would* have sent
    ledger["approx_prompt_tokens"] = int(ledger.get("approx_prompt_tokens") or 0) + max(
        1, len(_excerpt(text_s, max(40, excerpt_chars))) // 4
    )
    save_store(repo_p, store)
    return {
        "status": "stored",
        "handle": handle,
        "path": path_s,
        "start_line": int(start_line or 0),
        "end_line": int(end_line or 0),
        "content_hash": h,
        "why": (why or "")[:200],
        "role": (role or "")[:40],
        "source": (source or "")[:40],
        "excerpt": _excerpt(text_s, max(40, int(excerpt_chars))),
        "hint": "Full text is in session store. expand(handle) to materialize.",
        "serve_count": 1,
    }


def govern_targets(
    repo: Path | str,
    targets: list[dict[str, Any]],
    *,
    excerpt_chars: int | None = None,
    topic: str = "",
) -> list[dict[str, Any]]:
    """Replace target excerpts with handles + tiny excerpts."""
    if excerpt_chars is None:
        excerpt_chars = savings_defaults("map")["excerpt_chars"] // 10  # tiny face excerpt
        excerpt_chars = max(60, min(excerpt_chars, 120))
    out: list[dict[str, Any]] = []
    for t in targets or []:
        item = dict(t)
        text = item.pop("excerpt", None) or item.pop("text", None) or ""
        card = put_span(
            repo,
            path=str(item.get("file") or item.get("path") or ""),
            start_line=int(item.get("start_line") or 0),
            end_line=int(item.get("end_line") or 0),
            text=str(text),
            why=str(item.get("why") or ""),
            role=str(item.get("role") or ""),
            source="locate",
            topic=topic,
            excerpt_chars=int(excerpt_chars),
        )
        item["handle"] = card["handle"]
        item["status"] = card["status"]
        item.pop("content_hash", None)  # store-only; agents use handle
        if card["status"] == "already_in_session":
            item["excerpt"] = ""
            item["hint"] = card.get("hint")
        else:
            item["excerpt"] = card.get("excerpt") or ""
        # Face why is for routing, not a second body dump
        why = str(item.get("why") or "")
        if len(why) > 140:
            item["why"] = why[:140].rstrip() + "…"
        out.append(item)
    return out


def expand(repo: Path | str, handle: str, max_chars: int = 4000) -> dict[str, Any]:
    repo_p = Path(repo).resolve()
    store = load_store(repo_p)
    hid = (handle or "").strip()
    sp = (store.get("spans") or {}).get(hid)
    if not sp:
        return {"ok": False, "error": f"unknown handle {hid}", "handle": hid}

    text = sp.get("text") or ""
    path_s = sp.get("path") or ""
    # refresh if file changed on disk
    try:
        fp = repo_p / path_s
        if fp.is_file() and int(sp.get("start_line") or 0) > 0:
            lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
            s = max(0, int(sp["start_line"]) - 1)
            e = min(len(lines), max(int(sp.get("end_line") or s + 1), s + 1))
            fresh = "\n".join(lines[s:e])
            fh = content_hash(fresh)
            if fh != sp.get("content_hash"):
                sp["text"] = fresh
                sp["content_hash"] = fh
                text = fresh
                store["by_hash"][fh] = hid
    except Exception:  # noqa: BLE001
        pass

    sp["serve_count"] = int(sp.get("serve_count") or 0) + 1
    sp["last_served_ts"] = time.time()
    save_store(repo_p, store)

    max_chars = max(200, min(int(max_chars or 4000), 12000))
    body = text if len(text) <= max_chars else text[: max_chars - 1] + "…"
    return {
        "ok": True,
        "handle": hid,
        "path": path_s,
        "start_line": sp.get("start_line"),
        "end_line": sp.get("end_line"),
        "content_hash": sp.get("content_hash"),
        "why": sp.get("why"),
        "text": body,
        "chars": len(body),
        "truncated": len(text) > max_chars,
    }


def recall(repo: Path | str, need: str = "", top_n: int = 20) -> dict[str, Any]:
    """List what the session already knows — no file bodies."""
    repo_p = Path(repo).resolve()
    store = load_store(repo_p)
    need_l = (need or "").strip().lower()
    spans_out = []
    for hid, sp in (store.get("spans") or {}).items():
        blob = " ".join(
            [
                str(sp.get("path") or ""),
                str(sp.get("why") or ""),
                str(sp.get("role") or ""),
                store.get("topic") or "",
            ]
        ).lower()
        if need_l and need_l not in blob and not any(t in blob for t in need_l.split() if len(t) > 2):
            continue
        spans_out.append(
            {
                "handle": hid,
                "path": sp.get("path"),
                "start_line": sp.get("start_line"),
                "end_line": sp.get("end_line"),
                "why": (str(sp.get("why") or "")[:120] + ("…" if len(str(sp.get("why") or "")) > 120 else "")),
                "role": sp.get("role"),
                "serve_count": sp.get("serve_count"),
            }
        )
    spans_out.sort(key=lambda r: int(r.get("serve_count") or 0), reverse=True)

    # include work_session pins/heatmap lightly
    pins: list[str] = []
    hot: list[dict[str, Any]] = []
    try:
        from pipeline.work_session import heatmap, load_session

        pins = list(load_session(repo_p).get("pins") or [])
        hot_raw = heatmap(repo_p, top_n=8)
        hot = [
            {"file": h.get("file"), "heat": h.get("heat"), "pinned": h.get("pinned")}
            for h in hot_raw
        ]
    except Exception:  # noqa: BLE001
        pass

    return {
        "ok": True,
        "tool": "recall",
        "topic": store.get("topic") or "",
        "need": need,
        "spans": spans_out[: max(1, min(int(top_n), 40))],
        "pins": pins,
        "heatmap": hot,
        "n_spans": len(store.get("spans") or {}),
        "next": (
            "Use expand(handle) only for spans you will edit. "
            "If need is new, call focus(query) or map(query). Do not Grep."
        ),
    }


def apply_governor_to_card(repo: Path | str, card: dict[str, Any]) -> dict[str, Any]:
    """Post-process locate card: store excerpts as handles, shrink payload."""
    if not card.get("ok"):
        return card
    topic = str(card.get("query") or "")
    targets = card.get("targets") or []
    if targets:
        governed = govern_targets(repo, targets, topic=topic)
        card["targets"] = governed
        # keep map.chunk_index in sync with handles
        idx = []
        for t in governed:
            idx.append(
                {
                    "file": t.get("file"),
                    "start_line": t.get("start_line"),
                    "end_line": t.get("end_line"),
                    "role": t.get("role"),
                    "why": t.get("why"),
                    "handle": t.get("handle"),
                    "status": t.get("status"),
                }
            )
        if isinstance(card.get("map"), dict):
            card["map"]["chunk_index"] = idx
        stubs = sum(1 for t in governed if t.get("status") == "already_in_session")
        card["session"] = {
            "governed": True,
            "handles": [t.get("handle") for t in governed if t.get("handle")],
            "already_in_session": stubs,
            "token_mode": token_mode(),
        }
        card["next"] = (
            (card.get("next") or "")
            + " Spans stored as handles — recall() to list; expand(handle) for body. "
            "Re-fetch of same hash returns already_in_session stub."
        )
    # drop bulky all_hits bodies if present under related
    rel = card.get("related")
    if isinstance(rel, dict) and token_mode() in {"savings", "save", "default", ""}:
        rel.pop("all_hits", None)
        rel.pop("notes", None)
        g = str(rel.get("graph") or "")
        cap = 400 if token_mode() in {"savings", "save"} else 1800
        if len(g) > cap:
            rel["graph"] = g[:cap] + "\n…[trimmed]"
        if not g or not rel.get("graph"):
            rel.pop("graph", None)
    try:
        from pipeline.token_meter import estimate_tokens

        card["token_estimate"] = estimate_tokens(json.dumps(card, default=str))
    except Exception:  # noqa: BLE001
        card["token_estimate"] = max(1, len(json.dumps(card, default=str)) // 4)
    return card
