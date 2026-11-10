---
name: find-papers
description: Find candidate papers on a topic and file the chosen ones in the paper's Zotero read collection for the user to triage. Use when asked to find papers, literature or references on a topic, or for a kind:references ticket.
argument-hint: "<topic or question>, or a references ticket number"
---

This skill works in a paper repo laid out for it: the spine in `paper/` (`CONTEXT.md`, `claims.md`,
`GLOSSARY.md`, `outline.md`), the `make check` gate, and `scripts/zotero.py`. If the repo has no
`paper/CONTEXT.md`, say so and stop.

Find papers on the topic and put the good ones in Zotero `<root>/read`, where `<root>` is the paper's
collection (`ROOT_COLLECTION` in `scripts/zotero.py`). The user reads them there and moves the ones
they want into `<root>/sota/<topic>` (or `rejected`). Only `sota` reaches `references.bib`, so moving
a paper into `sota` is their approval. You never move,
edit or delete anything in Zotero.

## Search

Read `paper/CONTEXT.md` so you know what the paper argues and what counts as relevant. Run
`python3 scripts/zotero.py tree` to see what topics `sota/` already covers.

Turn the topic into 2–4 queries: different phrasings, the method name, the application name.
Run each with `python3 scripts/zotero.py search "<query>" --limit 15` (add `--since <year>` if
recency matters). Results come from OpenAlex, with `in_library` already checked against the
whole Zotero library, including `rejected`.

From the abstracts, pick the papers that would actually be cited. Prefer peer-reviewed and
well-cited work, include recent preprints only when they're directly on the topic, and drop
`in_library` hits. Aim for the number the ticket or user asks for, or about 5–10 if nobody says.

## Confirm

When a user is present, show the shortlist first, one line each: title, year, venue, citations,
open PDF yes/no, and why it's relevant. Let them trim it before anything is written.
Under the fleet (a `kind:references` ticket), the ticket is the approval: go ahead, since
the user triages `read/` afterwards anyway.

## File

Write the picks to a JSON file in your temp directory:

```json
{"query": "<the topic>",
 "items": [{"id": "W3091565629", "why": "<1–2 sentences: what it shows and which claim or section of this paper it bears on>"}]}
```

and run `python3 scripts/zotero.py add <file>`. Each paper is added to `<root>/read`, with
metadata from OpenAlex/Crossref (never from you), a "Why Claude picked this" note, the tags
`claude-found` and `q:<topic>`, and a link to the open-access PDF when there is one.

## Report

List what was added, which were skipped as already in the library, and the queries you ran. Tell
the user which `sota/` subcollection each paper probably belongs in. If a needed subcollection
doesn't exist, suggest a name: the user creates it, you don't.

For a `kind:references` ticket, also commit a short `paper/reading/<topic>.md` with the same
report, so the run has a record. No other files change.
