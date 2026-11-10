---
name: research-academic
description: Academic literature library in ~/research, mirrored to Zotero. Use when writing or checking any part of a paper or thesis that rests on prior work, when a claim or value needs a citation, or when asked to research an academic topic.
---

The **library** holds every paper read so far, with notes and citation keys. Writing that rests on prior work cites only keys in the library's `refs.bib`, and takes every value from a paper's note. When the library is thin on a topic, grow it first, then write.

`scripts/lit.py` (in this skill's folder) does the search, metadata, Zotero and download work; `lit.py --help` lists its commands. `lit.py config` shows where the library is and how Zotero is reached.

## Layout

```
~/research/
  INDEX.md                 one line per topic: `- [topic](topics/<topic>/OVERVIEW.md) — what it covers`
  refs.bib                 every paper, keyed authorYearWord (solonenko2015inherent)
  library.json             lit.py's own record; edit through lit.py
  papers/<key>.md          one note per paper, shared by every topic it serves
  topics/<topic>/OVERVIEW.md
  pdf/, text/              full texts; text/<key>.txt is what you read
```

A topic is a kebab-case subject (`jerlov-water-types`, `underwater-image-formation`), never a paper section: the methodology, the discussion and a reviewer reply all draw on the same topics. Each topic is also a Zotero collection of the same name, under `ai-fleet/`.

## Steps

1. **Consult.** Read `INDEX.md`, then the `OVERVIEW.md` of every topic the request touches, then the notes it points to. List the claims and values the request needs, and mark each covered (a note supports it) or uncovered. Done when every needed claim is marked.

2. **Grow** (only for uncovered claims). Find candidates with `lit.py search`, then snowball from the strongest hits with `lit.py refs` and `lit.py cited-by`. Use WebSearch to find the canonical works a field cites by name. Pick, per claim:
   - the original source (the paper that defined the concept or ran the measurement),
   - the paper whose numbers you will use, when values are involved,
   - a recent review or the strongest recent work, so the text isn't stuck in one decade.

   Add each with `lit.py add DOI --topic T` (or `arXiv:ID`). A work without a DOI, such as an old book, goes in with `--csl FILE` holding hand-written CSL-JSON (`type`, `title`, `author`, `issued`, `publisher`, `ISBN`). Done when every uncovered claim has its original source, plus the measuring paper for each value.

3. **Read.** For each new paper, read `text/<key>.txt` (or the abstract when `fulltext: abstract-only`) and fill the note's `## Notes`:
   - **Claim**: what the paper establishes, in one or two sentences.
   - **Method**: how, at the level a methodology section would cite it.
   - **Values**: numbers, equations and tables you might use, each with its page, table or equation number.
   - **Quotes**: short verbatim passages worth citing, each with its page.
   - **Relevance**: which topics and which of the user's claims it supports, and where it disagrees with other notes.

   An abstract-only note carries only what the abstract states; its values wait for the full text. Done when every new note has all five headings filled.

4. **Synthesize.** Write or update `topics/<topic>/OVERVIEW.md`: what the literature agrees on, where it disagrees, the standard citations for each point (by key), open gaps, and a list of member keys. Add or update the topic's line in `INDEX.md`.

5. **Write.** Produce what was asked, citing with `\cite{key}` (or the repo's own citation style). When writing into a paper repo, copy the cited entries from `~/research/refs.bib` into the repo's `.bib`, keeping the keys. Every cited key exists in `refs.bib`, and every number traces to a note's Values.

6. **Report.** Tell the user which papers were added and under which topics, and list the abstract-only ones with their DOI links, so they can fetch those.

## Full text and access

`lit.py add` tries, in order: the PDF already in Zotero storage, arXiv, open-access copies, then the publisher through this machine's network. On the university network (eduroam), publisher IP access applies. Off campus, only open-access copies come through, unless `proxy_prefix` is set in the config.

Request papers one at a time, only the ones you will read; university licences forbid bulk downloading, and a publisher can block the whole university for it. When a site answers with a bot check, login page or captcha, the paper stays abstract-only: leave it there and list it in the report. The user saves it with the Zotero browser connector, and `lit.py fetch KEY` then picks the PDF up from Zotero storage.

## Zotero

The Zotero library has two top-level collections. `ai-fleet/` is where agents keep their references: `lit.py add` files each paper under `ai-fleet/<topic>`, and any paper there may be cited right away, with no approval step. It's shared across papers, so later work reuses it. `patrick/` is the user's own reading stack, where they mark what they've read themselves. You may read and cite from it, but never add, move, edit or delete anything there. `zotero_root` in the config names the agents' collection (default `ai-fleet`).

With web API keys (`zotero_user_id` and `zotero_api_key` in `~/.config/research-academic/config.toml`, else `ZOTERO_USER_ID` and `ZOTERO_API_KEY` in `~/.config/zotero/env`), `lit.py` adds items through the Zotero web API, creating `ai-fleet/` and each topic's collection under it as needed; they reach the desktop app on its next sync. Without them it uses the desktop app's connector, which needs Zotero open and can file into an existing collection only. Each item's Extra field pins `Citation Key: <key>`, so Better BibTeX exports the same keys as `refs.bib`.
