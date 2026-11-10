---
name: find-papers
description: Find papers on a topic and file the chosen ones in Zotero under ai-fleet/<topic>, where any agent can cite them. Use when asked to find papers, literature or references on a topic, or for a kind:references ticket.
argument-hint: "<topic or question>, or a references ticket number"
---

This skill works in a paper repo laid out for it: the spine in `paper/` (`CONTEXT.md`, `claims.md`,
`GLOSSARY.md`, `outline.md`), the `make check` gate, and `scripts/zotero.py`. If the repo has no
`paper/CONTEXT.md`, say so and stop.

Find papers on the topic and put the good ones in Zotero `ai-fleet/<topic>`, where `<topic>` is a
kebab-case subject (`underwater-domain-randomization`), not a paper section. `ai-fleet/` is the
agents' shared collection. A paper filed there can be cited straight away, by this paper or a later
one, with no approval step. `patrick/` is the user's own reading stack: read and cite from it, but
never add, move, edit or delete anything there. Outside `ai-fleet/`, you change nothing in Zotero.

## Search

Read `paper/CONTEXT.md` so you know what the paper argues and what counts as relevant. Run
`python3 scripts/zotero.py tree` to see which topics `ai-fleet/` and `patrick/` already cover,
and reuse an existing topic name when one fits.

Turn the topic into 2–4 queries: different phrasings, the method name, the application name.
Run each with `python3 scripts/zotero.py search "<query>" --limit 15` (add `--since <year>` if
recency matters). Results come from OpenAlex, with `in_library` already checked against the
whole Zotero library, including anything the user rejected.

From the abstracts, pick the papers that would actually be cited. Prefer peer-reviewed and
well-cited work, include recent preprints only when they're directly on the topic, and drop
`in_library` hits. Aim for the number the ticket or user asks for, or about 5–10 if nobody says.
Since nobody checks the picks afterwards, keep only papers you'd stand behind citing.

## Confirm

When a user is present, show the shortlist first, one line each: title, year, venue, citations,
open PDF yes/no, and why it's relevant. Let them trim it before anything is written.
Under the fleet (a `kind:references` ticket), the ticket is the approval: go ahead.

## File

Write the picks to a JSON file in your temp directory:

```json
{"query": "<the search topic>", "topic": "<kebab-case topic>",
 "items": [{"id": "W3091565629", "why": "<1–2 sentences: what it shows and which claim or section of this paper it bears on>"}]}
```

and run `python3 scripts/zotero.py add <file>`. Each paper is added to `ai-fleet/<topic>` (the
collection is created if it's missing), with metadata from OpenAlex/Crossref (never from you), a
"Why Claude picked this" note, the tags `claude-found` and `q:<query>`, and a link to the
open-access PDF when there is one.

## Report

List what was added and under which topic, which were skipped as already in the library, and the
queries you ran. They're citable now: `make bib` exports what the manuscript cites.

For a `kind:references` ticket, also commit a short `paper/reading/<topic>.md` with the same
report, so the run has a record. No other files change.
