#!/usr/bin/env bash
# handwrite.sh paper.pdf out.pdf [samples_dir] [seed]     extra renderer flags: RENDER_ARGS="--xscale 1.1"
# PDF -> items.tsv (python) -> handwritten page PNGs (C++) -> out.pdf
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
in="${1:?usage: handwrite.sh paper.pdf out.pdf [samples_dir] [seed]}"; out="${2:?missing out.pdf}"
samples="${3:-$root/samples}"; seed="${4:-1}"; scale=4
[[ -x "$root/build/render" ]] || { echo "build first: make" >&2; exit 2; }
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
python3 "$root/tools/extract_items.py" "$in" -o "$tmp/items.tsv" --symbols "$root/symbols.json"
python3 "$root/tools/index_samples.py" "$samples"
"$root/build/render" "$tmp/items.tsv" "$samples" "$tmp/page" --scale "$scale" --seed "$seed" ${RENDER_ARGS:-}
python3 "$root/tools/pngs_to_pdf.py" "$out" --scale "$scale" $(ls "$tmp"/page-*.png | sort -V)
