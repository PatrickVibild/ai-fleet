"""Git operations the daemon runs itself (merging into the base branch, checking worktrees, pushing)."""
import asyncio
import os
import re

# A push from the daemon has no terminal to ask for a password or a host key; fail fast instead of hanging.
PUSH_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o ConnectTimeout=15"}


async def git(repo, *args, timeout=120, env=None):
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(repo), *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env={**os.environ, **env} if env else None)
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


async def add_worktree(repo, name, base):
    """Make `.claude/worktrees/<name>` on a new branch `worktree-<name>`, cut from the local `base` as it is now.
    The daemon does this itself instead of `claude -w`, which cuts from the remote's default branch: a ticket must
    start from the base branch with its blockers merged, not from origin or from where the run was submitted.
    Returns the worktree's path. Raises RuntimeError with git's output on failure."""
    path = os.path.join(str(repo), ".claude", "worktrees", name)
    rc, out = await git(repo, "worktree", "add", "-q", "-b", f"worktree-{name}", path, f"refs/heads/{base}")
    if rc != 0:
        raise RuntimeError(f"git worktree add failed: {out[-400:]}")
    return path


async def remove_worktree(repo, path):
    """Drop a worktree and its branch, but only when it is clean (no changes, no untracked files) and the branch is
    merged into the checked-out base, so nothing can be lost. Returns None when removed, else why it was kept."""
    branch = await current_branch(path)
    rc, out = await git(path, "status", "--porcelain")
    if rc != 0 or out:
        return "has uncommitted or untracked files"
    if branch and not await is_ancestor(repo, branch, "HEAD"):
        return f"{branch} isn't merged into the base branch"
    rc, out = await git(repo, "worktree", "remove", path)
    if rc != 0:
        return out.splitlines()[-1][:200] if out else "git worktree remove failed"
    if branch:
        await git(repo, "branch", "-d", branch)
    return None


async def is_ancestor(repo, a, b):
    rc, _ = await git(repo, "merge-base", "--is-ancestor", a, b)
    return rc == 0


async def base_branch(repo):
    """The branch work lands in: the remote's default branch when it has one, else main or master."""
    rc, out = await git(repo, "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD")
    if rc == 0 and "/" in out:
        b = out.split("/", 1)[1]
        if (await git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{b}"))[0] == 0:
            return b
    return await default_branch(repo)


async def remote_for(repo, branch):
    """The remote a branch pushes to: its upstream's, else origin, else the only one there is."""
    if branch:
        rc, out = await git(repo, "config", "--get", f"branch.{branch}.remote")
        if rc == 0 and out and out != ".":
            return out
    rc, out = await git(repo, "remote")
    remotes = out.split() if rc == 0 else []
    return "origin" if "origin" in remotes else (remotes[0] if remotes else None)


async def status(repo, base=None):
    """Where a checkout's work stands: merged into `base` (the default branch if not given) and on a remote.
    `target` is what a push sends: the base branch once the work is merged into it, else the branch itself.
    None outside a git repository or before the first commit."""
    rc, top = await git(repo, "rev-parse", "--show-toplevel")
    if rc != 0 or (await git(repo, "rev-parse", "--verify", "-q", "HEAD"))[0] != 0:
        return None
    branch = await current_branch(repo)
    base = base or await base_branch(repo) or branch
    merged = bool(branch and branch == base) or bool(base and await is_ancestor(repo, "HEAD", base))
    changes = await tracked_changes(repo)
    target = base if merged else branch
    remote = await remote_for(repo, target)
    rc, out = await git(repo, "rev-list", "--count", "HEAD", "--not", "--remotes")
    unpushed = int(out) if rc == 0 and out.isdigit() else 0
    return {"path": str(repo), "top": top, "branch": branch or "", "base": base or "", "merged": merged,
            "dirty": len(changes.splitlines()), "remote": remote or "", "unpushed": unpushed,
            "pushed": bool(remote) and unpushed == 0, "target": target or ""}


# What a failed push printed -> why, most specific first. GitHub answers "Repository not found" both when the
# repo doesn't exist and when this account can't see it, so that message names both.
PUSH_ERRORS = [
    ("not_found", r"repository not found|does not appear to be a git repository|\b404\b|no such file or directory",
     "The remote repository {remote} ({url}) doesn't exist, or this account can't see it. Create it "
     "(e.g. `gh repo create`) or fix the URL with `git remote set-url {remote} <url>`."),
    ("host_key", r"host key verification failed",
     "SSH doesn't know {url}'s host key yet. Connect once in a terminal (`ssh -T git@<host>`) to accept it."),
    ("no_access", r"permission denied|authentication failed|could not read (username|password)|terminal prompts disabled"
                  r"|\b403\b|denied to |access denied|invalid username or password|publickey",
     "No write access to {url}. Check your SSH key or `gh auth status`, and that this account may push there."),
    ("protected", r"protected branch|gh006|pre-receive hook declined|hook declined",
     "The remote refused the push to `{target}`: it's a protected branch or a server hook said no. Open a PR instead."),
    ("behind", r"non-fast-forward|fetch first|\[rejected\]|updates were rejected",
     "The remote's `{target}` has commits this one doesn't. Pull (or rebase) first, then push again."),
    ("network", r"could not resolve host|connection timed out|connection refused|network is unreachable"
                r"|operation timed out|unable to access|connection reset|timed out",
     "Can't reach {url}. Check the network or VPN, then push again."),
]


def explain_push(out, remote="", url="", target=""):
    """(kind, message) for a failed push's output."""
    low = (out or "").lower()
    for kind, pattern, msg in PUSH_ERRORS:
        if re.search(pattern, low):
            return kind, msg.format(remote=remote, url=url or remote, target=target)
    last = next((ln.strip() for ln in reversed((out or "").splitlines()) if ln.strip()), "no output")
    return "other", f"git push failed: {last}"


async def push(repo, info):
    """Push `info["target"]` (from status()) to its remote. Returns (ok, kind, message, output)."""
    target, remote = info.get("target"), info.get("remote")
    if not target:
        return False, "detached", "HEAD isn't on a branch, so there's nothing to push. Check out a branch first.", ""
    if not remote:
        return False, "no_remote", ("This repository has no remote yet. Create one (e.g. `gh repo create`) or add it "
                                    "with `git remote add origin <url>`, then push again."), ""
    rc, url = await git(repo, "remote", "get-url", remote)
    url = url if rc == 0 else remote
    rc, up = await git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", f"{target}@{{upstream}}")
    tracked = rc == 0 and up.startswith(remote + "/")
    dest = up.split("/", 1)[1] if tracked else target
    env = dict(PUSH_ENV)
    if (await git(repo, "config", "--get", "core.sshCommand"))[0] == 0 or "GIT_SSH_COMMAND" in os.environ:
        del env["GIT_SSH_COMMAND"]   # yours wins (a specific key, say)
    rc, out = await git(repo, "push", *([] if tracked else ["-u"]), remote, f"{target}:{dest}", env=env)
    if rc == 0:
        return True, "ok", f"Pushed `{target}` to {remote}.", out
    if rc == 124:
        return False, "network", f"The push to {url} timed out after 2 min. Check the network, then push again.", out
    kind, msg = explain_push(out, remote, url, target)
    return False, kind, msg, out
