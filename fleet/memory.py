"""How much context a session's CLAUDE.md files take, estimated from their size.

Claude Code loads ~/.claude/CLAUDE.md, then CLAUDE.md, .claude/CLAUDE.md and CLAUDE.local.md in every
directory from the session's cwd up to its git root. Measured starting context is the same in a repo and
in its .claude/worktrees/*, so the walk stops at the first directory holding a .git (file or dir).
Subdirectory CLAUDE.md files that load later, on demand, aren't counted.
"""
import os
from pathlib import Path

from . import paths

CHARS_PER_TOKEN = 4
NAMES = ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md")

_cache = {}   # path -> (mtime, tokens)


def tokens_in(p: Path) -> int:
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return 0
    hit = _cache.get(p)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        n = len(p.read_text(errors="replace")) // CHARS_PER_TOKEN
    except OSError:
        n = 0
    _cache[p] = (mtime, n)
    return n


def files_for(cwd) -> list[Path]:
    found = []
    user = paths.HOME / ".claude/CLAUDE.md"
    if user.is_file():
        found.append(user)
    if not cwd:
        return found
    d = Path(os.path.realpath(cwd))
    chain = []
    while True:
        chain.append(d)
        if (d / ".git").exists() or d.parent == d:
            break
        d = d.parent
    for d in reversed(chain):   # outermost first, the order Claude Code loads them
        found += [d / n for n in NAMES if (d / n).is_file() and d / n != user]
    return found


def claude_md(cwd) -> dict:
    """{"tokens": total, "files": [{"path", "tokens"}]} for a session started in `cwd`."""
    files = [{"path": short(p, cwd), "tokens": tokens_in(p)} for p in files_for(cwd)]
    return {"tokens": sum(f["tokens"] for f in files), "files": files}


def short(p: Path, cwd):
    s = str(p)
    if cwd and s.startswith(str(cwd).rstrip("/") + "/"):
        return s[len(str(cwd).rstrip("/")) + 1:]
    return s.replace(str(paths.HOME), "~", 1)
