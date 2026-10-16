"""Git operations the daemon runs itself (merging into the base branch, checking worktrees)."""
import asyncio


async def git(repo, *args, timeout=120):
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(repo), *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "timed out"
    return proc.returncode, out.decode(errors="replace").strip()


async def current_branch(repo):
    rc, out = await git(repo, "symbolic-ref", "--short", "-q", "HEAD")
    return out if rc == 0 else None


async def default_branch(repo):
    for b in ("main", "master"):
        rc, _ = await git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{b}")
        if rc == 0:
            return b
    return await current_branch(repo)


async def tracked_changes(repo):
    """Uncommitted changes to tracked files (untracked files, like .claude/worktrees, don't count)."""
    rc, out = await git(repo, "status", "--porcelain", "--untracked-files=no")
    return out if rc == 0 else "git status failed"


async def commits_ahead(repo, base, ref="HEAD"):
    rc, out = await git(repo, "rev-list", "--count", f"{base}..{ref}")
    return int(out) if rc == 0 and out.isdigit() else 0


async def changed_files(repo, base, ref="HEAD"):
    rc, out = await git(repo, "diff", "--name-only", f"{base}...{ref}")
    return out.splitlines() if rc == 0 else []


async def merge(repo, branch, message):
    """Merge `branch` into the checked-out branch of `repo`. Returns (ok, conflicted, output)."""
    rc, out = await git(repo, "merge", "--no-ff", "--no-edit", "-m", message, branch)
    if rc == 0:
        return True, False, out
    rc2, unmerged = await git(repo, "diff", "--name-only", "--diff-filter=U")
    if unmerged:
        await git(repo, "merge", "--abort")
        return False, True, unmerged
    await git(repo, "merge", "--abort")
    return False, False, out


async def is_ancestor(repo, a, b):
    rc, _ = await git(repo, "merge-base", "--is-ancestor", a, b)
    return rc == 0
