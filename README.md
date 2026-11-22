# latex-handwriter
Re-draw a LaTeX-compiled PDF into your own handwriting.
Process map:
    paper.pdf --extract_items.py--> items.tsv --build/render (C++)--> page PNGs --> out.pdf

## Setup
    pip install -r requirements.txt
    make                      # fetches stb headers, builds build/render

## 1. Collect samples (once)
    python tools/make_sheet.py --tier 1 -o sheets/tier1      # print / ink over it
    python tools/cut_sheet.py sheets/tier1.layout.json scans/p1.jpg ... -o samples --debug debug
See tools/README.md. `symbols.json` lists every symbol and how PDF fonts map to them.

## 2. Handwrite a PDF
    tools/handwrite.sh paper.pdf out.pdf [samples_dir] [seed]
Symbols with no samples are drawn as black boxes --- looks identical to `$\blackbox$` in LaTeX --- and listed on stderr. That list is all of your to-be sampled characters.
Different seeds give different "takes". Extra renderer flags: `RENDER_ARGS="--xscale 1.1" tools/handwrite.sh ...`
(`--xscale` widens ordinary glyphs: raise it if letters look gappy, lower it if they collide).

`index_samples.py` (run automatically) calibrates glyph size from how you write digits, capitals and
lowercase and prints a report. Read it to see how your handwriting compares to the sheet's guide lines.

## Tests
    python tests/roundtrip.py                      # sheet -> photo -> cut
    bash tests/render_smoke.sh paper.pdf           # extract -> render, incl. missing-symbol fallback

## How placement works (src/render.cpp, tools/extract_items.py)
- Normal glyph: sample scaled by font size / `em_px`, centered on the glyph's advance box, sitting on its baseline.
- Tall glyph (`stretch` in symbols.json: big delimiters, `\int \sum \prod \sqrt`): the PDF's own boxes are font
  boxes, not ink, and these glyphs hang below their origin, so the extractor rasterizes the page and measures the
  tallest ink blob in the glyph's column; the sample is stretched to that box.
- Lines (fraction bars, radical bars): wobbly pen strokes.
- Radical sign: write only the check mark (no overline); it is scaled uniformly and pinned to the bar.
- Matrix brackets (built from pieces) are merged into one tall bracket.
