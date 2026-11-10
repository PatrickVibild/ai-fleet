---
name: make-table
description: Make one manuscript results table from data as a reproducible script, wire it into its float, and get it reviewed.
argument-hint: "Which table ticket? An issue number"
---

This skill works in a paper repo laid out for it: the spine in `paper/` (`CONTEXT.md`, `claims.md`,
`GLOSSARY.md`, `outline.md`), the `make check` gate, and `scripts/zotero.py`. If the repo has no
`paper/CONTEXT.md`, say so and stop.

Make the table that the ticket describes. If no ticket is named, list the open `kind:table`
issues whose blockers are closed and ask. Don't guess.

Read the ticket, `paper/claims.md`, `paper/GLOSSARY.md`, `tables/src/tablestyle.py`, and
`tables/src/tab_example.py` for the pattern.

1. The data must already be in `results/*.json`. If it isn't, stop and ask. Never type values
   into the script.
2. Write `tables/src/tab_<name>.py` using `write_table(...)`. It writes only the `tabular*` body
   to `tables/<name>.tex`. Use units in headers, consistent decimals, and `bold_best` when the
   table compares methods.
3. Run `make tables/<name>.tex` and read the output.
4. In the section the ticket names, replace the placeholder tabular in the float with
   `\input{tables/<name>}`, keeping the float, `\caption` and `\label{tab:<name>}` in the section.
   Write or fix the caption: what is compared, the metric, how best values are marked, and
   every abbreviation defined.
5. Tables that aren't results (parameters, datasets, related-tool comparison) can be written
   directly in the section. They still use `booktabs`, glossary terms, and macros for any
   numbers that come from results.

Run `make check` and `/review-section --table <name>`. Fix `blocking` and `should` findings
and review at most once more. Commit the script, `tables/<name>.tex` (Overleaf needs it), and
the section change.
