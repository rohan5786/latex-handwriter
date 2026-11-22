# tools/

    pip install -r requirements.txt

## 1. Make a sheet
    python tools/make_sheet.py --tier 1 -o sheets/tier1      # or --tier 2 / --only int,sum
Writes `sheets/tier1.pdf` (print it, or insert as a OneNote printout and ink over it)
and `sheets/tier1.layout.json`. Edit `n` in symbols.json, or pass `--n 5`, to change samples per symbol.

## 2. Write in OneNote
1. `make_sheet.py` also writes `sheets/tier1-p1.png`, `-p2.png`, ... (one per sheet page).
2. One OneNote page per sheet page: **Insert > Picture > From File** (or Pictures), then resize so the whole
   sheet fits within one printed page, all four black corner squares visible.
3. If you have it (desktop OneNote): right-click the picture > **Set Picture as Background**.
4. **Draw** tab, black pen, medium thickness. Never use a highlighter or pale colors. Don't use Ink to Text/Math.
   Don't touch the four corner squares.
5. Capitals and digits reach the dashed cap line; letters sit on the solid baseline. Tall cells: write big.
6. **File > Print > Microsoft Print to PDF** -> `scans/p1.pdf`. (File > Export > Page > PDF also works if offered.)
   Each OneNote page must come out as exactly one PDF page.
7. Do a dry run first: fill 2-3 cells on page 1, export, run step 3, check `debug/page1.png`.

## 3. Cut
    python tools/cut_sheet.py sheets/tier1.layout.json scans/p1.pdf scans/p2.pdf scans/p3.pdf -o samples --debug debug
Images (or an exported PDF) go in page order. Check `debug/pageN.png`: green outlines = ink found, red = empty.
Re-scanning a page overwrites the same sample numbers, so you can fix single cells.
Result: `samples/<key>/NNN.png` (black RGBA, alpha = ink) + `samples/<key>/meta.json`.

meta.json fields: `baseline_px`/`cap_px` = line positions measured from the top of the tight crop;
`em_px` = reference em size in pixels. Render scale = target_em_px / em_px.

## Tests
    python tests/roundtrip.py
