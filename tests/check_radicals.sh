#!/usr/bin/env bash
# Regression: radical ink boxes must be sane even next to \fbox borders and under other lines.
# Needs pdflatex (skips otherwise). Run from repo root.
command -v pdflatex >/dev/null || { echo "skip (no pdflatex)"; exit 0; }
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/r.tex" <<'TEX'
\documentclass{article}\usepackage{amsmath}\pagestyle{empty}\begin{document}
\noindent $\frac43\pi r^3=\frac43\pi ab^2\implies r=\sqrt[3]{2.85\cdot 2.2^2}\approx 2.3983$\par\bigskip
\noindent $S=\fbox{$\displaystyle b\sqrt{1-\frac{e^2y^2}{a^2}}$}\;dy\qquad e\sqrt{1-e^2}\qquad\sqrt{x+h}-\sqrt{x}$\par
\end{document}
TEX
(cd "$tmp" && pdflatex -interaction=nonstopmode r.tex >/dev/null 2>&1) || { echo "FAIL: pdflatex"; exit 1; }
python3 tools/extract_items.py "$tmp/r.pdf" -o "$tmp/i.tsv" >/dev/null 2>&1
awk -F'\t' '$1=="G"&&$2=="sqrt"{n++; w=$10-$8; h=$11-$9; if(w<7||w>11||h<9||h>32){bad++; printf "bad radical box w=%.1f h=%.1f\n",w,h}}
  END{ if(n<5){print "FAIL: expected >=5 radicals, found " n+0; exit 1} if(bad){exit 1} print "ok   " n " radical boxes sane" }' "$tmp/i.tsv"
