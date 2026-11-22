#!/usr/bin/env python3
"""pngs_to_pdf.py -- merge rendered page PNGs into one PDF.
Usage: python tools/pngs_to_pdf.py out.pdf --scale 4 page-1.png page-2.png ...
(--scale = pixels per PDF point used by the renderer; page size = pixels / scale)"""
import argparse, pymupdf
ap = argparse.ArgumentParser(); ap.add_argument("out"); ap.add_argument("pngs", nargs="+")
ap.add_argument("--scale", type=float, default=4.0); a = ap.parse_args()
doc = pymupdf.open()
for p in a.pngs:
    pix = pymupdf.Pixmap(p)
    page = doc.new_page(width=pix.width / a.scale, height=pix.height / a.scale)
    page.insert_image(page.rect, filename=p)
doc.save(a.out); print("wrote", a.out)
