"""Difficult multi-suite comparison on existing size-ladder indexes.

Reuses out/size_ladder/indexes/{mix_450,mix_350,mix_300,mix_250,budget_c_300}
No re-embed — only harder evals for a real quality comparison.

Suites:
  hard_plus   — precise symbols / APIs (strict)
  soft_hard   — vague but single-correct-file
  paraphrase  — rewordings of known winners (vocab shift)
  adversarial — distractor-heavy / near-miss wording
  soft_v1     — original 52 soft (baseline)

Usage:
  python -u scripts/bench_difficult_compare.py
"""

from __future__ import annotations

import json
import math
import os
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))
sys.path.insert(0, str(ROOT / "scripts"))

from bench_mix_seq_ab import HARD, SOFT  # noqa: E402
from conductor.architectures import MultiArchConductor
from conductor.bm25_index import BM25Index
from conductor.conductor import ConductorConfig
from conductor.graphify_retriever import ChunkSpan, GraphifyChunkRetriever
from graphify.serve import _load_graph

from pipeline.embedder import Embedder
from pipeline.searcher import FaissDenseAdapter
from pipeline.store import PipelineStore
from pipeline.vectordb import VectorDatabase

REPO = ROOT / "testdata" / "frontend-mcp"
INDEX_ROOT = ROOT / "out" / "size_ladder" / "indexes"
OUT = ROOT / "out" / "difficult_compare"
ARMS = ("mix_450", "mix_350", "mix_300", "mix_250", "budget_c_300")

HARD_PLUS: list[dict[str, Any]] = [
    {"q": "probe_validation_form FormProbeResult ValidationRule", "relevant": ["form_probe.py"], "suite": "hard_plus"},
    {"q": "async def probe_validation_form session base_url", "relevant": ["form_probe.py"], "suite": "hard_plus"},
    {"q": "_fill_validation_form _extract_error_messages", "relevant": ["form_probe.py"], "suite": "hard_plus"},
    {"q": "handle_session_start perception_session_start", "relevant": ["handlers.py", "dispatch_registry.py"], "suite": "hard_plus"},
    {"q": "dispatch_registry register perception handlers wire", "relevant": ["dispatch_registry.py"], "suite": "hard_plus"},
    {"q": "make_envelope session start success payload", "relevant": ["envelope.py"], "suite": "hard_plus"},
    {"q": "BrowserSessionManager lock queue acquire", "relevant": ["browser_session_manager.py"], "suite": "hard_plus"},
    {"q": "perception_runtime headed browser inspiration scout", "relevant": ["perception_runtime.py"], "suite": "hard_plus"},
    {"q": "agent_guidance SESSION_NOT_FOUND unreachable recovery", "relevant": ["agent_guidance.py"], "suite": "hard_plus"},
    {"q": "tool_catalog perception_session_start perception_health", "relevant": ["tool_catalog.py"], "suite": "hard_plus"},
    {"q": "instructions spine health session_start observe verify", "relevant": ["instructions.py"], "suite": "hard_plus"},
    {"q": "session_store create session_id persist", "relevant": ["session_store.py", "session.py"], "suite": "hard_plus"},
    {"q": "handler_runner browser_session_busy wait_ms", "relevant": ["handler_runner.py", "observability.py"], "suite": "hard_plus"},
    {"q": "visual_capture screenshot_pack design regions", "relevant": ["visual_capture.py", "visual_feedback"], "suite": "hard_plus"},
    {"q": "implement_blocked evidence owed pack critical", "relevant": ["agent_summary", "coordinator", "tool_catalog"], "suite": "hard_plus"},
    {"q": "perception_auth_gate before browser actions", "relevant": ["auth"], "suite": "hard_plus"},
    {"q": "consistency_audit design_graph tokens spacing", "relevant": ["consistency"], "suite": "hard_plus"},
    {"q": "select_component_foundation integrate_component", "relevant": ["component", "foundation"], "suite": "hard_plus"},
    {"q": "inspiration_pulse look_lock chrome density", "relevant": ["inspiration", "pulse"], "suite": "hard_plus"},
    {"q": "full_diagnosis correlate console network", "relevant": ["diagnosis", "correlate", "full_diagnosis"], "suite": "hard_plus"},
]

SOFT_HARD: list[dict[str, Any]] = [
    {"q": "which file intentionally submits a bad form then a good one", "relevant": ["form_probe.py"], "suite": "soft_hard"},
    {"q": "which module returns the structured result after probing validation forms", "relevant": ["form_probe.py"], "suite": "soft_hard"},
    {"q": "where is the table that maps tool names to handler functions", "relevant": ["dispatch_registry.py"], "suite": "soft_hard"},
    {"q": "what wraps successful tool replies into a standard json shape", "relevant": ["envelope.py"], "suite": "soft_hard"},
    {"q": "where do we refuse to run two headed browser tools overlapping", "relevant": ["browser_session_manager.py", "handler_runner.py"], "suite": "soft_hard"},
    {"q": "file that spins a real chrome window for inspiration scraping", "relevant": ["perception_runtime.py"], "suite": "soft_hard"},
    {"q": "copy the agent must read when session_id is unknown", "relevant": ["agent_guidance.py"], "suite": "soft_hard"},
    {"q": "canonical list of perception mcp tool names for the agent", "relevant": ["tool_catalog.py", "tools.py"], "suite": "soft_hard"},
    {"q": "document that orders health then session then observe", "relevant": ["instructions.py", "agent_guidance.py"], "suite": "soft_hard"},
    {"q": "store that keeps session_id after start succeeds", "relevant": ["session_store.py", "handlers.py"], "suite": "soft_hard"},
    {"q": "code that decides the agent cannot edit until evidence is paid", "relevant": ["implement_blocked", "owed", "agent_summary"], "suite": "soft_hard"},
    {"q": "gate that blocks browser work until auth is satisfied", "relevant": ["auth", "gate"], "suite": "soft_hard"},
    {"q": "audit that checks screens against design tokens", "relevant": ["consistency"], "suite": "soft_hard"},
    {"q": "picker for a foundation component before integrate", "relevant": ["component", "foundation", "select_component"], "suite": "soft_hard"},
    {"q": "pulse that returns inspiration thumbs for chrome copy", "relevant": ["inspiration", "pulse"], "suite": "soft_hard"},
    {"q": "one-shot diagnosis bundling console and network", "relevant": ["diagnosis", "full_diagnosis"], "suite": "soft_hard"},
    {"q": "end the browser session when the agent is finished", "relevant": ["session_end", "handlers.py", "dispatch_registry.py"], "suite": "soft_hard"},
    {"q": "take multi-region screenshots for design review", "relevant": ["screenshot", "visual_capture", "visual_feedback"], "suite": "soft_hard"},
    {"q": "framework detector for react vs other stacks", "relevant": ["framework", "detect"], "suite": "soft_hard"},
    {"q": "seo visibility failure rules for a page", "relevant": ["seo"], "suite": "soft_hard"},
]

PARAPHRASE: list[dict[str, Any]] = [
    {"q": "kick off browsing and receive a session token back", "relevant": ["handlers.py", "dispatch_registry.py", "session_store.py", "tools.py"], "suite": "paraphrase"},
    {"q": "try the form incorrectly on purpose then correctly", "relevant": ["form_probe.py"], "suite": "paraphrase"},
    {"q": "instructions for when the browsing session vanished", "relevant": ["agent_guidance.py"], "suite": "paraphrase"},
    {"q": "catalog of tools and the step after health", "relevant": ["tool_catalog.py", "instructions.py", "tools.py"], "suite": "paraphrase"},
    {"q": "register start-session so the dispatcher can find it", "relevant": ["dispatch_registry.py"], "suite": "paraphrase"},
    {"q": "prevent concurrent tools from fighting over chrome", "relevant": ["browser_session_manager.py", "handler_runner.py", "lock"], "suite": "paraphrase"},
    {"q": "open a visible browser to look at design inspiration sites", "relevant": ["perception_runtime.py"], "suite": "paraphrase"},
    {"q": "box up the json when session creation works", "relevant": ["envelope.py", "handlers.py"], "suite": "paraphrase"},
    {"q": "cold-start order: health, session, then look at the page", "relevant": ["instructions.py", "tool_catalog.py", "agent_guidance.py"], "suite": "paraphrase"},
    {"q": "invalid submit learning then valid submit confirmation", "relevant": ["form_probe.py"], "suite": "paraphrase"},
    {"q": "site is down before we ever open a session", "relevant": ["agent_guidance.py", "health"], "suite": "paraphrase"},
    {"q": "look at the page once the session already exists", "relevant": ["observe", "handlers.py", "visual_capture"], "suite": "paraphrase"},
    {"q": "decide if the UI matches the design system", "relevant": ["consistency"], "suite": "paraphrase"},
    {"q": "choose a base component prior to wiring it in", "relevant": ["component", "foundation"], "suite": "paraphrase"},
    {"q": "grab network and console junk while debugging ui", "relevant": ["console", "network", "observ"], "suite": "paraphrase"},
    {"q": "cleanly tear down the browser when done", "relevant": ["session_end", "handlers.py"], "suite": "paraphrase"},
    {"q": "summary card that names the next mcp call", "relevant": ["agent_summary", "tool_catalog", "coordinator"], "suite": "paraphrase"},
    {"q": "do not edit the product until evidence pack is complete", "relevant": ["implement_blocked", "evidence", "owed"], "suite": "paraphrase"},
    {"q": "login wall before any browser automation", "relevant": ["auth", "gate"], "suite": "paraphrase"},
    {"q": "design screenshot bundle for visual review", "relevant": ["screenshot", "visual_feedback", "visual_capture"], "suite": "paraphrase"},
]

ADVERSARIAL: list[dict[str, Any]] = [
    # wording that could match SEO/resource/inspiration wrongly
    {"q": "session start is not about seo crawlability or robots", "relevant": ["handlers.py", "dispatch_registry.py", "session_store.py"], "suite": "adversarial"},
    {"q": "form probe is validation testing not figma spacing extractors", "relevant": ["form_probe.py"], "suite": "adversarial"},
    {"q": "browser lock is concurrency control not oauth token store", "relevant": ["browser_session_manager.py", "handler_runner.py"], "suite": "adversarial"},
    {"q": "inspiration headed browser not the resource icon search catalog", "relevant": ["perception_runtime.py"], "suite": "adversarial"},
    {"q": "envelope json wrapper not twitter card meta tags", "relevant": ["envelope.py"], "suite": "adversarial"},
    {"q": "agent summary next-tool card not dribbble result cards", "relevant": ["agent_summary", "tool_catalog", "coordinator"], "suite": "adversarial"},
    {"q": "consistency audit of live page tokens not citation readiness", "relevant": ["consistency"], "suite": "adversarial"},
    {"q": "component foundation select not pricing card registry blocks", "relevant": ["component", "foundation"], "suite": "adversarial"},
    {"q": "health then session spine not seo ai visibility analyzers", "relevant": ["instructions.py", "tool_catalog.py", "agent_guidance.py"], "suite": "adversarial"},
    {"q": "session disappeared recovery text not framework detect docs", "relevant": ["agent_guidance.py"], "suite": "adversarial"},
    {"q": "screenshot pack for design look not land-book navigation parsers", "relevant": ["screenshot", "visual_capture", "visual_feedback"], "suite": "adversarial"},
    {"q": "console network diagnosis not community lexicon for ecommerce cards", "relevant": ["console", "network", "diagnosis", "observ"], "suite": "adversarial"},
    {"q": "dispatch wire handlers not graphify fuzzy dedupe nodes", "relevant": ["dispatch_registry.py"], "suite": "adversarial"},
    {"q": "auth gate before browse not figma community api tokens", "relevant": ["auth", "gate"], "suite": "adversarial"},
    {"q": "end session tool not episode coordinator start alone", "relevant": ["session_end", "handlers.py", "dispatch_registry.py"], "suite": "adversarial"},
]


def all_suites() -> dict[str, list[dict[str, Any]]]:
    soft = [{**x, "suite": "soft_v1"} for x in SOFT]
    hard = [{**x, "suite": "hard_v1"} for x in HARD]
    return {
        "hard_v1": hard,
        "hard_plus": HARD_PLUS,
        "soft_hard": SOFT_HARD,
        "paraphrase": PARAPHRASE,
        "adversarial": ADVERSARIAL,
        "soft_v1": soft,
    }


def _hit(files: list[str], needles: list[str]) -> bool:
    blob = " ".join(f.replace("\\", "/").lower() for f in files)
    return any(n.lower() in blob for n in needles)


def _rank(files: list[str], needles: list[str]) -> int | None:
    for i, f in enumerate(files, 1):
        fl = f.replace("\\", "/").lower()
        if any(n.lower() in fl for n in needles):
            return i
    return None


def _dcg(rels: list[float]) -> float:
    return sum(r / math.log2(i + 2) for i, r in enumerate(rels))


def _ndcg(gains: list[float], k: int = 10) -> float:
    g = gains[:k]
    ideal = sorted(gains, reverse=True)[:k]
    idcg = _dcg(ideal)
    return 0.0 if idcg <= 0 else _dcg(g) / idcg


def load_conductor(arm: str) -> MultiArchConductor:
    base = INDEX_ROOT / arm
    store = PipelineStore(REPO.resolve(), base_dir=base / "store", vdb=VectorDatabase(root=base / "vectordb"))
    chunks = store.load_chunks()
    if not chunks:
        raise RuntimeError(f"missing index for {arm} under {base}")
    col = store.get_collection()
    if col is None:
        raise RuntimeError(f"missing collection for {arm}")
    texts = [c.enriched for c in chunks]
    files = [c.file.replace("\\", "/") for c in chunks]
    graph = PipelineStore(REPO.resolve()).base / "graph.json"
    G = _load_graph(str(graph))
    spans = [
        ChunkSpan(index=c.id, file=files[i], start_line=c.start_line, end_line=c.end_line)
        for i, c in enumerate(chunks)
    ]
    return MultiArchConductor(
        files=files,
        bm25=BM25Index(texts),
        dense=FaissDenseAdapter(col, n_chunks=len(chunks)),
        graph=GraphifyChunkRetriever(G, spans, depth=2),
        config=ConductorConfig(),
    )


def eval_suite(cond: MultiArchConductor, emb: Embedder, suite: list[dict[str, Any]]) -> dict[str, Any]:
    r1 = r5 = r10 = 0
    rr = 0.0
    ndcgs: list[float] = []
    fails: list[str] = []
    rows = []
    for item in suite:
        q, rel = item["q"], item["relevant"]
        t0 = time.perf_counter()
        qv = emb.embed_one(q, is_query=True)
        hits = cond.retrieve_R_plan(q, qv, top_k=10)
        ms = (time.perf_counter() - t0) * 1000
        files = [h.file.replace("\\", "/") for h in hits]
        ok1, ok5, ok10 = _hit(files[:1], rel), _hit(files[:5], rel), _hit(files[:10], rel)
        r1 += int(ok1)
        r5 += int(ok5)
        r10 += int(ok10)
        if not ok10:
            fails.append(q)
        rank = _rank(files, rel)
        if rank:
            rr += 1.0 / rank
        gains = [1.0 if _hit([f], rel) else 0.0 for f in files[:10]]
        ndcgs.append(_ndcg(gains, 10))
        rows.append({"q": q, "ok@5": ok5, "ok@10": ok10, "rank": rank, "ms": round(ms, 1)})
    n = max(len(suite), 1)
    return {
        "n": n,
        "recall_at_1": round(r1 / n, 4),
        "recall_at_5": round(r5 / n, 4),
        "recall_at_10": round(r10 / n, 4),
        "mrr": round(rr / n, 4),
        "ndcg_at_10": round(statistics.mean(ndcgs) if ndcgs else 0.0, 4),
        "failures": fails,
        "rows": rows,
    }


def main() -> int:
    os.environ.setdefault("CTX_EMBED_BATCH", "16")
    suites = all_suites()
    total_q = sum(len(v) for v in suites.values())
    print(f"arms={ARMS} suites={ {k: len(v) for k, v in suites.items()} } total_q={total_q}", flush=True)

    missing = [a for a in ARMS if not (INDEX_ROOT / a / "store").exists()]
    if missing:
        print(f"ERROR: missing indexes {missing}. Run bench_size_ladder.py first.", flush=True)
        return 2

    emb = Embedder(
        model="nomic-ai/CodeRankEmbed",
        cache_path=None,
        batch_size=int(os.environ.get("CTX_EMBED_BATCH", "16")),
        max_seq_length=512,
    )
    emb.embed_one("warmup", is_query=True)

    results: dict[str, Any] = {}
    for arm in ARMS:
        print(f"=== LOAD {arm} ===", flush=True)
        cond = load_conductor(arm)
        arm_res: dict[str, Any] = {}
        for name, suite in suites.items():
            print(f"  eval {name} n={len(suite)}", flush=True)
            arm_res[name] = eval_suite(cond, emb, suite)
            m = arm_res[name]
            print(
                f"    R@5={m['recall_at_5']} MRR={m['mrr']} fails={len(m['failures'])}/{m['n']}",
                flush=True,
            )
        # macro average across difficult suites (exclude soft_v1 from 'difficult macro')
        diff = [k for k in suites if k != "soft_v1"]
        arm_res["macro_difficult"] = {
            "recall_at_5": round(statistics.mean(arm_res[k]["recall_at_5"] for k in diff), 4),
            "mrr": round(statistics.mean(arm_res[k]["mrr"] for k in diff), 4),
            "recall_at_1": round(statistics.mean(arm_res[k]["recall_at_1"] for k in diff), 4),
        }
        # overall including soft
        all_k = list(suites)
        arm_res["macro_all"] = {
            "recall_at_5": round(statistics.mean(arm_res[k]["recall_at_5"] for k in all_k), 4),
            "mrr": round(statistics.mean(arm_res[k]["mrr"] for k in all_k), 4),
        }
        results[arm] = arm_res
        print(f"  MACRO_DIFFICULT R@5={arm_res['macro_difficult']['recall_at_5']} MRR={arm_res['macro_difficult']['mrr']}", flush=True)

    ranked = sorted(
        ARMS,
        key=lambda a: (
            -results[a]["macro_difficult"]["recall_at_5"],
            -results[a]["macro_difficult"]["mrr"],
            -results[a]["soft_v1"]["recall_at_5"],
        ),
    )
    base = "mix_450"

    lines = [
        "# Difficult multi-suite size comparison",
        "",
        "Indexes reused from size ladder (no re-embed). Harder suites stress locate quality.",
        "",
        f"Queries: { {k: len(v) for k, v in suites.items()} } (total {total_q})",
        "",
        "## Macro (difficult only: hard_v1 + hard_plus + soft_hard + paraphrase + adversarial)",
        "",
        "| Arm | Macro R@5 | Macro MRR | Soft52 R@5 | Soft52 MRR |",
        "|-----|-----------|-----------|------------|------------|",
    ]
    for a in ARMS:
        d = results[a]["macro_difficult"]
        s = results[a]["soft_v1"]
        lines.append(
            f"| {a} | {d['recall_at_5']} | {d['mrr']} | {s['recall_at_5']} | {s['mrr']} |"
        )

    lines += ["", "## Per-suite R@5", "", "| Arm | " + " | ".join(suites.keys()) + " |", "|-----|" + "|".join(["------"] * len(suites)) + "|"]
    for a in ARMS:
        cells = [a] + [str(results[a][k]["recall_at_5"]) for k in suites]
        lines.append("| " + " | ".join(cells) + " |")

    lines += ["", "## Per-suite MRR", "", "| Arm | " + " | ".join(suites.keys()) + " |", "|-----|" + "|".join(["------"] * len(suites)) + "|"]
    for a in ARMS:
        cells = [a] + [str(results[a][k]["mrr"]) for k in suites]
        lines.append("| " + " | ".join(cells) + " |")

    lines += [
        "",
        f"## Winner (difficult macro): **{ranked[0]}**",
        "",
        f"Order: {' > '.join(ranked)}",
        "",
        f"Δ macro R@5 vs {base}:",
    ]
    for a in ARMS:
        if a == base:
            continue
        d = results[a]["macro_difficult"]["recall_at_5"] - results[base]["macro_difficult"]["recall_at_5"]
        lines.append(f"- {a}: {d:+.4f}")

    # where mix_300 loses uniquely vs mix_450 on difficult
    lines += ["", "## mix_300 regressions vs mix_450 (ok@5 miss where 450 hit)", ""]
    reg = []
    for name, suite in suites.items():
        if name == "soft_v1":
            continue
        for i, item in enumerate(suite):
            a450 = results["mix_450"][name]["rows"][i]["ok@5"]
            a300 = results["mix_300"][name]["rows"][i]["ok@5"]
            if a450 and not a300:
                reg.append(f"- ({name}) {item['q']}")
    lines.extend(reg[:25] if reg else ["- (none)"])
    if len(reg) > 25:
        lines.append(f"- … +{len(reg) - 25} more")

    lines += [
        "",
        "## Verdict",
        "",
    ]
    d300 = results["mix_300"]["macro_difficult"]["recall_at_5"]
    d450 = results["mix_450"]["macro_difficult"]["recall_at_5"]
    if d300 >= d450 - 0.02:
        lines.append(
            f"**mix@300 holds under difficult load** (macro R@5 {d300} vs {d450}). "
            "Safe to ship smaller budget."
        )
    else:
        lines.append(
            f"**mix@300 drops under difficult load** (macro R@5 {d300} vs {d450}). "
            "Keep 450 or investigate regressions."
        )

    OUT.mkdir(parents=True, exist_ok=True)
    md = "\n".join(lines) + "\n"
    (OUT / "REPORT.md").write_text(md, encoding="utf-8")
    # strip rows for smaller json except failure counts
    slim = {}
    for a, arm_res in results.items():
        slim[a] = {
            k: ({kk: vv for kk, vv in v.items() if kk != "rows"} if isinstance(v, dict) else v)
            for k, v in arm_res.items()
        }
    (OUT / "report.json").write_text(
        json.dumps({"winner": ranked[0], "ranking": list(ranked), "results": slim}, indent=2),
        encoding="utf-8",
    )
    print(md, flush=True)
    print(f"wrote {OUT / 'REPORT.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
