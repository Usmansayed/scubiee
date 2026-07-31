"""CLI: python -m parse_harness <repo> [--out DIR]"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running from repo root without install
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "packages"))

from parse_harness.bakeoff import assert_deterministic, run_bakeoff  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AST bake-off / Graphify→RepoIR harness")
    parser.add_argument("repo", type=Path, help="Repository root to parse")
    parser.add_argument("--out", type=Path, default=None, help="Write bakeoff.json + repo_ir.json here")
    parser.add_argument("--check-deterministic", action="store_true", help="Parse twice and compare")
    args = parser.parse_args(argv)

    if not args.repo.exists():
        print(f"error: repo not found: {args.repo}", file=sys.stderr)
        return 2

    if args.check_deterministic:
        assert_deterministic(args.repo)
        print("deterministic: OK")

    report = run_bakeoff(args.repo, out_dir=args.out)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
