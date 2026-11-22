#!/usr/bin/env python3
"""make_sheet.py -- build a printable handwriting-sample sheet from symbols.json.

Outputs:
  <out>.pdf          the sheet (Letter size)
  <out>.layout.json  where every cell is, in PDF points (read by cut_sheet.py)

Each cell has a light baseline and cap line. Four black squares near the page
corners let cut_sheet.py undo any scaling / skew from a scan, photo or export.

Usage:
  python tools/make_sheet.py --tier 1 -o sheets/tier1
  python tools/make_sheet.py --only int,sum,prod -o sheets/bigops
"""
import argparse
import json
import math
import textwrap
from pathlib import Path

import pymupdf

# ---- page geometry (PDF points; 72 pt = 1 inch) ---------------------------
PAGE_W, PAGE_H = 612.0, 792.0
FID = 18.0                      # corner square size
FID_OFF = 18.0                  # distance of corner squares from page edges
X0, X1 = 40.0, 572.0            # usable area (left, right)
Y0, Y1 = 58.0, 752.0            # usable area (top, bottom)
LABEL_W = 112.0                 # label column on the left
CELL_W, CELL_H, CELL_H_TALL = 44.0, 44.0, 88.0
COL_GAP, ROW_GAP = 2.0, 8.0
BASE_FRAC, CAP_FRAC = 0.72, 0.22    # baseline / cap line as fraction of cell height
GRID = (0.80, 0.80, 0.80)           # light: cut_sheet's threshold drops these
GUIDE = (0.78, 0.85, 0.95)

HINTS = {
    "normal": "",
    "tall": "write LARGE, tall",
    "display": "write LARGE",
    "accent": "just the accent,\nplaced above a letter",
}


def fid_centers():
    c = FID_OFF + FID / 2
    return {"tl": [c, c], "tr": [PAGE_W - c, c],
            "bl": [c, PAGE_H - c], "br": [PAGE_W - c, PAGE_H - c]}


def plan(symbols, cols):
    """Assign every sample cell a rectangle. Returns a list of pages."""
    pages, cur, y = [], {"cells": [], "labels": []}, Y0
    for s in symbols:
        cell_h = CELL_H_TALL if s["kind"] in ("tall", "display") else CELL_H
        nrows = math.ceil(s["n"] / cols)
        need = nrows * (cell_h + ROW_GAP)
        if y + need > Y1 and cur["cells"]:           # keep a symbol's rows together
            pages.append(cur)
            cur, y = {"cells": [], "labels": []}, Y0
        cur["labels"].append({"sym": s, "y": y})
        for i in range(s["n"]):
            r, c = divmod(i, cols)
            cx = X0 + LABEL_W + c * (CELL_W + COL_GAP)
            cy = y + r * (cell_h + ROW_GAP)
            cur["cells"].append({
                "key": s["key"], "idx": i + 1, "kind": s["kind"],
                "x": cx, "y": cy, "w": CELL_W, "h": cell_h,
                "baseline_y": cy + BASE_FRAC * cell_h,
                "cap_y": cy + CAP_FRAC * cell_h,
            })
        y += need
    if cur["cells"]:
        pages.append(cur)
    return pages


def draw(pages, title, pdf_path):
    doc = pymupdf.open()
    for pi, pg in enumerate(pages, 1):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        for cx, cy in fid_centers().values():
            page.draw_rect(pymupdf.Rect(cx - FID / 2, cy - FID / 2, cx + FID / 2, cy + FID / 2),
                           color=None, fill=(0, 0, 0))
        page.insert_text((X0, 46), f"latex-handwriter | {title} | page {pi}/{len(pages)}",
                         fontname="cour", fontsize=8)
        for lab in pg["labels"]:
            s, y = lab["sym"], lab["y"]
            tex = s["tex"]
            page.insert_text((X0, y + 14), tex, fontname="cobo",
                             fontsize=14 if len(tex) <= 3 else 10)
            page.insert_text((X0, y + 26), f"key: {s['key']}", fontname="cour", fontsize=7,
                             color=(0.4, 0.4, 0.4))
            for j, line in enumerate(filter(None, textwrap.wrap(s.get("hint") or HINTS[s["kind"]], 22) if s.get("hint") else HINTS[s["kind"]].split("\n"))):
                page.insert_text((X0, y + 36 + 8 * j), line, fontname="helv", fontsize=6.5,
                                 color=(0.4, 0.4, 0.4))
        for c in pg["cells"]:
            r = pymupdf.Rect(c["x"], c["y"], c["x"] + c["w"], c["y"] + c["h"])
            page.draw_rect(r, color=GRID, width=0.5)
            page.draw_line((r.x0, c["baseline_y"]), (r.x1, c["baseline_y"]), color=GUIDE, width=0.6)
            page.draw_line((r.x0, c["cap_y"]), (r.x1, c["cap_y"]), color=GUIDE, width=0.4, dashes="[2 2] 0")
    doc.save(pdf_path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default="symbols.json")
    ap.add_argument("--tier", default="1", help="1, 2 or all")
    ap.add_argument("--only", help="comma-separated symbol keys (overrides --tier)")
    ap.add_argument("--batch", help="select symbols whose \"batch\" field in symbols.json matches (overrides --tier)")
    ap.add_argument("--n", type=int, help="override samples per symbol")
    ap.add_argument("-o", "--out", default="sheets/sheet", help="output path without extension")
    ap.add_argument("--png-dpi", type=int, default=200, help="also write <out>-p1.png ... (for OneNote etc.); 0 = skip")
    a = ap.parse_args()

    syms = json.load(open(a.symbols, encoding="utf-8"))["symbols"]
    if a.only:
        want = a.only.split(",")
        syms = [s for s in syms if s["key"] in want]
    elif a.batch:
        syms = [s for s in syms if s.get("batch") == a.batch]
    elif a.tier != "all":
        syms = [s for s in syms if s["tier"] == int(a.tier)]
    if a.n:
        syms = [dict(s, n=a.n) for s in syms]
    if not syms:
        raise SystemExit("no symbols selected")

    cols = int((X1 - X0 - LABEL_W + COL_GAP) // (CELL_W + COL_GAP))
    if max(s["n"] for s in syms) > cols * 2:
        print(f"note: some symbols need more than 2 rows (cells per row = {cols})")
    pages = plan(syms, cols)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    draw(pages, out.name, str(out.with_suffix(".pdf")))
    layout = {"page": [PAGE_W, PAGE_H], "fiducials": fid_centers(), "fid_size": FID,
              "cap_height_em": 0.683,      # CM cap height as a fraction of 1 em
              "pages": [{"cells": p["cells"]} for p in pages]}
    json.dump(layout, open(out.with_suffix(".layout.json"), "w"), indent=1)
    if a.png_dpi:
        for i, pg in enumerate(pymupdf.open(out.with_suffix(".pdf")), 1):
            pg.get_pixmap(dpi=a.png_dpi).save(f"{out}-p{i}.png")
    ncell = sum(len(p["cells"]) for p in pages)
    print(f"{len(syms)} symbols, {ncell} cells, {len(pages)} pages -> {out}.pdf")


if __name__ == "__main__":
    main()
