# Reading tickets for a plan

Every ticket in the plan needs: an `id`, a `title`, the full `body` (what to build and its acceptance criteria), a `ref` the implementor can open, and `blockedBy` (ids of tickets in this same plan). Some also get an `implement_command` (see [Ticket commands](#ticket-commands)).

## Local markdown (`.scratch/`)

Tickets are `.scratch/<feature>/issues/<NN>-<slug>.md`; the spec is `.scratch/<feature>/spec.md`.

- `id`: the `NN` prefix without leading zeros (`03` becomes `3`).
- `title`: the `# NN: <title>` heading.
- `body`: the whole file.
- `ref`: the file's path relative to the repo root.
- `blockedBy`: the `**Blocked by:**` line. It names tickets by number or title; map each to its id. "None" means no blockers.
- `kind`: the `**Kind:**` line, if any.
- Skip tickets whose `Status:` says done, resolved, or closed.

## GitHub

- List: `gh issue list --state open --label <label> --json number,title,body,url,labels` (default label `ready-for-agent`), or `gh issue view <n> --json number,title,body,url,labels` for named issues.
- `id`: the issue number. `ref`: the issue URL. `body`: title plus body; add comments with `--comments` when they carry decisions.
- `kind`: a `kind:<x>` label, else a `**Kind:**` line in the body. The label wins if they disagree.
- `blockedBy`: native dependencies first:
  `gh api repos/{owner}/{repo}/issues/<n>/dependencies/blocked_by --jq '.[] | select(.state=="open") | .number'`.
  If that endpoint isn't available, read the `## Blocked by` section of the body. Keep only blockers that are in this plan; a blocker outside the plan that is still open means the ticket can't run yet, so leave it out and tell the user.

## GitLab

Same shape with `glab issue list` / `glab issue view`; blockers come from the issue's "blocked by" links (`glab api projects/:id/issues/<n>/links`) or the body's `Blocked by` section. `kind` as for GitHub: a `kind:<x>` label, else the body's `**Kind:**` line.

## Anything else

Follow the workflow described in `docs/agents/issue-tracker.md` to read each ticket, and build the same fields.

## Ticket commands

If the repo has `docs/agents/ticket-commands.md`, read its kind → command table:

```markdown
| kind    | command        |
|---------|----------------|
| section | /write-section |
| figure  | /make-figure   |
```

Set `implement_command` to the matching command on each ticket whose `kind` is in the table. A ticket with no kind, or a kind the table doesn't list, gets no `implement_command` and uses the global one. Without the file, no ticket gets one.
