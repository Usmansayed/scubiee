"""CLI: python -m trace_lab [--fixture PATH] [--out report.json] [--no-graphify]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scubiee context-tracing simulation")
    parser.add_argument("--fixture", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--no-graphify", action="store_true")
    parser.add_argument("--hot", type=float, default=0.45)
    parser.add_argument(
        "--vague",
        action="store_true",
        help="Run 20 vague-prompt map(BM25+vector)->PolyTrace eval",
    )
    parser.add_argument(
        "--seeded",
        action="store_true",
        help="Seeded head-to-head: PolyTrace vs EmbedPower (same seed+prompt)",
    )
    parser.add_argument(
        "--map-bakeoff",
        action="store_true",
        help="Compare BM25/graph/dense map algorithms then PolyTrace",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Diverse board: hard correctness poly vs poly_embed vs embed_power",
    )
    parser.add_argument(
        "--verify-hard",
        action="store_true",
        help="50 tough cases with large related-code must sets (verify_hard.json)",
    )
    parser.add_argument(
        "--director-bakeoff",
        action="store_true",
        help="BM25+Graphify → LLM Trace Director arms A/B/C vs polytrace",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit cases for bakeoffs / verify",
    )
    parser.add_argument(
        "--verify-prod",
        action="store_true",
        help="Production-like board: detailed paragraph + 2 seed code chunks",
    )
    parser.add_argument(
        "--director-arms",
        type=str,
        default="A,B,C",
        help="Comma arms for --director-bakeoff (e.g. A or A,B)",
    )
    args = parser.parse_args(argv)

    if args.verify_prod:
        from trace_lab.prod_eval import main_prod_cli

        main_prod_cli(out=args.out, fixture=args.fixture, hot=args.hot)
        return 0

    if args.director_bakeoff:
        from trace_lab.director_bakeoff import (
            dump_director_report,
            format_director_table,
            run_director_bakeoff,
        )

        arms = tuple(a.strip().upper() for a in args.director_arms.split(",") if a.strip())
        report = run_director_bakeoff(
            args.fixture,
            board_name="verify_hard.json",
            hot_threshold=args.hot,
            limit=args.limit,
            arms=arms,  # type: ignore[arg-type]
        )
        print(format_director_table(report))
        out = args.out or Path("docs/superpowers/plans/director-bakeoff-results.json")
        dump_director_report(report, out)
        print(f"wrote {out}")
        return 0

    if args.verify or args.verify_hard:
        from trace_lab.verify_board import (
            dump_verify_report,
            format_verify_table,
            run_verify,
        )

        board = "verify_hard.json" if args.verify_hard else "verify_board.json"
        report = run_verify(args.fixture, board_name=board, hot_threshold=args.hot)
        print(format_verify_table(report))
        default_out = (
            "docs/superpowers/plans/verify-hard-results.json"
            if args.verify_hard
            else "docs/superpowers/plans/verify-board-results.json"
        )
        out = args.out or Path(default_out)
        dump_verify_report(report, out)
        print(f"wrote {out}")
        return 0

    if args.map_bakeoff:
        from trace_lab.map_bakeoff import dump_map_report, format_map_table, run_map_bakeoff

        report = run_map_bakeoff(args.fixture, hot_threshold=args.hot, with_real_embeds=True)
        print(format_map_table(report))
        out = args.out or Path("docs/superpowers/plans/map-bakeoff-results.json")
        dump_map_report(report, out)
        print(f"wrote {out}")
        return 0

    if args.seeded:
        from trace_lab.seeded_compare import (
            dump_seeded_report,
            format_seeded_table,
            run_seeded_compare,
        )

        report = run_seeded_compare(args.fixture, hot_threshold=args.hot)
        print(format_seeded_table(report))
        out = args.out or Path("docs/superpowers/plans/seeded-poly-vs-embed-results.json")
        dump_seeded_report(report, out)
        print(f"wrote {out}")
        return 0

    if args.vague:
        from trace_lab.vague_eval import dump_vague_report, format_vague_table, run_vague_eval

        report = run_vague_eval(
            args.fixture,
            hot_threshold=args.hot,
            with_graphify=False,
            with_embed_power=True,
            require_real_embeds=False,
        )
        print(format_vague_table(report))
        out = args.out or Path("docs/superpowers/plans/vague-prompt-eval-results.json")
        dump_vague_report(report, out)
        print(f"wrote {out}")
        return 0

    from trace_lab.sim import dump_report, format_table, run_sim

    cache = Path(args.out).parent / "_trace_lab_cache" if args.out else None
    report = run_sim(
        args.fixture,
        cache_root=cache,
        with_graphify=not args.no_graphify,
        hot_threshold=args.hot,
    )
    print(format_table(report))
    if args.out:
        dump_report(report, args.out)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
