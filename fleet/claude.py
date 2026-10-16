"""Thin async wrappers around the `claude` CLI's background-session commands."""
import asyncio
import json
import re
import shutil

CLAUDE = shutil.which("claude") or "claude"


async def run(*args, cwd=None, timeout=120, input=None):
    proc = await asyncio.create_subprocess_exec(
        *args, cwd=cwd,
        stdin=asyncio.subprocess.PIPE if input is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(input.encode() if input else None), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, "timed out"
    return proc.returncode, out.decode(errors="replace")


async def agents(include_done=False) -> list[dict]:
    args = [CLAUDE, "agents", "--json"] + (["--all"] if include_done else [])
    rc, out = await run(*args, timeout=30)
    if rc != 0:
        return []
    try:
        return json.loads(out[out.index("["):])
    except (ValueError, json.JSONDecodeError):
        return []


_BG = re.compile(r"backgrounded\s*·\s*([0-9a-f]+)")


async def spawn_bg(*, cwd, prompt=None, name, settings, session_id=None, resume=None,
                   worktree=None, model=None, permission_mode="auto") -> str:
    """Start a background session (idle when there's no prompt); returns its short id.
    Raises RuntimeError with the CLI output on failure."""
    args = [CLAUDE, "--bg", "-n", name, "--settings", str(settings), "--permission-mode", permission_mode]
    if resume:
        args += ["--resume", resume]
    elif session_id:
        args += ["--session-id", session_id]
    if worktree:
        args += ["-w", worktree]
    if model:
        args += ["--model", model]
    if prompt:
        args.append(prompt)
    rc, out = await run(*args, cwd=str(cwd), timeout=90)
    m = _BG.search(out)
    if rc != 0 or not m:
        raise RuntimeError(out.strip()[-600:] or f"claude --bg exited {rc}")
    return m.group(1)


async def stop(short_id):
    return await run(CLAUDE, "stop", short_id, timeout=30)


async def rm(short_id, discard_token=None):
    args = [CLAUDE, "rm", short_id] + (["--discard-unpushed", discard_token] if discard_token else [])
    return await run(*args, timeout=60)


async def print_once(prompt, *, model, cwd, timeout=60) -> str:
    """One-shot `claude -p` call (used for AI status summaries)."""
    rc, out = await run(CLAUDE, "-p", "--model", model, "--no-session-persistence",
                        "--output-format", "text", prompt, cwd=str(cwd), timeout=timeout)
    return out if rc == 0 else ""
