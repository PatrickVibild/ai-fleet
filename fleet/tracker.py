"""Tidying a finished run's spec and tickets out of the tracker they came from. Local markdown files are deleted,
and the deletion is committed on the base branch when git tracks them. GitHub and GitLab issues are closed:
deleting an issue can't be undone and needs admin rights."""
import asyncio
import contextlib
import os
import re
from pathlib import Path

from . import git

GITHUB = re.compile(r"^https?://github\.com/[^/]+/[^/]+/issues/\d+/?$")
GITLAB = re.compile(r"^https?://[^/]+/.+/-/(issues|work_items)/\d+/?$")
DONE = re.compile(r"^\**status:?\**:?\s*(done|resolved|closed)\b", re.I | re.M)


def kind(ref):
    """'file', 'github', 'gitlab', or None for a ref we can't act on."""
    ref = (ref or "").strip()
    if not ref:
        return None
    if GITHUB.match(ref):
        return "github"
    if GITLAB.match(ref):
        return "gitlab"
    return None if re.match(r"^[a-z]+://", ref) else "file"


def items(run):
    """What tidying a run would touch: [{ref, kind, what}], tickets first so the spec goes last."""
    out = [{"ref": t["ref"], "kind": kind(t["ref"]), "what": f"#{t['id']}"} for t in run.tickets.values()]
    spec = run.d.get("spec") or ""
    out.append({"ref": spec, "kind": kind(spec), "what": "spec"})
    return [x for x in out if x["kind"]]


def summary(run):
    """For the panel and `fleet status`: the verb, what it covers, and every ref in the tooltip. None if nothing."""
    xs = items(run)
    if not xs:
        return None
    n = sum(x["what"] != "spec" for x in xs)
    spec = any(x["what"] == "spec" for x in xs)
    kinds = {x["kind"] for x in xs}
    verb = "delete" if kinds == {"file"} else "close" if "file" not in kinds else "tidy"
    noun = ("ticket" if kinds == {"file"} else "issue") + "s" * (n != 1)
    what = " + ".join((["spec"] if spec else []) + ([f"{n} {noun}"] if n else []))
    return {"verb": verb, "what": what, "refs": [x["ref"] for x in xs]}


def _inside(repo, ref):
    p = (Path(repo) / ref).resolve()
    return p if p.is_relative_to(Path(repo).resolve()) and p != Path(repo).resolve() else None


def open_siblings(spec_path, removed):
    """Ticket files beside a local spec (in its issues/ folder) that are still open and weren't in this run."""
    d = spec_path.parent / "issues"
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.md")):
        if f.resolve() in removed:
            continue
        try:
            if not DONE.search(f.read_text(errors="replace")):
                out.append(f.name)
        except OSError:
            pass
    return out


async def _run(*args, timeout=60):
    try:
        proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.STDOUT)
    except FileNotFoundError:
        return 127, f"{args[0]} isn't installed"
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "timed out"
    return proc.returncode, out.decode(errors="replace").strip()


async def close_issue(k, url, comment):
    if k == "github":
        rc, out = await _run("gh", "issue", "close", url, "--reason", "completed", "--comment", comment)
    else:
        rc, out = await _run("glab", "issue", "close", url)
    if rc == 0 or "already closed" in out.lower():
        return None
    return out.splitlines()[-1][:200] if out else f"exit {rc}"


async def tidy(run):
    """Delete or close every spec and ticket the run names. Returns {done, skipped, failed: [(ref, why)], commit}.
    Safe to repeat: files already gone and issues already closed count as done."""
    repo, name, base = Path(run.d["repo"]).resolve(), run.d["name"], run.d["base"]
    done, skipped, failed = [], [], []
    files, removed = [], set()
    comment = f"Done in ai-fleet run {name}: merged into `{base}`."
    for x in items(run):
        if x["kind"] != "file":
            why = await close_issue(x["kind"], x["ref"], comment)
            (failed.append((x["ref"], why)) if why else done.append(x["ref"]))
            continue
        p = _inside(repo, x["ref"])
        if not p:
            failed.append((x["ref"], "isn't a file inside the repo"))
            continue
        if x["what"] == "spec":
            still = open_siblings(p, removed)
            if still:
                skipped.append((x["ref"], f"kept: {len(still)} ticket(s) beside it are still open ({', '.join(still[:3])})"))
                continue
        removed.add(p)
        if p.exists() or await _tracked(repo, p):
            files.append(p)
        else:
            done.append(x["ref"])   # already gone
    commit = None
    if files:
        tracked = [p for p in files if await _tracked(repo, p)]
        if tracked and await git.current_branch(repo) != base:
            failed += [(str(p.relative_to(repo)), f"check out {base} in {repo} first; the deletion is committed there")
                       for p in files]
            files = []
        for p in files:
            if p not in tracked:
                try:
                    p.unlink(missing_ok=True)
                except OSError as e:
                    failed.append((str(p.relative_to(repo)), str(e)))
                    continue
            done.append(str(p.relative_to(repo)))
        if tracked and files:
            rels = [str(p.relative_to(repo)) for p in tracked]
            rc, out = await git.git(repo, "rm", "-q", "--ignore-unmatch", "--", *rels)
            if rc == 0:
                rc, out = await git.git(repo, "commit", "-q", "-m", f"Remove the spec and tickets of {name}: all merged",
                                        "--", *rels)
            if rc == 0:
                commit = (await git.git(repo, "rev-parse", "--short", "HEAD"))[1]
            else:
                done = [d for d in done if d not in rels]
                failed += [(r, out.splitlines()[-1][:200] if out else "git failed") for r in rels]
        dirs = {d for p in files for d in (p.parent, p.parent.parent)}   # issues/ and the feature folder
        for d in sorted(dirs, key=lambda d: -len(d.parts)):   # deepest first, so a folder emptied by its child goes too
            if d.is_relative_to(repo) and d != Path(repo) and d.is_dir() and not any(d.iterdir()):
                with contextlib.suppress(OSError):   # an empty folder left behind isn't worth failing over
                    os.rmdir(d)
    return {"done": done, "skipped": skipped, "failed": failed, "commit": commit}


async def _tracked(repo, p):
    return (await git.git(repo, "ls-files", "--error-unmatch", "--", str(p)))[0] == 0
