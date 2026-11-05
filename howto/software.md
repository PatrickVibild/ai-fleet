# Software implementation

From an idea to a merged PR.

<!-- Numbered sections are the stages of the main flow, left to right. In each, `-` skills are the main path, in order, and `+` skills are optional or alternatives. Unnumbered sections are for any time. -->

## 1. Shape it
- `/grill-me`: stress-test the idea, one round of questions at a time, until nothing is silently assumed.
+ `/grill-with-docs`: the same interview, writing ADRs and glossary entries as decisions land.
+ `/domain-modeling`: the terms are fuzzy or used two ways. Sharpen GLOSSARY.md before code bakes it in.
+ `/prototype`: a UI or state model you can't judge on paper. A throwaway build answers one question.

## 2. Plan it
- `/to-spec`: write the decisions already made up as a spec. No new interview.
- `/to-tickets`: split the spec into tracer-bullet tickets with their blocking edges.
+ `/wayfinder`: too big for one session. Map it as decision tickets and resolve them one by one.

## 3. Build it
- `/implement-orchestrator`: run the tickets through the fleet, implementors in parallel. Watch the Agentic tab.
+ `/implement`: one piece of work in this session instead, from a spec or tickets.
+ `/tdd`: new behaviour or a bug fix, test first, red-green-refactor.
+ `/codebase-design`: deciding where a module's seam goes, or making code easier to test.

## 4. Ship it
- `/code-review`: review the branch against the repo's standards and the spec it came from.
- `/pr`: write the PR body.
+ `/simplify`: a cleanup pass that applies what it finds. It doesn't hunt for bugs.
+ `/security-review`: before shipping anything that handles input, auth or secrets.

## When it breaks
- `/diagnosing-bugs`: a hard bug or a slowdown. Reproduce, hypothesise, measure.
- `/diagnose-crash`: a program segfaulted or dumped core on this machine.

## Any time
- `/handoff`: the context is getting full. Write a handoff for a fresh session.
- `/improve-codebase-architecture`: every so often, find modules worth deepening.
- `/writing-for-agents`: editing a skill, CLAUDE.md or AGENTS.md.
- `/retro`: after a long session, learn what to do differently.
