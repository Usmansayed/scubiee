"""Context Agent loop: Qwen3-1.7B orchestrates retrieval → context pack."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from pipeline.context_agent.llm_llama import LlamaCppClient
from pipeline.context_agent.prompts import SYSTEM_PROMPT, USER_TEMPLATE
from pipeline.context_agent.tools import dispatch_tool, dump_tool_result

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "packages") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages"))


_JSON_RE = re.compile(r"\{[\s\S]*\}")


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    # Strip Qwen thinking blocks if present
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.I).strip()
    cleaned = re.sub(r"```(?:json)?\s*([\s\S]*?)```", r"\1", cleaned).strip()
    candidates = [cleaned]
    m = _JSON_RE.search(cleaned)
    if m:
        candidates.append(m.group(0))
    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    # Trailing garbage: find first { to last }
    if "{" in cleaned and "}" in cleaned:
        try:
            return json.loads(cleaned[cleaned.index("{") : cleaned.rindex("}") + 1])
        except json.JSONDecodeError:
            return None
    return None


def _pack_from_trace(
    query: str,
    steps: list[dict[str, Any]],
    done: dict[str, Any] | None,
) -> dict[str, Any]:
    files: list[str] = []
    snippets: list[dict[str, Any]] = []
    for s in steps:
        res = s.get("result") or {}
        if res.get("tool") == "search_code":
            for h in res.get("hits") or []:
                f = h.get("file")
                if f and f not in files:
                    files.append(f)
                snippets.append({"kind": "search_hit", **h})
        elif res.get("tool") == "grep_code":
            for h in res.get("hits") or []:
                f = h.get("file")
                if f and f not in files:
                    files.append(f)
        elif res.get("tool") in {"query_graph", "get_node", "get_neighbors"}:
            snippets.append(
                {
                    "kind": res.get("tool"),
                    "text": (res.get("text") or "")[:2000],
                }
            )
        elif res.get("tool") == "read_span":
            f = res.get("path")
            if f and f not in files:
                files.append(f)
            snippets.append(
                {
                    "kind": "span",
                    "path": f,
                    "text": res.get("text") if isinstance(res.get("text"), str) else str(res)[:800],
                }
            )
    if done:
        for f in done.get("files") or []:
            if f and f not in files:
                files.append(str(f))
    return {
        "ok": True,
        "query": query,
        "summary": (done or {}).get("summary") or "",
        "notes": (done or {}).get("notes") or [],
        "files": files[:12],
        "snippets": snippets[:16],
        "steps": len(steps),
        "tool_trace": [
            {"tool": s.get("tool"), "args": s.get("args"), "ok": (s.get("result") or {}).get("ok", True)}
            for s in steps
        ],
    }


def gather_context(
    query: str,
    *,
    repo: Path | str | None = None,
    max_rounds: int = 5,
    llm: LlamaCppClient | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Run the Context Agent and return a context pack for the main coding agent."""
    repo_p = Path(repo or os.environ.get("CTX_REPO") or ".").resolve()
    os.environ.setdefault("CTX_REPO", str(repo_p))

    from pipeline.daemon import ensure_daemon
    from pipeline.client import EngineClient

    ensure_daemon(repo_p, force_if_hung=False)
    try:
        EngineClient().open_repo(str(repo_p), wait=True)
    except Exception:  # noqa: BLE001
        pass

    client = llm or LlamaCppClient()
    if not client.healthy():
        return {
            "ok": False,
            "error": f"llama.cpp not healthy at {client.base}",
            "hint": "Run scripts/context_agent/start_llama_qwen.ps1",
        }

    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_TEMPLATE.format(query=query)},
    ]
    steps: list[dict[str, Any]] = []
    done_obj: dict[str, Any] | None = None

    for round_i in range(max(1, max_rounds)):
        if verbose:
            print(f"[context-agent] round {round_i + 1}/{max_rounds}", flush=True)
        raw = client.chat(messages)
        if verbose:
            print(f"[context-agent] model: {raw[:240]!r}", flush=True)
        obj = _extract_json(raw)
        if not obj:
            # Nudge once
            messages.append({"role": "assistant", "content": raw[:800]})
            messages.append(
                {
                    "role": "user",
                    "content": 'Invalid. Reply with ONLY JSON: {"tool":"...","args":{...}} or {"done":true,"summary":"...","files":[...]}',
                }
            )
            continue

        if obj.get("done") is True or obj.get("action") == "done":
            done_obj = obj
            break

        tool = str(obj.get("tool") or obj.get("name") or "").strip()
        args = obj.get("args") if isinstance(obj.get("args"), dict) else {}
        if not tool:
            # Maybe they returned done fields without done:true
            if obj.get("files") or obj.get("summary"):
                done_obj = {**obj, "done": True}
                break
            messages.append({"role": "assistant", "content": json.dumps(obj)})
            messages.append(
                {
                    "role": "user",
                    "content": 'Need "tool" or done:true. Example: {"tool":"search_code","args":{"query":"..."}}',
                }
            )
            continue

        result = dispatch_tool(repo_p, tool, args)
        steps.append({"tool": tool, "args": args, "result": result})
        if verbose:
            print(f"[context-agent] {tool} -> ok={result.get('ok')}", flush=True)

        messages.append({"role": "assistant", "content": json.dumps({"tool": tool, "args": args})})
        messages.append(
            {
                "role": "user",
                "content": (
                    f"TOOL_RESULT {tool}:\n{dump_tool_result(result)}\n\n"
                    "Next JSON tool call, or {\"done\":true,\"summary\":\"...\",\"files\":[...]}."
                ),
            }
        )

    pack = _pack_from_trace(query, steps, done_obj)
    pack["repo"] = str(repo_p)
    pack["model"] = client.model
    pack["llama_url"] = client.base
    if not done_obj and steps:
        pack["summary"] = pack.get("summary") or "Stopped at max rounds; pack built from tool results."
    elif not steps and not done_obj:
        pack["ok"] = False
        pack["error"] = "model produced no valid tool calls"
    return pack


def run_cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Context Agent (Qwen3-1.7B + CE tools)")
    p.add_argument("query", nargs="?", help="Natural language locate/gather request")
    p.add_argument("--repo", default=os.environ.get("CTX_REPO") or ".", help="Repo path")
    p.add_argument("--rounds", type=int, default=5, help="Max tool rounds")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--out", default="", help="Write pack JSON to path")
    args = p.parse_args(argv)
    if not args.query:
        p.error("query required")
    pack = gather_context(
        args.query,
        repo=args.repo,
        max_rounds=args.rounds,
        verbose=args.verbose,
    )
    text = json.dumps(pack, indent=2, default=str)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0 if pack.get("ok") else 2


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
