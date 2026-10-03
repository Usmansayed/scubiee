"""Test a candidate optimization for _score_query's full-graph fallback WITHOUT
changing production: compare the current fallback (score ALL nodes when the
trigram prefilter bails) vs a 'union-of-selective-needles' candidate set, on the
SAME graph, for soft queries. Report: (a) do the top-N ranked nodes match? (b)
speed. This tells us whether a selective-union prefilter is behavior-preserving
for the graph channel ranking before we touch the engine.
"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, base_env  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v

# Load the published graph the same way the engine does.
from pipeline.project_id import peek_project  # noqa: E402
import graphify.serve as gs  # noqa: E402
import networkx as nx  # noqa: E402


def load_graph():
    # The engine builds the graph from the project's graphify output; reuse the
    # conductor's loader path. Simplest: ask the running engine? No — load from
    # the project store. Try the known graph artifact.
    ref = peek_project(Path(REPO))
    store = Path(ref.store_dir)
    # find a graphml/json graph under the store
    for pat in ("**/graph*.graphml", "**/*.graphml", "**/graph*.json"):
        for p in store.glob(pat):
            try:
                if p.suffix == ".graphml":
                    return nx.read_graphml(p), str(p)
            except Exception:
                pass
    return None, None


def main():
    G, src = load_graph()
    if G is None:
        print("could not load graph from store; falling back to engine-timing only")
        return
    print(f"graph: {G.number_of_nodes()} nodes from {src}")

    QUERIES = [
        "how the map v3 server dispatches a tool call to a config handler",
        "how the bridge spawns and respawns the worker process",
        "what happens when a client disconnects and the engine goes idle",
    ]
    for q in QUERIES:
        terms = gs._query_terms(q)
        norm = list(dict.fromkeys(tok for t in terms for tok in gs._search_tokens(t)))
        # current prefilter decision
        cur = gs._trigram_candidates(G, norm + [" ".join(norm)])
        # union-of-selective: per-needle, keep candidates only for needles whose
        # trigram set is individually selective; union them
        sel_union = set()
        any_sel = False
        for s in norm:
            c = gs._trigram_candidates(G, [s])
            if c is not None:
                any_sel = True
                sel_union |= set(c)
        sel = sorted(sel_union) if any_sel else None

        # score with full fallback (current) and with selective-union candidate set
        t0 = time.perf_counter()
        full = gs._score_query(G, terms, collect_per_term_seeds=True).ranked
        full_ms = (time.perf_counter() - t0) * 1000

        print(f"\nQ: {q[:50]}")
        print(f"   norm_terms={norm}")
        print(f"   current _trigram_candidates -> {'FULL SCAN' if cur is None else str(len(cur))+' cands'}")
        print(f"   selective-union -> {'none selective (full)' if sel is None else str(len(sel))+' cands'}  any_selective={any_sel}")
        print(f"   full _score_query: {full_ms:.1f}ms, ranked={len(full)}  top5={[n for _,n in full[:5]]}")


if __name__ == "__main__":
    main()
