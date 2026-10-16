# Reading tickets for a plan

Every ticket in the plan needs: an `id`, a `title`, the full `body` (what to build and its acceptance criteria), a `ref` the implementor can open, and `blockedBy` (ids of tickets in this same plan).

## Local markdown (`.scratch/`)

Tickets are `.scratch/<feature>/issues/<NN>-<slug>.md`; the spec is `.scratch/<feature>/spec.md`.

- `id`: the `NN` prefix without leading zeros (`03` becomes `3`).
- `title`: the `# NN: <title>` heading.
- `body`: the whole file.
- `ref`: the file's path relative to the repo root.
- `blockedBy`: the `**Blocked by:**` line. It names tickets by number or title; map each to its id. "None" means no blockers.
- Skip tickets whose `Status:` says done, resolved, or closed.

## GitHub

- List: `gh issue list --state open --label <label> --json number,title,body,url` (default label `ready-for-agent`), or `gh issue view <n> --json number,title,body,url` for named issues.
- `id`: the issue number. `ref`: the issue URL. `body`: title plus body; add comments with `--comments` when they carry decisions.
- `blockedBy`: native dependencies first:
  `gh api repos/{owner}/{repo}/issues/<n>/dependencies/blocked_by --jq '.[] | select(.state=="open") | .number'`.
  If that endpoint isn't available, read the `## Blocked by` section of the body. Keep only blockers that are in this plan; a blocker outside the plan that is still open means the ticket can't run yet, so leave it out and tell the user.

## GitLab

Same shape with `glab issue list` / `glab issue view`; blockers come from the issue's "blocked by" links (`glab api projects/:id/issues/<n>/links`) or the body's `Blocked by` section.

## Anything else

Follow the workflow described in `docs/agents/issue-tracker.md` to read each ticket, and build the same fields.
