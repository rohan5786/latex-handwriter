import fitz
page = fitz.open("sampling2.pdf")[0]
for b in page.get_text("rawdict")["blocks"]:
    for l in b.get("lines", []):
        for s in l["spans"]:
            for ch in s["chars"]:
                print(repr(ch["c"]), s["font"], round(s["size"], 1), ch["bbox"], ch["origin"])
for d in page.get_drawings():
    print("DRAW", d["rect"])