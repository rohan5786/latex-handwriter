#!/usr/bin/env python3
"""cut_sheet.py -- crop a filled-in sample sheet into samples/<key>/NNN.png.

Inputs: the *.layout.json from make_sheet.py, and one image per sheet page, in
page order (png/jpg photos or scans, or a PDF exported from OneNote).

Pipeline per page:
  1. find the four corner squares            (cv2 contours)
  2. perspective-warp the page to a fixed pixel grid
  3. flatten uneven lighting                 (optional, on by default)
  4. for each cell: ink = how dark the pixel is, not a hard threshold, so
     the faint grid / guide lines vanish and pen strokes stay
  5. crop tight to the ink; save as black RGBA PNG (alpha = ink)

Each symbol folder also gets meta.json: per sample, the baseline and cap line
position inside the tight crop, and a reference em size in pixels. The renderer
scales a sample by (target_em_px / em_px).

Usage:
  python tools/cut_sheet.py sheets/tier1.layout.json scans/p1.jpg scans/p2.jpg -o samples
  python tools/cut_sheet.py sheets/tier1.layout.json onenote_export.pdf -o samples --debug debug
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf


def load_pages(paths, dpi):
    imgs = []
    for p in paths:
        if p.lower().endswith(".pdf"):
            for pg in pymupdf.open(p):
                pix = pg.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
                imgs.append(np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w).copy())
        else:
            im = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
            if im is None:
                sys.exit(f"cannot read image: {p}")
            imgs.append(im)
    return imgs


def find_fiducials(gray):
    """Return centers of the four corner squares as {'tl','tr','bl','br'}, or None."""
    h, w = gray.shape
    s = 1600 / max(h, w) if max(h, w) > 1600 else 1.0
    g = cv2.resize(gray, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else gray
    g = cv2.GaussianBlur(g, (5, 5), 0)
    _, bw = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    cnts, _ = cv2.findContours(bw, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE) # LIST: squares may sit inside a hole
    cands = []
    for c in cnts:
        a = cv2.contourArea(c)
        x, y, bw_, bh = cv2.boundingRect(c)
        if a < 30 or a > 0.01 * g.size or bh == 0 or not (0.75 < bw_ / bh < 1.33) or a / (bw_ * bh) < 0.85:
            continue # not a solid square
        cands.append((a, (x + bw_ / 2) / s, (y + bh / 2) / s))
    if len(cands) < 4:
        return None
    amax = max(c[0] for c in cands)
    pts = [(x, y) for a, x, y in cands if a >= 0.5 * amax] # drop specks of pen ink
    if len(pts) < 4:
        return None
    corner = {"tl": min(pts, key=lambda p: p[0] + p[1]), "br": max(pts, key=lambda p: p[0] + p[1]),
              "tr": max(pts, key=lambda p: p[0] - p[1]), "bl": min(pts, key=lambda p: p[0] - p[1])}
    return corner if len(set(corner.values())) == 4 else None


def flatten(gray, k=41):
    """Divide by an estimate of the paper brightness (kills shadows / gradients)."""
    bg = cv2.GaussianBlur(cv2.dilate(gray, np.ones((k, k), np.uint8)), (0, 0), k)
    return np.clip(gray.astype(np.float32) / np.maximum(bg, 1) * 255, 0, 255)


def cut_cell(page, cell, ppp, inset, lo, hi, min_ink):
    x0, y0 = int((cell["x"] + inset) * ppp), int((cell["y"] + inset) * ppp)
    x1, y1 = int((cell["x"] + cell["w"] - inset) * ppp), int((cell["y"] + cell["h"] - inset) * ppp)
    alpha = np.clip((hi - page[y0:y1, x0:x1]) / (hi - lo), 0, 1)
    if alpha.mean() < min_ink:
        return None
    ys, xs = np.where(alpha > 0.15)
    if len(xs) == 0:
        return None
    tx0, tx1 = max(xs.min() - 2, 0), min(xs.max() + 3, alpha.shape[1])
    ty0, ty1 = max(ys.min() - 2, 0), min(ys.max() + 3, alpha.shape[0])
    tight = alpha[ty0:ty1, tx0:tx1]
    top = y0 + ty0 # page-pixel y of the crop's top edge
    return tight, {
        "w": int(tight.shape[1]), "h": int(tight.shape[0]),
        "baseline_px": round(cell["baseline_y"] * ppp - top, 1), # from top of crop (may be <0 | >h)
        "cap_px": round(cell["cap_y"] * ppp - top, 1),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("layout")
    ap.add_argument("pages", nargs="+", help="images or PDFs, one sheet page each, in order")
    ap.add_argument("-o", "--out", default="samples")
    ap.add_argument("--ppp", type=float, default=5.0, help="working pixels per PDF point")
    ap.add_argument("--dpi", type=int, default=200, help="rasterization dpi for PDF inputs")
    ap.add_argument("--inset", type=float, default=2.5, help="ignore this many pt at cell edges")
    ap.add_argument("--lo", type=float, default=90, help="gray value that counts as full ink")
    ap.add_argument("--hi", type=float, default=170, help="gray value that counts as no ink")
    ap.add_argument("--min-ink", type=float, default=0.0015, help="mean alpha below this = empty cell")
    ap.add_argument("--no-flatten", action="store_true")
    ap.add_argument("--debug", help="write warped pages with cell outlines here")
    a = ap.parse_args()

    lay = json.load(open(a.layout))
    imgs = load_pages(a.pages, a.dpi)
    if len(imgs) != len(lay["pages"]):
        print(f"warning: layout has {len(lay['pages'])} pages, got {len(imgs)} images")
    out = Path(a.out)
    dst_pts = np.float32([[lay["fiducials"][k][0] * a.ppp, lay["fiducials"][k][1] * a.ppp]
                          for k in ("tl", "tr", "bl", "br")])
    size = (int(lay["page"][0] * a.ppp), int(lay["page"][1] * a.ppp))
    em_den = lay["cap_height_em"]
    meta, saved, empty = {}, 0, []

    for pi, (img, pg) in enumerate(zip(imgs, lay["pages"]), 1):
        fid = find_fiducials(img)
        if fid is None:
            print(f"page {pi}: could not find the 4 corner squares; skipped "
                  "(is the whole page visible, and the photo roughly upright?)")
            continue
        M = cv2.getPerspectiveTransform(np.float32([fid[k] for k in ("tl", "tr", "bl", "br")]), dst_pts)
        page = cv2.warpPerspective(img, M, size, flags=cv2.INTER_CUBIC, borderValue=255)
        page = page.astype(np.float32) if a.no_flatten else flatten(page)
        dbg = cv2.cvtColor(np.clip(page, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR) if a.debug else None

        for cell in pg["cells"]:
            res = cut_cell(page, cell, a.ppp, a.inset, a.lo, a.hi, a.min_ink)
            tl = (int(cell["x"] * a.ppp), int(cell["y"] * a.ppp))
            br = (int((cell["x"] + cell["w"]) * a.ppp), int((cell["y"] + cell["h"]) * a.ppp))
            if dbg is not None:
                cv2.rectangle(dbg, tl, br, (0, 160, 0) if res else (0, 0, 255), 3)
            if res is None:
                empty.append(f"{cell['key']}#{cell['idx']}")
                continue
            tight, m = res
            d = out / cell["key"]
            d.mkdir(parents=True, exist_ok=True)
            rgba = np.dstack([np.zeros(tight.shape + (3,), np.uint8), (tight * 255).astype(np.uint8)])
            name = f"{cell['idx']:03d}.png"
            cv2.imwrite(str(d / name), rgba)
            m.update(file=name, kind=cell["kind"], px_per_pt=a.ppp,
                     em_px=round((m["baseline_px"] - m["cap_px"]) / em_den, 1))
            meta.setdefault(cell["key"], {})[name] = m
            saved += 1
        if dbg is not None:
            Path(a.debug).mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(Path(a.debug) / f"page{pi}.png"), dbg)

    for key, entries in meta.items(): # merge with earlier runs
        mp = out / key / "meta.json"
        old = json.load(open(mp)) if mp.exists() else {"key": key, "samples": {}}
        old["samples"].update(entries)
        json.dump(old, open(mp, "w"), indent=1)
    print(f"saved {saved} samples, {len(empty)} empty cells")
    if empty:
        print("empty:", " ".join(empty[:40]) + (" ..." if len(empty) > 40 else ""))


if __name__ == "__main__":
    main()
