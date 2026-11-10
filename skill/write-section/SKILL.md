---
name: write-section
description: Write or revise one manuscript section from its ticket, claims-first, then get it reviewed. The paper's equivalent of /implement.
argument-hint: "Which section ticket? An issue number, or nothing to pick from the frontier"
---

This skill works in a paper repo laid out for it: the spine in `paper/` (`CONTEXT.md`, `claims.md`,
`GLOSSARY.md`, `outline.md`), the `make check` gate, and `scripts/zotero.py`. If the repo has no
`paper/CONTEXT.md`, say so and stop.

Write the section that the ticket describes.

If no ticket is named, list the open `kind:section` issues whose blockers are all closed (the
frontier) and ask which one to take. Don't guess.

## Read first

The ticket. Then `paper/CONTEXT.md`, `paper/GLOSSARY.md`, `paper/claims.md`, `paper/outline.md`,
the section file itself, and the sections immediately before and after it in `main.tex`.
Look at every figure the section describes: run `make preview` and open its PNG in
`build/preview/`. Open every table it describes in `tables/`. For related work, read your
notes and annotations on the cited papers in Zotero (`python3 scripts/zotero.py tree` shows the
collections), not just their abstracts.

## Draft claims-first

The section's claims are its tests.

1. **Red.** Replace the skeleton with one topic sentence per paragraph, following the
   section's lines in `outline.md`. Above each paragraph that argues a claim, put `% C<n>` and its
   evidence, e.g. `% C4 ← tab:main, \MainMapOurs`. Run `make check SECTION=<name>`
   and see it fail.
2. **Green.** Expand each paragraph until its claim is supported:
   - Numbers come only from `numbers.tex` macros. If the macro you need doesn't exist, the result
     isn't in `results/`: stop and ask.
   - Cite only keys in `references.bib`. If a claim needs a source you don't have, write
     `\citep{TODO: what the source must show}` and ask. The gate fails on it until the paper is
     in Zotero `sota/` and `make bib` has run. Never invent a citekey, a paper, or a result.
   - Use only terms and symbols from `GLOSSARY.md`. If you need a new one, add it there.
   - Describe what figures and tables show, not what they're expected to show.
3. **Refactor.** Tighten. Cut sentences that don't serve a claim or the arc, fix the transitions
   to the neighbouring sections, and get within the word budget.
4. **Humanize.** Run `/humanizer` on the section's prose. Keep every `% C<n>` tag, macro,
   `\cite`, `\ref`, `\label`, equation and float exactly as they are, and don't change what any
   claim says or how strongly it says it. Only the wording changes.

Run `make check SECTION=<name>` after each group of paragraphs, and again after humanizing.

## Review

Run `/review-section <name>`. Fix every `blocking` and `should` finding, run `make check
SECTION=<name>` again, and run one more review at most. Leave `nit`s as `% REVIEW:` comments.
If you disagree with a finding on substance (a claim's strength, what the data shows), don't
argue it out: ask, quoting the finding and your reason.

## Finish

If the section needed changes to the spine files (`paper/*.md`), commit those separately and
say so. Commit the section to the current branch.
