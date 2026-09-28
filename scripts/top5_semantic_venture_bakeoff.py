"""Bakeoff: Top-5 semantic venture arms vs composite on seed-hard cases.

Seed-hard = composite_v1 misses ≥1 must-id at hot threshold.
Boards: verify_hard + verify_ood_v2 + verify_prod (filtered).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from trace_lab.cases import default_fixture_root
from trace_lab.metrics import evaluate
from trace_lab.sim import HOT_THRESHOLD
from trace_lab.strategies import compile_bundle
from trace_lab.vague_eval import hot_set, prompt_to_case
from trace_lab.verify_board import _correct, _must_at_k

BOARDS = (
    "verify_hard.json",
    "verify_ood_v2.json",
    "verify_prod.json",
    "verify_ood_v10_realistic.json",
)

ARMS = (
    "composite_v1",
    "venture_propose_verify",
    "venture_propose_path1",
    "venture_semantic_frontier",
    "venture_multiview",
    "venture_trace_state",
    "venture_learned_heat",
    "venture_propose_plus_frontier",
    "semantic_tracer_fuse",
    "poly_embed",
    "hyb_fuse_demote_noise_plus",
)


def _load_cases(root: Path, board: str) -> list[dict[str, Any]]:
    path = root / board
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "cases" in data:
        return list(data["cases"])
    if isinstance(data, list):
        return data
    return []


def run(*, hot: float = HOT_THRESHOLD) -> dict[str, Any]:
    t0 = time.time()
    root = default_fixture_root().resolve()
    nodes, graph, lex, tracers = compile_bundle(
        root, with_graphify=True, with_embed_power=True, require_real_embeds=True
    )
    present_arms = [a for a in ARMS if a in tracers]
    rows: list[dict[str, Any]] = []
    seed_hard_ids: list[str] = []

    for board in BOARDS:
        for raw in _load_cases(root, board):
            try:
                gold = prompt_to_case(raw) if "prompt" in raw or "must" in raw else None
            except Exception:  # noqa: BLE001
                gold = None
            if gold is None:
                # classic GoldCase json
                from trace_lab.cases import load_case
                # skip non-prompt boards that aren't files
                continue
            if "composite_v1" not in tracers:
                continue
            hm0 = tracers["composite_v1"](gold, nodes, graph, lex)
            hot0 = hot_set(hm0, hot)
            miss = sorted(gold.must_ids - hot0)
            is_hard = len(miss) >= 1
            if is_hard:
                seed_hard_ids.append(f"{board}:{gold.id}")

            arm_out: dict[str, Any] = {}
            for name in present_arms:
                hm = tracers[name](gold, nodes, graph, lex)
                met = evaluate(hm, gold, nodes, hot_threshold=hot)
                ids = hot_set(hm, hot)
                ver = _correct(ids, gold)
                arm_out[name] = {
                    **ver,
                    "f1": met.f1,
                    "recall_must": met.recall_must,
                    "precision_hot": met.precision_hot,
                    "must_at_10": round(_must_at_k(hm.ranked_ids(), gold.must_ids, 10), 4),
                    "n_hot": len(ids),
                    "missing_must": [m.rsplit("::", 1)[-1] for m in sorted(gold.must_ids - ids)],
                    "recovered": [m.rsplit("::", 1)[-1] for m in sorted(set(miss) & ids)],
                    "proposed": int((hm.extra or {}).get("proposed_admitted") or 0),
                }
            rows.append(
                {
                    "board": board,
                    "id": gold.id,
                    "family": raw.get("family"),
                    "seed_hard": is_hard,
                    "composite_miss": [m.rsplit("::", 1)[-1] for m in miss],
                    "arms": arm_out,
                }
            )

    def summarize(subset: list[dict[str, Any]]) -> dict[str, Any]:
        out = {}
        for name in present_arms:
            present = [r for r in subset if name in r["arms"]]
            if not present:
                continue
            n = len(present)
            n_ok = sum(1 for r in present if r["arms"][name]["correct"])
            soft = {
                k: round(sum(r["arms"][name][k] for r in present) / n, 4)
                for k in ("f1", "recall_must", "precision_hot", "must_at_10", "n_hot")
            }
            base_rec = sum(r["arms"]["composite_v1"]["recall_must"] for r in present) / n
            out[name] = {
                "n": n,
                "accuracy": round(n_ok / n, 4),
                "mean_f1": soft["f1"],
                "mean_recall_must": soft["recall_must"],
                "mean_precision_hot": soft["precision_hot"],
                "mean_must_at_10": soft["must_at_10"],
                "mean_n_hot": soft["n_hot"],
                "delta_must_vs_composite": round(soft["recall_must"] - base_rec, 4),
                "failed": [f"{r['board']}:{r['id']}" for r in present if not r["arms"][name]["correct"]],
            }
        return out

    all_sum = summarize(rows)
    hard_rows = [r for r in rows if r["seed_hard"]]
    hard_sum = summarize(hard_rows)

    # Crown: maximize delta must on seed-hard, then F1, then precision
    ranked = sorted(
        hard_sum.items(),
        key=lambda kv: (
            -kv[1]["delta_must_vs_composite"],
            -kv[1]["mean_recall_must"],
            -kv[1]["mean_f1"],
            -kv[1]["mean_precision_hot"],
        ),
    )
    winner = ranked[0][0] if ranked else None

    return {
        "elapsed_s": round(time.time() - t0, 2),
        "boards": list(BOARDS),
        "arms": present_arms,
        "n_cases": len(rows),
        "n_seed_hard": len(hard_rows),
        "seed_hard_ids": seed_hard_ids,
        "summary_all": all_sum,
        "summary_seed_hard": hard_sum,
        "ranked_seed_hard": [a for a, _ in ranked],
        "winner_seed_hard": winner,
        "rows": rows,
    }


def write_report(result: dict[str, Any]) -> tuple[Path, Path]:
    docs = Path("docs/superpowers/plans")
    docs.mkdir(parents=True, exist_ok=True)
    jp = docs / "2026-09-06-top5-semantic-venture.json"
    mp = docs / "2026-09-06-top5-semantic-venture.md"
    slim = {k: v for k, v in result.items() if k != "rows"}
    jp.write_text(
        json.dumps(
            {
                **slim,
                "per_case_hard": [
                    {
                        "id": f"{r['board']}:{r['id']}",
                        "composite_miss": r["composite_miss"],
                        "arms": {
                            n: {
                                "must": a["recall_must"],
                                "f1": a["f1"],
                                "recovered": a["recovered"],
                                "missing": a["missing_must"],
                                "n_hot": a["n_hot"],
                            }
                            for n, a in r["arms"].items()
                        },
                    }
                    for r in result["rows"]
                    if r["seed_hard"]
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    lines = [
        "# Top-5 semantic tracer venture bakeoff",
        "",
        f"Boards: {', '.join(result['boards'])} · cases {result['n_cases']} · "
        f"**seed-hard {result['n_seed_hard']}** · elapsed {result['elapsed_s']}s",
        "",
        f"**Stack gate:** `{result.get('stack')}`",
        "",
        f"**Winner on seed-hard (Δ must-recall vs composite):** `{result['winner_seed_hard']}`",
        "",
        "Implements architectures from `SCUBIEE_TOP5_SEMANTIC_TRACER_EXPERIMENTS.md` "
        "(A1 propose+verify, A2 frontier, A3 multiview, A4 trace-state, A5 learned proxy, A6 combo).",
        "",
        "## Seed-hard summary (primary)",
        "",
        "| Arm | Δ must | Must | F1 | Prec | Must@10 | Mean hot | Acc |",
        "|-----|--------|------|----|------|---------|----------|-----|",
    ]
    for name in result["ranked_seed_hard"]:
        st = result["summary_seed_hard"][name]
        lines.append(
            f"| `{name}` | {st['delta_must_vs_composite']:+.4f} | {st['mean_recall_must']:.4f} | "
            f"{st['mean_f1']:.4f} | {st['mean_precision_hot']:.4f} | {st['mean_must_at_10']:.4f} | "
            f"{st['mean_n_hot']:.1f} | {st['accuracy']:.4f} |"
        )
    lines += [
        "",
        "## All cases summary",
        "",
        "| Arm | Must | F1 | Prec | Acc |",
        "|-----|------|----|------|-----|",
    ]
    for name, st in sorted(
        result["summary_all"].items(),
        key=lambda kv: (-kv[1]["mean_recall_must"], -kv[1]["mean_f1"]),
    ):
        lines.append(
            f"| `{name}` | {st['mean_recall_must']:.4f} | {st['mean_f1']:.4f} | "
            f"{st['mean_precision_hot']:.4f} | {st['accuracy']:.4f} |"
        )
    lines += ["", "## Seed-hard per case (recovery)", ""]
    for r in result["rows"]:
        if not r["seed_hard"]:
            continue
        lines.append(f"### `{r['board']}:{r['id']}` miss={r['composite_miss']}")
        for name in (
            "composite_v1",
            result["winner_seed_hard"],
            "venture_propose_verify",
            "venture_propose_plus_frontier",
        ):
            if name not in r["arms"]:
                continue
            a = r["arms"][name]
            lines.append(
                f"- `{name}`: must={a['recall_must']:.2f} recovered={a['recovered']} "
                f"still_missing={a['missing_must']} hot={a['n_hot']}"
            )
        lines.append("")
    mp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jp, mp


def main() -> int:
    from trace_lab.vague_eval import prompt_to_case
    import importlib.util

    # Preflight: refuse to crown winners if stack is dead
    print("PREFLIGHT …", flush=True)
    fix_root = default_fixture_root().resolve()
    from pathlib import Path as P
    import json as _json

    spec = importlib.util.spec_from_file_location(
        "venture_preflight",
        P(__file__).resolve().parents[1] / "scripts" / "venture_preflight.py",
    )
    assert spec and spec.loader
    vp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vp)
    # Custom: FAISS gate on PRODUCT repo (indexed), EmbedField on fixture
    rep = vp.preflight(fixture_root=fix_root, require_faiss=False)
    from trace_lab.semantic_venture import product_faiss_ok

    prod = product_faiss_ok(P(__file__).resolve().parents[1])
    rep["faiss_product_repo"] = prod
    if not prod.get("ok"):
        rep["blockers"] = list(rep.get("blockers") or []) + ["product FAISS returned 0 hits"]
    if not rep.get("dml_live"):
        rep["blockers"] = list(rep.get("blockers") or []) + ["DML not live on Embedder"]
    if not rep.get("field_ok"):
        rep["blockers"] = list(rep.get("blockers") or []) + ["EmbedField not real"]
    rep["ok"] = len(rep.get("blockers") or []) == 0
    (P("docs/superpowers/plans") / "2026-09-06-venture-preflight.json").write_text(
        _json.dumps(rep, indent=2), encoding="utf-8"
    )
    print(_json.dumps({k: rep[k] for k in ("ok", "blockers", "field_backend", "embed_device", "dml_live", "faiss_product_repo")}, indent=2), flush=True)
    if not rep["ok"]:
        print("ABORT: underlying stack not healthy — not running bakeoff", flush=True)
        return 2

    t0 = time.time()
    root = fix_root
    print(f"compile_bundle {root} require_real_embeds=True …", flush=True)
    nodes, graph, lex, tracers = compile_bundle(
        root, with_graphify=True, with_embed_power=True, require_real_embeds=True
    )
    present_arms = [a for a in ARMS if a in tracers]
    print(f"arms={present_arms}", flush=True)

    rows: list[dict[str, Any]] = []
    seed_hard_ids: list[str] = []
    hot = HOT_THRESHOLD

    for board in BOARDS:
        path = root / board
        if not path.is_file():
            print(f"skip missing {board}", flush=True)
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        raw_cases = data["cases"] if isinstance(data, dict) else data
        for raw in raw_cases:
            try:
                if "seed" in raw and "must" in raw and "query" in raw and "prompt" not in raw:
                    # file-shaped gold — write temp? use GoldCase constructor
                    from trace_lab.types import GoldCase, GoldRef

                    def ref(d):
                        return GoldRef(file=d["file"], symbol=d["symbol"])

                    gold = GoldCase(
                        id=str(raw["id"]),
                        title=str(raw.get("title") or raw["id"]),
                        query=str(raw["query"]),
                        seed=ref(raw["seed"]),
                        must=[ref(x) for x in raw.get("must") or []],
                        should=[ref(x) for x in raw.get("should") or []],
                        must_not=[ref(x) for x in raw.get("must_not") or []],
                        gold_rank=list(raw.get("gold_rank") or []),
                    )
                else:
                    gold = prompt_to_case(raw)
            except Exception as e:  # noqa: BLE001
                print(f"  skip case parse {raw.get('id')}: {e}", flush=True)
                continue
            if gold.seed.id not in nodes:
                print(f"  skip missing seed {gold.id}", flush=True)
                continue

            hm0 = tracers["composite_v1"](gold, nodes, graph, lex)
            hot0 = hot_set(hm0, hot)
            miss = sorted(gold.must_ids - hot0)
            is_hard = len(miss) >= 1
            if is_hard:
                seed_hard_ids.append(f"{board}:{gold.id}")
            print(
                f"[{board}:{gold.id}] hard={is_hard} miss={[m.split('::')[-1] for m in miss]}",
                flush=True,
            )

            arm_out: dict[str, Any] = {}
            for name in present_arms:
                hm = tracers[name](gold, nodes, graph, lex)
                met = evaluate(hm, gold, nodes, hot_threshold=hot)
                ids = hot_set(hm, hot)
                ver = _correct(ids, gold)
                arm_out[name] = {
                    **ver,
                    "f1": met.f1,
                    "recall_must": met.recall_must,
                    "precision_hot": met.precision_hot,
                    "must_at_10": round(_must_at_k(hm.ranked_ids(), gold.must_ids, 10), 4),
                    "n_hot": len(ids),
                    "missing_must": [m.rsplit("::", 1)[-1] for m in sorted(gold.must_ids - ids)],
                    "recovered": [m.rsplit("::", 1)[-1] for m in sorted(set(miss) & ids)],
                    "proposed": int((hm.extra or {}).get("proposed_admitted") or 0),
                }
            rows.append(
                {
                    "board": board,
                    "id": gold.id,
                    "family": raw.get("family"),
                    "seed_hard": is_hard,
                    "composite_miss": [m.rsplit("::", 1)[-1] for m in miss],
                    "arms": arm_out,
                }
            )

    def summarize(subset: list[dict[str, Any]]) -> dict[str, Any]:
        out = {}
        for name in present_arms:
            present = [r for r in subset if name in r["arms"]]
            if not present:
                continue
            n = len(present)
            n_ok = sum(1 for r in present if r["arms"][name]["correct"])
            soft = {
                k: round(sum(r["arms"][name][k] for r in present) / n, 4)
                for k in ("f1", "recall_must", "precision_hot", "must_at_10", "n_hot")
            }
            base_rec = (
                sum(r["arms"]["composite_v1"]["recall_must"] for r in present) / n
                if "composite_v1" in present_arms
                else 0.0
            )
            out[name] = {
                "n": n,
                "accuracy": round(n_ok / n, 4),
                "mean_f1": soft["f1"],
                "mean_recall_must": soft["recall_must"],
                "mean_precision_hot": soft["precision_hot"],
                "mean_must_at_10": soft["must_at_10"],
                "mean_n_hot": soft["n_hot"],
                "delta_must_vs_composite": round(soft["recall_must"] - base_rec, 4),
                "failed": [
                    f"{r['board']}:{r['id']}"
                    for r in present
                    if not r["arms"][name]["correct"]
                ],
            }
        return out

    hard_rows = [r for r in rows if r["seed_hard"]]
    hard_sum = summarize(hard_rows)
    all_sum = summarize(rows)
    ranked = sorted(
        hard_sum.items(),
        key=lambda kv: (
            -kv[1]["delta_must_vs_composite"],
            -kv[1]["mean_recall_must"],
            -kv[1]["mean_f1"],
            -kv[1]["mean_precision_hot"],
        ),
    )
    result = {
        "elapsed_s": round(time.time() - t0, 2),
        "boards": list(BOARDS),
        "arms": present_arms,
        "n_cases": len(rows),
        "n_seed_hard": len(hard_rows),
        "seed_hard_ids": seed_hard_ids,
        "summary_all": all_sum,
        "summary_seed_hard": hard_sum,
        "ranked_seed_hard": [a for a, _ in ranked],
        "winner_seed_hard": ranked[0][0] if ranked else None,
        "stack": {
            "preflight_ok": True,
            "field_backend": rep.get("field_backend"),
            "field_dim": rep.get("field_dim"),
            "embed_device": rep.get("embed_device"),
            "dml_live": rep.get("dml_live"),
            "faiss_product_hits": (rep.get("faiss_product_repo") or {}).get("n_hits"),
            "require_real_embeds": True,
            "prior_run_invalid": "2026-09-06-top5-semantic-venture.md before stack gate — FAISS helper was broken (mode= keyword swallowed all hits)",
        },
        "rows": rows,
    }
    jp, mp = write_report(result)
    print(f"winner={result['winner_seed_hard']}", flush=True)
    print(f"Wrote {mp}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
