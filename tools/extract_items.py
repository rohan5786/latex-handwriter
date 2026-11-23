#!/usr/bin/env python3
"""extract_items.py -- turn a LaTeX-compiled PDF into items.tsv for the renderer.

Records (tab-separated; coordinates in PDF points, y grows downward):
  PAGE  n  width  height
  G  key  x  y  size  advance  stretch  ix0  iy0  ix1  iy1  anchor
       x,y = glyph origin (left end of the baseline). stretch = 1 if the sample
       should be stretched to the ink box (ix0..iy1, measured from the page
       raster); otherwise ix* are '-'. Unmapped glyphs get key  ?FONT:U+XXXX
       and are drawn as black boxes by the renderer.
  L  x0  y0  x1  y1  thickness        a drawn line (fraction bar, radical bar, ...)

Usage:  python tools/extract_items.py paper.pdf -o items.tsv [--symbols symbols.json]
"""
import argparse
import collections
import json
import re
import sys

import cv2
import numpy as np
import pymupdf

SELECTORS = range(0xFE00, 0xFE10)      # variation selectors: CMEX size-variant markers


def family(font):
    return re.sub(r"\d+$", "", font)   # CMR10 -> CMR


def ink_box(img, ppp, x0, x1, ya, yb, pad=0.6, thr=160):
    """Bounding box (pt) of the largest ink blob in the column [x0-pad, x1+pad]
    between ya and yb (pt). A big delimiter is one connected stroke, so the largest
    (tallest) blob is the glyph even if neighbors poke into the column."""
    X0, X1 = max(int((x0 - pad) * ppp), 0), int((x1 + pad) * ppp) + 1
    Y0, Y1 = max(int(ya * ppp), 0), min(int(yb * ppp) + 1, img.shape[0])
    if X1 <= X0 or Y1 <= Y0:
        return None
    bw = (img[Y0:Y1, X0:X1] < thr).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
    if n < 2:
        return None
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_HEIGHT] * 1e6 + st[1:, cv2.CC_STAT_AREA]))   # tallest, ties by area
    x, y, w, h = st[i, 0], st[i, 1], st[i, 2], st[i, 3]
    return ((X0 + x) / ppp, (Y0 + y) / ppp, (X0 + x + w) / ppp, (Y0 + y + h) / ppp)


def page_lines(page):
    """Drawn strokes/rects as (x0,y0,x1,y1,thickness)."""
    out = []
    for d in page.get_drawings():
        w = d.get("width") or 0.4
        for it in d["items"]:
            if it[0] == "l":
                out.append((it[1].x, it[1].y, it[2].x, it[2].y, w))
            elif it[0] == "re":                       # filled rule: long axis = line, short = thickness
                r = it[1]
                if r.width >= r.height:
                    out.append((r.x0, (r.y0 + r.y1) / 2, r.x1, (r.y0 + r.y1) / 2, max(r.height, 0.3)))
                else:
                    out.append(((r.x0 + r.x1) / 2, r.y0, (r.x0 + r.x1) / 2, r.y1, max(r.width, 0.3)))
    return out


# Overlapping glyph pairs that TeX builds long arrows from -> one glyph.
COMPOSITES = [(("CMR", "="), ("CMSY", "\u21d2"), "implies"),
              (("CMSY", "\u21d0"), ("CMSY", "\u21d2"), "iff"),
              (("CMSY", "\u2212"), ("CMSY", "\u2192"), "longrightarrow")]


def merge_composites(glyphs, fams):
    out, i = [], 0
    while i < len(glyphs):
        g = glyphs[i]
        nx = glyphs[i + 1] if i + 1 < len(glyphs) else None
        hit = None
        if nx and abs(nx["y"] - g["y"]) < 0.5 and -3.0 <= nx["x"] - (g["x"] + g["adv"]) <= 0.5:
            for a, b, key in COMPOSITES:
                if fams[id(g)] == a and fams[id(nx)] == b:
                    hit = key
        if hit:
            g = dict(g, key=hit, adv=nx["x"] + nx["adv"] - g["x"], anchor="fitw", stretch=0, ink=None, role=None)
            fams[id(g)] = ("MERGED", hit)
            i += 1
        out.append(g)
        i += 1
    return out


def extract_page(page, fmap, dpi, missing):
    ppp = dpi / 72
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w).copy()
    # Erase vertical rules (\\boxed borders, determinant bars...) before measuring: a 30pt
    # border running through a glyph's column would otherwise be mistaken for the glyph.
    for x0_, y0_, x1_, y1_, t_ in page_lines(page):
        if abs(x1_ - x0_) < 0.2 * abs(y1_ - y0_) and abs(y1_ - y0_) > 4:
            cv2.line(img, (int(x0_ * ppp), int(y0_ * ppp)), (int(x1_ * ppp), int(y1_ * ppp)), 255, int((t_ + 1.0) * ppp))

    glyphs, fams = [], {}
    for b in page.get_text("rawdict")["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                fam = family(s["font"])
                for ch in s["chars"]:
                    c = ch["c"]
                    if c == " " or ord(c) in SELECTORS:
                        continue
                    x0, _, x1, _ = ch["bbox"]
                    m = fmap.get((fam, c))
                    g = {"x": ch["origin"][0], "y": ch["origin"][1], "size": s["size"],
                         "adv": x1 - x0, "x0": x0, "x1": x1, "ink": None, "role": None, "stretch": 0,
                         "anchor": "center"}
                    if m is None:
                        g["key"] = f"?{fam}:U+{ord(c):04X}"
                        missing[g["key"]] += 1
                    else:
                        g["key"], g["role"] = m["key"], m.get("role")
                        g["anchor"] = m.get("anchor", "center")
                        if m.get("ink_em"):                       # known ink box relative to the origin
                            top, bot = m["ink_em"]
                            g["stretch"] = 1
                            g["ink"] = (g["x"], g["y"] - top * s["size"], g["x"] + max(g["adv"], 0.3 * s["size"]), g["y"] + bot * s["size"])
                        elif m.get("stretch") == "vertical":
                            g["stretch"] = 1
                            up, down = m.get("win", [0.4, 3.5])      # CM delimiters/radicals hang BELOW their origin
                            g["ink"] = ink_box(img, ppp, x0, x1, g["y"] - up * s["size"], g["y"] + down * s["size"], m.get("pad", 0.6))
                            if g["ink"] is None:
                                g["stretch"] = 0
                    glyphs.append(g)
                    fams[id(g)] = (fam, c)

    glyphs = merge_composites(glyphs, fams)

    # Zero-width accents (\vec) share an origin with the letter they sit on: borrow its width.
    for i, g in enumerate(glyphs):
        if g["role"] == "accent" and g["adv"] <= 0:
            for j in (i + 1, i - 1):
                if 0 <= j < len(glyphs) and abs(glyphs[j]["x"] - g["x"]) < 0.5 and glyphs[j]["adv"] > 0:
                    g["adv"] = glyphs[j]["adv"]
                    break

    # Overlays (\not slash): zero width, drawn just before the glyph they cross: center on that glyph.
    for i, g in enumerate(glyphs):
        if g["role"] == "overlay" and i + 1 < len(glyphs):
            nx = glyphs[i + 1]
            if nx["adv"] > 0 and abs(nx["x"] - g["x"]) < 8:
                g["x"], g["adv"] = nx["x"], nx["adv"]

    lines = page_lines(page)

    # Merge matrix-bracket pieces (top + bottom) into one tall glyph; the vertical
    # extension line between them is dropped.
    tops = [g for g in glyphs if g["role"] == "piece_top" and g["ink"]]
    bots = [g for g in glyphs if g["role"] == "piece_bottom" and g["ink"]]
    for t in tops:
        cand = [b for b in bots if b["key"] == t["key"] and abs(b["x"] - t["x"]) < 2 and b["y"] > t["y"]]
        if not cand:
            continue
        b = min(cand, key=lambda g: g["y"])
        bots.remove(b)
        t["ink"] = (min(t["ink"][0], b["ink"][0]), t["ink"][1], max(t["ink"][2], b["ink"][2]), b["ink"][3])
        t["role"] = "merged"
        b["role"] = "drop"
        ix0, iy0, ix1, iy1 = t["ink"]
        lines = [ln for ln in lines
                 if not (abs(ln[0] - ln[2]) < 0.5 and ix0 - 1.5 <= ln[0] <= ix1 + 1.5
                         and iy0 - 1 <= min(ln[1], ln[3]) and max(ln[1], ln[3]) <= iy1 + 1)]
    glyphs = [g for g in glyphs if g["role"] != "drop"]
    return pix.width / ppp, pix.height / ppp, glyphs, lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", default="items.tsv")
    ap.add_argument("--symbols", default="symbols.json")
    ap.add_argument("--dpi", type=int, default=400, help="raster dpi used only to measure tall glyphs")
    a = ap.parse_args()

    fmap = {(m["font"], m["char"]): m for m in json.load(open(a.symbols, encoding="utf-8"))["font_map"]}
    missing = collections.Counter()
    f = lambda v: f"{v:.3f}"
    with open(a.out, "w", encoding="utf-8") as out:
        for pn, page in enumerate(pymupdf.open(a.pdf), 1):
            w, h, glyphs, lines = extract_page(page, fmap, a.dpi, missing)
            out.write(f"PAGE\t{pn}\t{f(w)}\t{f(h)}\n")
            for g in glyphs:
                ink = [f(v) for v in g["ink"]] if g["stretch"] else ["-"] * 4
                out.write("\t".join(["G", g["key"], f(g["x"]), f(g["y"]), f(g["size"]), f(g["adv"]),
                                     str(g["stretch"]), *ink, g["anchor"]]) + "\n")
            for x0, y0, x1, y1, t in lines:
                out.write("\t".join(["L", f(x0), f(y0), f(x1), f(y1), f(t)]) + "\n")
    print(f"wrote {a.out}")
    if missing:
        print("no sample mapping for (will render as black boxes):", file=sys.stderr)
        for k, n in missing.most_common():
            print(f"  {k}  x{n}", file=sys.stderr)


if __name__ == "__main__":
    main()
