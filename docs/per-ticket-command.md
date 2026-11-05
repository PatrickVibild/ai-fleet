# Per-ticket implement command

## Why

Every implementor prompt currently starts with the global `implement_command`
(`fleet/config.py:12`, default `/mattpocock-skills:implement`). A repo with
more than one kind of ticket can't route them to different skills. The
motivating case is the ocean-engineering paper repo
(`~/repos/latex/ocean-engineering-paper`): section tickets should start with
`/write-section`, figure and table tickets with `/make-figure`, and tooling
tickets (`make check` gate, `numbers.tex` pipeline, bib checks) with the
normal implement. Those skills live in the paper repo's own `.claude/skills/`.

## Decisions

- The ticket field is `implement_command`, the same name as the global setting
  it overrides. Missing or empty means "use the global one"; there is no
  per-ticket opt-out to plain instructions.
- It may carry arguments (`/review-section --figure`). Only the first word is
  checked for being installed, as with the global setting.
- Only the orchestrator turns ticket kinds into commands. The daemon sees a
  concrete command per ticket and knows nothing about labels or kinds.
- A retry (new session) starts with the ticket's command again. Sendback and
  fix rounds resume the same session with a note and don't re-send it: the
  skill already ran there, and re-invoking it would restart its workflow.

## What to change

### 1. Keep the field in the run: `fleet/runs.py` `Run.from_plan`

`from_plan` (line ~30) builds each ticket dict from known keys and drops the
rest, so the field has to be added there:

```python
"implement_command": (t.get("implement_command") or "").strip(),
```

Update the docstring's plan shape to include `implement_command?`.

### 2. Check it at submit: `fleet/daemon.py` submit (~line 386)

Submit already refuses a plan whose `implement_command` / `merge_command`
isn't installed (`skills.missing(cmd, repo)`). Change it so:

- the global `implement_command` is checked only if at least one ticket has no
  `implement_command` of its own (a plan where every ticket brings its own
  shouldn't need the default installed). `merge_command` is checked as now.
- every distinct per-ticket `implement_command` is checked, and a missing one
  refuses the plan with a message naming the ticket(s):

```
ticket #12 implement_command `/write-section` isn't an installed skill or command
```

`skills.missing` already looks in the repo's `.claude/skills`, so a skill
that only exists in the target repo passes. The plan dicts at submit still
carry raw ids (`"#12"` is possible), so strip the `#` the way `from_plan` does,
or check after `Run.from_plan`.

### 3. Use it in the prompt: `fleet/daemon.py` `implementor_prompt` (~line 446)

```python
cmd = self.ticket_command(run, t) if t.get("implement_command") else self.command(run, "implement_command")
```

`ticket_command` mirrors `command()` (line 432): if the skill has gone missing
since submit, record a `command_missing` event with `ticket` set and notify
once per ticket. `command()` dedupes on the setting name in
`run.d["missingCommands"]`, so key per-ticket entries by ticket (e.g.
`"ticket:12"`). Then return `""` so the session gets plain instructions,
which is the existing fallback.

Don't fall back to the global `implement_command`. A ticket that asked for
`/write-section` shouldn't quietly run `/implement`.

`spawn_implementor` has one caller (the scheduler) and none pass a custom
`prompt`, and a retry puts the ticket back in `WAIT`, so retries already go
through `implementor_prompt`. Nothing else to route.

### 4. Show it

Show a ticket's command when it differs from the global `implement_command`:

- `fleet status` (`fleet/cli.py` `cmd_status`, the per-ticket line): append it
  after the title, e.g. `#12  running  Methods section  /write-section`.
- The panel: add `implement_command` to each ticket in `snapshot()`
  (`fleet/daemon.py` ~line 1509) and show it in the ticket's details in
  `omarchy-plugin/Run.qml`. Run `omarchy restart shell` after editing it.

## Docs

- `README.md` (~line 94): add `"implement_command": "/write-section"` to the
  example ticket and explain it in one sentence.
- `skill/implement-orchestrator/SKILL.md` (line 26): add `"implement_command"`
  to the submit JSON. Update the `command_missing` bullet (line 63) to say it
  can also name a ticket's command (`ticket` is set then).
- `skill/implement-orchestrator/TICKETS.md`: add a step to plan building.
  - If the repo has `docs/agents/ticket-commands.md`, read its kind → command
    table and set `implement_command` on each ticket whose kind matches.
    Unmatched tickets get none.
  - A ticket's kind: for GitHub/GitLab, a `kind:<x>` label or a `**Kind:**`
    line in the body; the label wins if they disagree. For local `.scratch/`
    tickets, the `**Kind:**` line only.
  - Fetch labels from GitHub with `--json number,title,body,url,labels`.
  - When showing the plan to the user (SKILL.md step 4), give each ticket's
    command next to its blockers when it has one.

`skill/implement-orchestrator` is symlinked into `~/.claude/skills` by
`install.sh`, so edits there take effect without reinstalling.

Example `docs/agents/ticket-commands.md` in a target repo (the paper repo's,
for now):

```markdown
| kind       | command          |
|------------|------------------|
| section    | /write-section   |
| figure     | /make-figure     |
| table      | /make-figure     |
```

`kind:references` (a planned `/find-references`) stays out until that skill
exists; unmapped kinds get the global command.

## Tests (`tests/test_core.py`)

- A plan ticket with `implement_command` keeps it through `from_plan`. One
  without gets `""`.
- `implementor_prompt` starts with the ticket's command when it's set
  (arguments included), and with the global `implement_command` when it isn't.
- Submit refuses a plan whose ticket command isn't installed, naming the
  ticket. It accepts one that exists only in the repo's `.claude/skills/`.
- Submit accepts a plan where every ticket has its own command even when the
  global `implement_command` isn't installed, and still refuses one where a
  ticket relies on the missing global.
- If a ticket's command goes missing after submit: `command_missing` event
  with the ticket id, once per ticket; the prompt falls back to plain
  instructions and does **not** fall back to the global `implement_command`.
- A retried ticket (back to `WAIT`, new session) starts with its command again.

## Out of scope

- Per-ticket `merge_command` or per-ticket checks.
- Per-repo default `implement_command`. That would be a separate, also
  reasonable, change.
- Re-sending the command on sendback or fix rounds.
