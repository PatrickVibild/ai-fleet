# ai-fleet

Runs a plan of tickets through unattended Claude Code sessions: implementors build each ticket in its own worktree, and the fleet merges finished tickets into the base branch.

## Language

**Implement command**:
The slash command an implementor's first prompt starts with. A global default, which a ticket may override with its own.
_Avoid_: ticket command, skill (when meaning the command a ticket starts with)

**Ticket kind**:
What sort of work a ticket is (section, figure, tooling…), marked by a `kind:` label or a `**Kind:**` line. The orchestrator maps it to an implement command; the fleet itself never sees it.
_Avoid_: type, category
