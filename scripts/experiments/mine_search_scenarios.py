"""Mine SDK trial arms for CE search scenarios and context-waste patterns."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "superpowers" / "specs" / "_search_scenario_mine.json"

RUNS = [
    Path(r"C:\Users\usman\AppData\Local\Temp\ce_iso_trial\20260810T214438Z"),
    Path(r"C:\Users\usman\AppData\Local\Temp\ce_iso_trial\20260810T202752Z"),
    Path(r"C:\Users\usman\AppData\Local\Temp\ce_iso_trial\20260810T175138Z"),
    Path(r"C:\Users\usman\AppData\Local\Temp\ce_iso_trial\20260810T191029Z"),
    Path(r"C:\Users\usman\AppData\Local\Temp\ce_private_f4133b33991447e7ae34aa26737f6f38"),
]

STRUCT = re.compile(
    r"\b(who|caller|callee|wiring|dispatch|handler|uses|related|neighbor|"
    r"graph|call path|depends|imports?)\b",
    re.I,
)
MEANING = re.compile(
    r"\b(where|how|what|which|find|locate|handles|implements|session|"
    r"evidence|observe|verify|schema|tool|guidance|coordinator)\b",
    re.I,
)
SYMBOLISH = re.compile(r"^[A-Za-z_][\w\.]*$|PERCEPTION_|CODEBASE_|FEATURE_|env_flag")


def classify_query(q: str) -> str:
    q = (q or "").strip()
    if not q:
        return "empty"
    if STRUCT.search(q):
        return "structural"
    if len(q.split()) <= 3 and SYMBOLISH.search(q):
        return "symbolish"
    if MEANING.search(q) or len(q.split()) >= 4:
        return "soft_meaning"
    return "other"


def arm_files(root: Path) -> list[Path]:
    if root.is_file() and root.name.endswith("-arm.json"):
        return [root]
    if not root.exists():
        return []
    found = list(root.glob("*-arm.json"))
    found += [p for p in root.rglob("*-arm.json") if p not in found]
    return found


def main() -> None:
    seen: set[str] = set()
    rows: list[dict] = []
    for root in RUNS:
        for ap in arm_files(root):
            key = str(ap.resolve())
            if key in seen:
                continue
            seen.add(key)
            try:
                arm = json.loads(ap.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                continue
            name = str(arm.get("name") or ap.stem)
            calls = [c for c in (arm.get("tool_calls") or []) if isinstance(c, dict)]
            searches = [
                c for c in calls if c.get("name") == "search" and c.get("provider")
            ]
            mcp_reads = [
                c for c in calls if c.get("name") == "read" and c.get("provider")
            ]
            nat_reads = [
                c
                for c in calls
                if c.get("name") == "read" and not c.get("provider")
            ]
            scenarios: Counter[str] = Counter()
            fetch_true = 0
            k_vals: Counter[str] = Counter()
            modes: Counter[str] = Counter()
            queries: list[str] = []
            for c in searches:
                args = c.get("arguments") or {}
                if not isinstance(args, dict):
                    args = {}
                q = str(args.get("query") or "")
                scenarios[classify_query(q)] += 1
                if args.get("fetch") is True:
                    fetch_true += 1
                k_vals[str(args.get("k", "default"))] += 1
                modes[str(args.get("mode", "default"))] += 1
                queries.append(q[:160])

            norms = [" ".join(q.lower().split()) for q in queries if q.strip()]
            dup_q = len(norms) - len(set(norms))
            u = arm.get("usage") or {}
            wt = arm.get("work_tokens")
            if wt is None and u.get("input_tokens") is not None:
                wt = (u.get("input_tokens") or 0) + (u.get("output_tokens") or 0)

            # estimate returned body pressure for mcp reads (nav)
            read_targets = []
            for c in mcp_reads:
                args = c.get("arguments") or {}
                if isinstance(args, dict):
                    read_targets.append(
                        str(args.get("target") or args.get("path") or "")[:120]
                    )
            uniq_read = len(set(t for t in read_targets if t))
            dup_read = len(read_targets) - uniq_read

            rows.append(
                {
                    "run": root.name,
                    "path": str(ap),
                    "arm": name,
                    "work_tokens": wt,
                    "complete": arm.get("work_complete"),
                    "quality": arm.get("quality_pass"),
                    "n_search": len(searches),
                    "n_mcp_read": len(mcp_reads),
                    "n_nat_read": len(nat_reads),
                    "scenarios": dict(scenarios),
                    "fetch_true": fetch_true,
                    "k_vals": dict(k_vals),
                    "modes": dict(modes),
                    "dup_queries": dup_q,
                    "uniq_queries": len(set(norms)),
                    "mcp_read_dup_targets": dup_read,
                    "mcp_read_uniq_targets": uniq_read,
                    "sample_queries": queries[:20],
                    "mcp_names": Counter(
                        str(c.get("name") or "")
                        for c in calls
                        if c.get("provider")
                    ).most_common(12),
                    "native_names": Counter(
                        str(c.get("name") or "")
                        for c in calls
                        if not c.get("provider")
                    ).most_common(12),
                }
            )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"wrote {OUT} arms={len(rows)}")
    for r in rows:
        print(
            f"\n{r['run']} / {r['arm']} wt={r['work_tokens']} "
            f"complete={r['complete']} search={r['n_search']} "
            f"mcp_read={r['n_mcp_read']} nat_read={r['n_nat_read']} "
            f"dup_q={r['dup_queries']} fetch_true={r['fetch_true']}"
        )
        print("  scenarios", r["scenarios"])
        print("  modes", r["modes"], "k", r["k_vals"])
        print("  mcp", r["mcp_names"])
        for q in r["sample_queries"][:8]:
            print("   Q:", q)


if __name__ == "__main__":
    main()
