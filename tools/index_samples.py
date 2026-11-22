#!/usr/bin/env python3
"""index_samples.py -- flatten samples/*/meta.json into samples/index.tsv (so the C++
renderer needs no JSON parser).  Columns: key file w h baseline_px cap_px em_px

em_px is CALIBRATED from your handwriting: digits/capitals give one em estimate
(Computer Modern digit height 0.644 em, cap height 0.683 em) and lowercase x-height
letters give another (x-height ~0.44 em). The renderer then makes your letters the
same size as the typeset ones. The report shows how your writing compares to the
sheet's guide lines. Usage: python tools/index_samples.py samples"""
import json, statistics, sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "samples")
rows = []
for mp in sorted(root.glob("*/meta.json")):
    d = json.load(open(mp))
    for name, m in sorted(d["samples"].items()):
        if (mp.parent / name).exists():
            rows.append({**m, "key": d["key"], "file": name})

def med(xs, need=8):
    return statistics.median(xs) if len(xs) >= need else None

caps = [r["h"] / (0.644 if r["key"].startswith("digit_") else 0.683)
        for r in rows if r["kind"] == "normal" and (r["key"].startswith("digit_") or r["key"].startswith("cap_"))]
xh = [r["h"] / 0.44 for r in rows if r["key"] in list("acemnorsuvwxz")]
em_dc, em_lo = med(caps), med(xh)
guide = statistics.median([r["em_px"] for r in rows]) if rows else 0
for r in rows:
    if r["kind"] != "normal": continue
    lower = len(r["key"]) == 1 and r["key"].islower()
    cal = em_lo if lower else em_dc
    if cal: r["em_px"] = round(cal, 1)

lines = ["\t".join(map(str, [r["key"], r["file"], r["w"], r["h"], r["baseline_px"], r["cap_px"], r["em_px"]])) for r in rows]
(root / "index.tsv").write_text("\n".join(lines) + "\n")
print(f"{len(rows)} samples indexed -> {root / 'index.tsv'}")
if em_dc and guide: print(f"  digits/capitals: you write at {100 * guide / em_dc:.0f}% of the guide size (em {em_dc:.0f}px vs {guide:.0f}px)")
if em_lo and guide: print(f"  lowercase: x-height implies em {em_lo:.0f}px ({100 * em_lo / em_dc:.0f}% of the cap-based em)" if em_dc else f"  lowercase em {em_lo:.0f}px")
