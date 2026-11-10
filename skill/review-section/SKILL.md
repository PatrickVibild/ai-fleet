---
name: review-section
description: Review manuscript text with two independent reviewers, one on the section and one on the whole paper, and return ranked findings. The paper's equivalent of /code-review.
argument-hint: "<section> | --global | --figure <name> | --table <name>"
---

This skill works in a paper repo laid out for it: the spine in `paper/` (`CONTEXT.md`, `claims.md`,
`GLOSSARY.md`, `outline.md`), the `make check` gate, and `scripts/zotero.py`. If the repo has no
`paper/CONTEXT.md`, say so and stop.

Run the reviewers as **subagents in parallel, each with a fresh context**. Give each one its
brief file and the paths below. Don't pass the writer's reasoning, the ticket discussion, or
your own opinion of the text: a reviewer that has been told why the text is as it is will tend
to agree with it.

| Argument | Reviewers |
|----------|-----------|
| `<section>` (e.g. `results`) | [LOCAL.md](LOCAL.md) on `sections/<section>.tex`, and [GLOBAL.md](GLOBAL.md) on the whole manuscript |
| `--global` | [GLOBAL.md](GLOBAL.md) only, on the whole manuscript. Run it after a fleet run's last merge. |
| `--figure <name>` / `--table <name>` | [FIGURE.md](FIGURE.md), and [GLOBAL.md](GLOBAL.md) limited to the figure or table, its caption, and every place the text refers to it |

Give each reviewer:
- the brief's path, which it reads first
- the target, with the diff from `git diff <base>...HEAD -- <file>` when there is one
- the ticket text, for LOCAL and FIGURE only

The reviewers read the spine files (`paper/*.md`) and sources themselves.

Before reporting, run `make check` (plus `SECTION=<name>` for a section) and put any gate
errors first as `blocking`.

## Report

Merge the reviewers' findings and drop duplicates. Report them ranked `blocking` → `should` →
`nit`, each as:

```
[blocking] sections/results.tex:42 (LOCAL)
  "Our method clearly outperforms all baselines"
  C4 evidence (tab:main) shows +3.1 on dataset A and −0.4 on dataset B: "all" and "clearly" overclaim.
  Direction: qualify per dataset.
```

Reviewers never edit files. Each finding gives a direction, not replacement text. Also list
separately any change a reviewer thinks the **spine** needs (for example, the glossary is stale
and the new text is right), because that's a decision for the writer or for the user, not a fix.

When run with `--global`, end by proposing one GitHub issue per `blocking` finding, with title,
`kind:` label and body. Don't create them unless asked.
