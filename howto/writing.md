# Scientific writing

From a question to a revised paper.

<!-- Numbered sections are the stages of the main flow, left to right. In each, `-` skills are the main path, in order, and `+` skills are optional or alternatives. Unnumbered sections are for any time. -->

## 1. Learn the field
- `/research-academic`: find and read the prior work in your literature library (mirrored to Zotero), and cite it for each claim.
+ `/find-papers`: find new papers on a topic and file them in Zotero under `ai-fleet/<topic>`, citable right away. Your own reading stays in `patrick/`.
+ `/teach`: you need to understand a method yourself before writing about it.

## 2. Sharpen the claim
- `/grill-me`: stress-test the contribution, the argument and the outline before drafting.
+ `/domain-modeling`: fix the paper's terms in GLOSSARY.md, so a word means one thing throughout.
+ `/to-questionnaire`: a decision only co-authors or a supervisor can make. Turn it into questions for them.

## 3. Plan the paper
- `/to-spec`: write down the outline, the claims and the evidence each section needs.
- `/to-tickets`: one ticket per section, figure or tool, each marked with its kind.

## 4. Draft
- `/implement-orchestrator`: draft sections and build figures in parallel through the fleet. Each ticket starts with the command for its kind in the repo's `docs/agents/ticket-commands.md`.
+ `/write-section`: draft one section in this session from its ticket.
+ `/make-figure`: build one figure in this session from its ticket.
+ `/make-table`: build one table in this session from its ticket.
+ `/prototype`: try a figure or table layout before committing to it.

## 5. Revise
- `/humanizer`: rewrite prose that reads as AI-generated. Same claims, your voice.
- `/review-section`: two fresh reviewers check a section against its ticket and the whole paper. The paper's `/code-review`.
+ `/wait-what`: a paragraph didn't land. Have it re-pitched from another angle.

## Any time
- `/handoff`: the context is getting full. Write a handoff for a fresh session.
- `/retro`: after a writing session, learn what to do differently.
