---
name: make-figure
description: Make one manuscript figure from results data as a reproducible script, look at it at print size, caption it, and get it reviewed.
argument-hint: "Which figure ticket? An issue number"
---

This skill works in a paper repo laid out for it: the spine in `paper/` (`CONTEXT.md`, `claims.md`,
`GLOSSARY.md`, `outline.md`), the `make check` gate, and `scripts/zotero.py`. If the repo has no
`paper/CONTEXT.md`, say so and stop.

Make the figure that the ticket describes. If no ticket is named, list the open `kind:figure`
issues whose blockers are closed and ask. Don't guess.

Read the ticket, `paper/claims.md` (the claim this figure shows), `paper/GLOSSARY.md`,
`figures/src/paperstyle.py`, and one existing `figures/src/fig_*.py` for the pattern.

## Data plots

1. The data must already be in `results/*.json`. If it isn't, stop and ask where it comes from
   (usually an export from the experiment repo). Never type data into the script.
2. Write `figures/src/fig_<name>.py`: read the JSON, call `figure(<width>)` with the ticket's
   width, plot, and call `save(fig, "<name>")`. Use the shared style. Don't override fonts or sizes.
3. Run `make figures/<name>.pdf` and **look at** `build/preview/<name>.png`. Check that the
   claim reads at a glance, text is legible at print size, nothing overlaps or is clipped, and
   series are distinguishable in grayscale. Change the script and render again until it's right.

## Schematics and diagrams

Draw them as SVG or with matplotlib patches, through the same `save()`, so the output is a
vector PDF at the ticket's width. Keep the source in `figures/src/`. Photos and renders from
the experiments go in `figures/` as PDF or high-quality JPEG (300 dpi or more at print width), copied by a
script that names where they come from.

## Float and caption

Put the float in the section the ticket names, if it isn't there already:

```latex
\begin{figure}[t]
\centering
\includegraphics[width=\columnwidth]{<name>}   % figure* and \textwidth for double width
\caption{<what is shown and how to read it; define abbreviations; no interpretation beyond the data>}
\label{fig:<name>}
\end{figure}
```

The caption belongs to this ticket. Write the text that discusses the figure only if the ticket says so.

## Finish

Run `make check` and `/review-section --figure <name>`. Fix `blocking` and `should` findings
and review at most once more. Commit the script, the PDF (Overleaf needs it), and the
section change.
