import json
from collections import Counter
from pathlib import Path

r = json.loads(
    Path(r"C:\Users\usman\Downloads\context-engine\docs\superpowers\plans\verify-hard-results.json").read_text(
        encoding="utf-8"
    )
)
for arm in ["polytrace", "poly_embed", "embed_power_oracle"]:
    rows = [c["arms"][arm] for c in r["cases"]]
    n = len(rows)

    def avg(k):
        return sum(x[k] for x in rows) / n

    only_m = sum(1 for x in rows if x["missing_must"] and not x["forbidden_hot"])
    only_f = sum(1 for x in rows if x["forbidden_hot"] and not x["missing_must"])
    both = sum(1 for x in rows if x["missing_must"] and x["forbidden_hot"])
    print(arm)
    print(
        f"  hard-correct {sum(x['correct'] for x in rows)}/{n}  "
        f"meanF1={avg('f1'):.3f}  mean_recall_must={avg('recall_must'):.3f}  "
        f"mean_prec_hot={avg('precision_hot'):.3f}"
    )
    print(f"  fail modes: miss-only={only_m} forb-only={only_f} both={both}")

ctr = Counter()
fcr = Counter()
for c in r["cases"]:
    a = c["arms"]["polytrace"]
    for m in a["missing_must"]:
        ctr[m.split("::")[-1]] += 1
    for m in a["forbidden_hot"]:
        fcr[m.split("::")[-1]] += 1
print("\npoly missing symbols", ctr.most_common(15))
print("poly forbidden symbols", fcr.most_common(15))

# show ranking for a pass and a fail
for cid in ("h01", "h10", "h08"):
    c = next(x for x in r["cases"] if x["id"] == cid)
    a = c["arms"]["polytrace"]
    print(f"\n=== {cid} correct={a['correct']} recall={a['recall_must']} prec={a['precision_hot']} f1={a['f1']}")
    print(" missing", a["missing_must"])
    print(" forb", a["forbidden_hot"])
    print(" ranked hot:")
    for cell in a["heatmap"][:8]:
        print("  ", round(cell["score"], 3), cell["id"].split("::")[-1], cell["why"][:50])
