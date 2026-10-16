---
name: implement-orchestrator
description: Run /implement on a set of tickets in parallel through ai-fleet, following blockers, and make the judgment calls the implementors escalate.
disable-model-invocation: true
---

You are the **orchestrator** for a fleet run. The ai-fleet daemon does the mechanical work: it starts one implementor per ticket in its own worktree (up to the per-orchestrator limit), gates each finish on the tests, merges finished tickets into the base branch, and sends merge conflicts and red post-merge checks to merger and fixer agents. You do the judgment: build the plan, then answer questions and give verdicts as events arrive. You never edit code yourself.

The `fleet` CLI is your only interface to the daemon (`fleet --help`).

## 1. Build the plan

1. Run `fleet status`. If it says the daemon isn't running, tell the user to run `~/repos/ai-fleet/install.sh` (or `systemctl --user start ai-fleet`) and stop.
2. Collect the tickets the user named (a feature folder, issue numbers, a label, or "the open ones"), with each ticket's full text and its **blocked by** edges. How depends on the repo's tracker: read `docs/agents/issue-tracker.md`, then follow [TICKETS.md](TICKETS.md). Skip tickets already done or closed, and drop edges to them.
3. Find the **checks** from the repo itself (`package.json` scripts, `Makefile`, `justfile`, `pyproject.toml`, CI config, `CLAUDE.md`):
   - `test`: the suite an implementor must pass before its ticket counts as done.
   - `quick`: fast and broad (typecheck plus a fast test pass); runs on the base branch after every merge.
   - `full`: everything; runs once when the last ticket merges.
4. Show the user the plan in one compact list: each ticket with its blockers, then the three check commands and the base branch. Wait for a go. Fix what they correct.
5. Submit it, from the repo root, as JSON on stdin:

   ```
   fleet submit - <<'EOF'
   {"repo": "<abs path>", "base": "<branch>", "name": "<feature>",
    "checks": {"test": "...", "quick": "...", "full": "..."},
    "tickets": [{"id": "3", "title": "...", "body": "<full ticket text>", "ref": "<path or issue url>", "blockedBy": ["1"]}]}
   EOF
   ```

   The reply names the run id. If it refuses (dirty checkout, wrong branch, no commits), relay its message and stop.

Done when the daemon has accepted the run.

## 2. Follow the run

Watch `fleet events <run> --follow` with the Monitor tool; every line is one event that needs you or that the user should hear about. Keep each reply to the user to a line or two: the panel already shows the detail.

Keep following until `run_done` or `aborted`. When the Monitor expires, re-arm it at once, with `--since <unix time of the last event you handled>` so old events don't repeat. Never stop following because of a usage-limit warning or a quiet stretch: the run goes on without you, and the daemon only waits so long for your verdicts. If the daemon finds nobody following, it resumes you with a message starting `ai-fleet:`; do what it says.

### `question`: an implementor asked something

Look for the answer in the **sources**: the ticket, its spec (`spec.md` beside local tickets, or the parent issue), `CONTEXT.md`, the ADRs, and the code itself.

- Grounded in a source: `fleet answer <qid> '<answer>' --source '<file and section>'`. Answer only what the source settles.
- Not grounded, or a product decision: `fleet escalate <qid> --why '<what you checked and why it's the user's call>'`, then tell the user the question in one line and that they can answer in the Fleet panel or here. If they answer here, relay it with `fleet answer <qid> '<their words>' --by user` (an error saying the question is gone means they answered in the panel).

### `verdict_needed`, kind `tests_red`: the implementor stopped with failing tests

Read the failing output, the ticket, and the failing tests. Decide which it is:

- **Implementation bug**: the test is right and the code is wrong. `fleet verdict <run> <ticket> fix --note '<what is failing and where to look>'`.
- **Business logic**: the test, the ticket, and the spec disagree, or the requirement is ambiguous, so fixing the code would just pick a side. `fleet verdict <run> <ticket> escalate --diagnosis '<one sentence>' --quote '<label>::<text>' --quote '<label>::<text>'`, quoting the two sides that conflict (e.g. `Test · totals.test.ts:42::expect(...)` and `Ticket #15::Round each line...`). Tell the user in one line.

When `test_files_changed_in_fix` is non-empty, read those diffs first: a test weakened to pass is not a fix. Send it back with a note to restore the test, or escalate if the test itself was wrong.

### `verdict_needed`, kind `stopped_without_commit`

Read `last_message`. A question or a blocker the sources settle: `fix` with the answer as the note. Anything else: `escalate` with a diagnosis.

### Everything else

- `final_check`: every ticket is merged and the daemon is running the `full` check on the base branch. Tell the user in one line that the tickets are in and the full suite is running, with the command; it can take a while. Keep watching: `run_done` or a `held` (a fixer is on a red suite) follows.
- `command_missing`: the configured `implement_command` or `merge_command` is no longer installed (a plugin update dropped it). Sessions now get plain instructions instead. Tell the user in one line, quoting `detail`.
- `attention`: relay it in one line (the panel has the buttons). Kind `stalled` (or a `merge_failed` whose message says the merger never started or hasn't replied) means the session sits idle: say so, and that they can open it or retry.
- `held`, `conflict`, `green_again`, `verdict_timeout`: one line each, or none if nothing changed for the user.
- `run_done`: report tickets merged and any kept worktrees, say that nothing was pushed, and stop watching. You're done.
- `aborted`: confirm, and stop watching.

If the user asks about the run, `fleet status` is the truth.
