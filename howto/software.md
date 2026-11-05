# Software implementation

Which skill to reach for at each step. Click a skill to copy it, then paste it into a Claude session.

## 1. Pin down what you want

- `/grill-me`: you have an idea and want it stress-tested, one round of questions at a time.
- `/grill-with-docs`: the same, but it writes the ADRs and glossary entries as decisions land.
- `/domain-modeling`: the terms are fuzzy or used two ways. Sharpens GLOSSARY.md before code bakes the confusion in.
- `/prototype`: a UI or state model you can't judge on paper. A throwaway build to answer one question.

## 2. Turn it into work

- `/to-spec`: the conversation already holds the decisions. Writes them up as a spec, no new interview.
- `/to-tickets`: splits a spec into tracer-bullet tickets with their blocking edges.
- `/wayfinder`: the work is bigger than one session can hold. Maps it as decision tickets and resolves them one by one.

## 3. Build

- `/implement-orchestrator`: run the tickets through the fleet, several implementors in parallel. Watch it in the Agentic tab.
- `/implement`: one piece of work in this session, from a spec or tickets.
- `/tdd`: new behaviour or a bug fix, test first, red-green-refactor.
- `/codebase-design`: deciding where a module's seam goes, or making code easier to test.

## 4. When something breaks

- `/diagnosing-bugs`: a hard bug or a slowdown. A reproduce, hypothesise, measure loop.
- `/diagnose-crash`: a program segfaulted or dumped core on this machine.

## 5. Check and ship

- `/code-review`: review a branch against the repo's standards and the spec it came from.
- `/simplify`: a quality pass that applies the cleanups it finds. It doesn't hunt for bugs.
- `/security-review`: before shipping anything that handles input, auth or secrets.
- `/pr`: write the PR body.

## Housekeeping

- `/improve-codebase-architecture`: every so often, to find modules worth deepening.
- `/writing-for-agents`: editing a skill, CLAUDE.md or AGENTS.md.
- `/handoff`: the context is getting full. Writes a handoff document for a fresh session.
- `/retro`: after a long session, to learn what to do differently.
