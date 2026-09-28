import json
from pathlib import Path

r = json.loads(
    Path(r"C:\Users\usman\Downloads\context-engine\docs\superpowers\plans\verify-hard-results.json").read_text(
        encoding="utf-8"
    )
)
print("board", r.get("board"), "n", r["n_cases"])
for k, v in r["summary"].items():
    print(
        f"{k:22} hard={v['correct']:2d}/{v['n']} acc={v['accuracy']:.3f} "
        f"rec={v['mean_recall_must']:.3f} prec={v['mean_precision_hot']:.3f} "
        f"F1={v['mean_f1']:.3f} nDCG={v['mean_ndcg']:.3f} "
        f"@5={v['mean_must_at_5']:.3f} @10={v['mean_must_at_10']:.3f} inv={v['total_inversions']}"
    )
