#!/usr/bin/env python3
"""Fake a filled-in sheet (X in every cell), distort it like a phone photo,
run cut_sheet.py, and check every cell comes back. Run from the repo root:
    python tests/roundtrip.py
"""
import json, subprocess, sys, tempfile
from pathlib import Path
import cv2, numpy as np, pymupdf

root = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp())
run = lambda *a: subprocess.run([sys.executable, *map(str, a)], check=True, cwd=root, capture_output=True, text=True).stdout
print(run("tools/make_sheet.py", "--tier", "1", "-o", tmp / "sheet").strip())

lay = json.load(open(tmp / "sheet.layout.json"))
dpi = 150; k = dpi / 72
doc = pymupdf.open(tmp / "sheet.pdf")
BLANK = ("a", 8)                                  # one cell left empty on purpose
rng = np.random.default_rng(0)
photos, expected = [], 0
for pg, cells in zip(doc, lay["pages"]):
    pix = pg.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    im = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w).copy()
    for c in cells["cells"]:
        if (c["key"], c["idx"]) == BLANK: continue
        expected += 1
        x0, y0, x1, y1 = [int(v * k) for v in (c["x"] + 8, c["y"] + 8, c["x"] + c["w"] - 8, c["y"] + c["h"] - 8)]
        cv2.line(im, (x0, y0), (x1, y1), 20, 3); cv2.line(im, (x0, y1), (x1, y0), 20, 3)
    H, W = im.shape                                # put page on a darker "desk", then warp
    canvas = np.full((H + 200, W + 200), 120, np.uint8); canvas[100:100 + H, 100:100 + W] = im
    src = np.float32([[0, 0], [W + 200, 0], [0, H + 200], [W + 200, H + 200]])
    dst = src + rng.uniform(-35, 35, src.shape).astype(np.float32)
    ph = cv2.warpPerspective(canvas, cv2.getPerspectiveTransform(src, dst), (W + 200, H + 200), borderValue=120)
    grad = np.tile(np.linspace(0.75, 1.0, ph.shape[1]), (ph.shape[0], 1))   # uneven lighting
    ph = np.clip(ph * grad + rng.normal(0, 4, ph.shape), 0, 255).astype(np.uint8)
    p = tmp / f"photo{len(photos) + 1}.png"; cv2.imwrite(str(p), ph); photos.append(p)

out = run("tools/cut_sheet.py", tmp / "sheet.layout.json", *photos, "-o", tmp / "samples", "--debug", tmp / "dbg")
print(out.strip())
got = len(list((tmp / "samples").glob("*/*.png")))
m = json.load(open(tmp / "samples/x/meta.json"))["samples"]["001.png"]
print("sample x#1 meta:", m)
assert got == expected, f"expected {expected} samples, got {got}"
assert "a#8" in out, "blank cell not reported"
assert 0 < m["baseline_px"] < m["h"] + 60 and m["em_px"] > 0
print("OK: all", got, "cells recovered; debug images in", tmp / "dbg")
