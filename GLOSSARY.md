# ai-fleet

Runs a plan of tickets through unattended Claude Code sessions: implementors build each ticket in its own worktree, and the fleet merges finished tickets into the base branch.

## Language

**Implement command**:
The slash command an implementor's first prompt starts with. A global default, which a ticket may override with its own.
_Avoid_: ticket command, skill (when meaning the command a ticket starts with)

**Ticket kind**:
What sort of work a ticket is (section, figure, tooling…), marked by a `kind:` label or a `**Kind:**` line. The orchestrator maps it to an implement command; the fleet itself never sees it.
_Avoid_: type, category

**Tidy**:
Retiring a done run's spec and tickets from their tracker: local files deleted (committed when tracked), issues closed. Only from the panel's button or `fleet tidy`, never automatically.
_Avoid_: clean up (that's removing a run's worktrees and sessions), archive

**Reminder**:
A todo with a due time. When it comes due the daemon pops one desktop notification; it never goes to the phone.
_Avoid_: alarm, alert (alerts are the "needs you" list)

**Playbook**:
One Markdown file in the How-to tab: the steps of a kind of work and which skill to use at each.
_Avoid_: guide, doc (when meaning a How-to file)
