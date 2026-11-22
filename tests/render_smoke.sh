#!/usr/bin/env bash
# Pipeline smoke test with fake (font-based) samples. Pass any LaTeX-compiled PDF.
# Run from repo root after `make`:   bash tests/render_smoke.sh path/to/paper.pdf
set -euo pipefail
pdf="${1:?usage: render_smoke.sh paper.pdf}"; tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
python3 tests/fake_samples.py "$tmp/s" >/dev/null
tools/handwrite.sh "$pdf" "$tmp/full.pdf" "$tmp/s" >/dev/null 2>&1 && echo "ok   full render"
rm -rf "$tmp/s"; python3 tests/fake_samples.py "$tmp/s" --skip int,sqrt >/dev/null
log="$(tools/handwrite.sh "$pdf" "$tmp/skip.pdf" "$tmp/s" 2>&1 >/dev/null | grep -A5 'black boxes')"
echo "$log" | grep -q "int" && echo "$log" | grep -q "sqrt" && echo "ok   missing symbols reported: $(echo "$log" | tail -n +2 | tr -s ' \n' ' ')"
