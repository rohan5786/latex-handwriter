#!/usr/bin/env python3
"""Make a stand-in samples/ folder from a system font (NOT handwriting) so the
render pipeline can be tested before you've written your real samples.
Usage: python tests/fake_samples.py samples_fake [--skip key1,key2]"""
import argparse, json, random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ap = argparse.ArgumentParser(); ap.add_argument("out"); ap.add_argument("--skip", default="")
ap.add_argument("--n", type=int, default=3); ap.add_argument("--symbols", default="symbols.json"); a = ap.parse_args()
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
sym = json.load(open(a.symbols, encoding="utf-8"))
kind = {s["key"]: s["kind"] for s in sym["symbols"]}
char = {}
for m in sym["font_map"]:
    if not m.get("role", "").startswith("piece"):
        char.setdefault(m["key"], m["char"])
char["vec"], char["vbar_tall"] = "\u2192", "|"
EM, BASE = 100, 170
rng = random.Random(0)
for key, ch in char.items():
    if key in a.skip.split(","): continue
    d = Path(a.out) / key; d.mkdir(parents=True, exist_ok=True); meta = {}
    for i in range(1, a.n + 1):
        size = EM * (2.4 if kind[key] in ("tall", "display") else 0.55 if key == "vec" else 1)
        base = BASE - (85 if key == "vec" else 0)
        im = Image.new("L", (360, 360), 0)
        if key == "sqrt":
            ImageDraw.Draw(im).line([(60, base - 20), (75, base - 30), (95, base + 20), (150, base - 90)], fill=255, width=7, joint="curve")
        else:
            ImageDraw.Draw(im).text((60, base), ch, font=ImageFont.truetype(FONT, int(size)), anchor="ls", fill=255)
        im = im.rotate(rng.uniform(-4, 4), resample=Image.BICUBIC, center=(180, base))
        l, t, r, b = im.getbbox() or (0, 0, 1, 1)
        l, t, r, b = max(l - 2, 0), max(t - 2, 0), r + 2, b + 2
        crop = im.crop((l, t, r, b)); rgba = Image.new("RGBA", crop.size, (0, 0, 0, 0)); rgba.putalpha(crop)
        rgba.save(d / f"{i:03d}.png")
        meta[f"{i:03d}.png"] = dict(w=crop.width, h=crop.height, baseline_px=BASE - t, cap_px=BASE - t - 0.683 * EM * (2 if kind[key] in ("tall", "display") else 1),
                                    em_px=EM * (2 if kind[key] in ("tall", "display") else 1), kind=kind[key], px_per_pt=5.0, file=f"{i:03d}.png")
    json.dump({"key": key, "samples": meta}, open(d / "meta.json", "w"), indent=1)
print("fake samples for", len(char), "symbols ->", a.out)
