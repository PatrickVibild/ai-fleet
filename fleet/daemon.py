"""fleetd: schedules tickets onto background Claude sessions, answers their hooks, merges finished work,
and writes state.json for the Omarchy panel.

Talks JSON lines over a unix socket (paths.SOCK). Every request is one line; every reply is one line.
Hook requests stay open until the daemon has an answer (a question answered, a verdict given).
"""
import asyncio
import json
import os
import re
import shlex
import socket
import struct
import subprocess
import time
import uuid

from . import claude, config, git, memory, paths, skills
from .runs import (ATTN, CONFLICT, KILLED, LIVE_RUN, MERGED, MERGING, READY, REVIEW, RUNNING, TESTING, WAIT,
                   Run, slug)
from .transcripts import LIMIT_TEXT, SessionView, describe, trunc

TAIL = 3500


def tail(s, n=TAIL):
    s = s or ""
    return s if len(s) <= n else "…" + s[-n:]


async def run_shell(cmd, cwd, timeout=1800):
    proc = await asyncio.create_subprocess_shell(
        cmd, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        start_new_session=True)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        try:
            os.killpg(proc.pid, 9)
        except ProcessLookupError:
            pass
        return 124, f"`{cmd}` timed out after {timeout}s"
    return proc.returncode, out.decode(errors="replace")


def notify(title, body, urgent=True):
    try:
        subprocess.Popen(["notify-send", "-a", "AI Fleet", "-u", "critical" if urgent else "normal", title, body],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except FileNotFoundError:
        pass


def alive(a):
    """Whether a `claude agents` entry is a running session. Its `state` "done" only means the last turn finished
    (an idle background session waiting for you); a stopped one is "stopped" with no pid."""
    return bool(a) and bool(a.get("pid"))


def proc_ppid(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return int(f.read().rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return 0


class Question:
    def __init__(self, run, ticket, session, tool_use_id, tool_input):
        self.id = "q" + uuid.uuid4().hex[:8]
        self.run, self.ticket, self.session = run, ticket, session
        self.tool_use_id, self.tool_input = tool_use_id, tool_input
        self.questions = tool_input.get("questions") or []
        self.state = "orchestrator"   # or "user"
        self.why = ""
        self.created = time.time()
        self.future = asyncio.get_running_loop().create_future()


class Fleet:
    def __init__(self):
        paths.ensure()
        self.cfg = config.load()
        self.runs = {r.id: r for r in Run.load_all()}
        self.views = {}          # sessionId -> SessionView
        self.agents = {}         # sessionId -> `claude agents` entry
        self.questions = {}      # qid -> Question
        self.verdicts = {}       # (run id, ticket id) -> Future
        self.summaries = {}      # node id -> sentence
        self.notified = set()
        self.locks = {}
        self.sudo = {}           # request id -> {..., future}
        self.last_state = ""
        self.last_view = 0.0     # when the panel last said someone is looking
        try:
            self.windows = json.loads(paths.MODEL_WINDOWS.read_text())
        except (OSError, json.JSONDecodeError):
            self.windows = {}
        for r in self.runs.values():   # hooks that were waiting when we stopped will reconnect and resend
            for t in r.tickets.values():
                if t["state"] in (TESTING, REVIEW):
                    t["state"] = RUNNING
            if r.d.get("finalCheck") in ("running", "cleanup"):   # it died with us; schedule() starts it again
                r.d["finalCheck"] = None

    # ------------------------------------------------------------------ server
    async def serve(self):
        if paths.SOCK.exists():
            paths.SOCK.unlink()
        server = await asyncio.start_unix_server(self._client, path=str(paths.SOCK))
        os.chmod(paths.SOCK, 0o600)
        loops = [self._every(2, self.poll), self._every(2, self.schedule), self._every(1, self.write_state),
                 self._every(5, self.summarize)]
        async with server:
            await asyncio.gather(server.serve_forever(), *loops)

    async def _every(self, sec, fn):
        while True:
            try:
                await fn()
            except Exception as e:  # keep the daemon alive; surface the error in the log
                print(f"[{fn.__name__}] {type(e).__name__}: {e}", flush=True)
            await asyncio.sleep(sec)

    async def _client(self, reader, writer):
        try:
            line = await reader.readline()
            if not line:
                return
            req = json.loads(line)
            sock = writer.get_extra_info("socket")
            pid = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[0]
            try:
                resp = await self.dispatch(req, pid)
                resp = {"ok": True, **(resp or {})}
            except Exception as e:
                resp = {"ok": False, "error": str(e)}
            writer.write((json.dumps(resp) + "\n").encode())
            await writer.drain()
        except (ConnectionError, json.JSONDecodeError):
            pass
        finally:
            writer.close()

    async def dispatch(self, req, pid):
        op = req.get("op")
        if op == "ping":
            return {"pid": os.getpid()}
        if op == "state":
            return {"state": self.snapshot()}
        if op == "submit":
            return await self.submit(req["plan"], pid)
        if op == "hook":
            return await self.hook(req["event"], req.get("input") or {})
        if op == "answer":
            return self.answer(req["qid"], req.get("answers"), req.get("answer"), req.get("by", "user"), req.get("source", ""))
        if op == "escalate":
            q = self._q(req["qid"])
            q.state, q.why = "user", req.get("why", "")
            return {}
        if op == "verdict":
            return self.verdict(req["run"], req["ticket"], req)
        if op == "ctl":
            return await self.ctl(req)
        if op == "limits":
            for k in ("orchestrators", "implementors_per_orchestrator"):
                if k in req:
                    self.cfg[k] = max(1, min(16, int(req[k])))
            if req.get("summaries") in ("tool", "ai"):
                self.cfg["summaries"] = req["summaries"]
            config.save(self.cfg)
            return {}
        if op == "sudo":
            return await self.sudo_request(req, pid)
        if op == "sudo-answer":
            return self.sudo_answer(req["id"], req.get("password"), req.get("deny", False))
        if op == "viewing":
            # The panel calls this every few seconds while it's open; AI summaries are only made then (pull, not push).
            if time.time() - self.last_view > 15:
                self._last_sum = 0   # someone just opened the panel: summarize right away
            self.last_view = time.time()
            return {}
        if op == "events":
            r = self._run(req["run"])
            return {"path": str(r.dir / "events.jsonl")}
        raise ValueError(f"unknown op {op!r}")

    # ------------------------------------------------------------------ helpers
    def _run(self, rid):
        r = self.runs.get(rid) or next((r for r in self.runs.values() if r.id.startswith(rid)), None)
        if not r:
            raise ValueError(f"no run {rid!r}")
        return r

    def _q(self, qid):
        q = self.questions.get(qid)
        if not q:
            raise ValueError(f"no open question {qid!r}")
        return q

    def lock(self, repo):
        return self.locks.setdefault(repo, asyncio.Lock())

    def locate(self, session_id):
        for r in self.runs.values():
            role, obj = r.by_session(session_id)
            if role:
                return r, role, obj
        return None, None, None

    def orchestrator_alive(self, run):
        a = self.agents.get(run.d.get("orchestrator") or "")
        return alive(a)

    async def session_for_pid(self, pid):
        agents = await claude.agents()
        by_pid = {a.get("pid"): a for a in agents}
        for _ in range(40):
            if not pid or pid == 1:
                return None
            if pid in by_pid:
                return by_pid[pid].get("sessionId")
            pid = proc_ppid(pid)
        return None

    def write_settings(self, run, role, ticket=None):
        hooks = {"Stop": [{"hooks": [{"type": "command", "command": f"{paths.HOOK} stop", "timeout": 7200}]}],
                 "PreToolUse": [{"matcher": "AskUserQuestion",
                                 "hooks": [{"type": "command", "command": f"{paths.HOOK} ask", "timeout": 86400}]}]}
        settings = {"hooks": hooks,
                    "statusLine": {"type": "command", "command": str(paths.STATUSLINE_HOOK), "padding": 0},
                    "env": {"AI_FLEET_RUN": run.id, "AI_FLEET_ROLE": role, "AI_FLEET_TICKET": str(ticket or ""),
                            "AI_FLEET_SOCK": str(paths.SOCK), "AI_FLEET_STATE": str(paths.STATE)}}
        p = run.dir / "settings" / f"{role}-{ticket or uuid.uuid4().hex[:6]}.json"
        p.parent.mkdir(exist_ok=True)
        p.write_text(json.dumps(settings, indent=1))
        return p

    def log(self, run, t, msg):
        t.setdefault("log", []).append([time.time(), msg])
        t["log"] = t["log"][-40:]

    # ------------------------------------------------------------------ submit / schedule
    async def submit(self, plan, pid):
        repo = os.path.realpath(os.path.expanduser(plan["repo"]))
        if (await git.git(repo, "rev-parse", "--git-dir"))[0] != 0:
            raise ValueError(f"{repo} is not a git repository")
        if (await git.git(repo, "rev-parse", "--verify", "-q", "HEAD"))[0] != 0:
            raise ValueError(f"{repo} has no commits yet; background sessions need one to make worktrees")
        plan = {**plan, "repo": repo}
        plan["base"] = plan.get("base") or await git.current_branch(repo)
        if await git.current_branch(repo) != plan["base"]:
            raise ValueError(f"check out {plan['base']} in {repo} first; finished tickets merge into it there")
        if await git.tracked_changes(repo):
            raise ValueError(f"{repo} has uncommitted changes; commit or stash them first")
        for key in ("implement_command", "merge_command"):
            why = skills.missing(self.cfg[key], repo)
            if why:
                raise ValueError(f"{key} {why}. Set it in {paths.LIMITS} (\"\" for none), then submit again.")
        orch = plan.pop("orchestrator", None) or await self.session_for_pid(pid)
        run = Run.from_plan(plan, orchestrator=orch)
        self.runs[run.id] = run
        run.event("submitted", tickets=len(run.tickets))
        run.save()
        await self.schedule()
        return {"run": run.id, "status": run.d["status"], "events": str(run.dir / "events.jsonl")}

    async def schedule(self):
        live = [r for r in self.runs.values() if r.d["status"] in LIVE_RUN]
        queued = sorted((r for r in self.runs.values() if r.d["status"] == "queued"), key=lambda r: r.d["created"])
        while queued and len(live) < self.cfg["orchestrators"]:
            r = queued.pop(0)
            r.d["status"] = "active"
            r.event("run_started")
            r.save()
            live.append(r)
        limited = self.usage()["limited"]
        for r in live:
            if r.d["status"] != "active" or r.d.get("held"):
                continue
            if r.all_merged() and not r.d.get("finalCheck"):
                r.d["finalCheck"], r.d["finalCheckAt"] = "running", time.time()
                r.save()
                asyncio.create_task(self.final_check(r))
            if limited:   # a new session would only hit the limit too
                continue
            free = self.cfg["implementors_per_orchestrator"] - r.slots_used()
            for t in sorted(r.ready(), key=lambda t: (len(t["blockedBy"]), t["id"]))[:max(0, free)]:
                await self.spawn_implementor(r, t)

    def command(self, run, key):
        """The slash command a prompt starts with, or "" when it's unset or no longer installed (a plugin update
        can drop a skill mid-run; the session would only print "Unknown command" and sit idle)."""
        cmd = (self.cfg[key] or "").strip()
        why = skills.missing(cmd, run.d["repo"])
        if not why:
            return cmd
        if key not in run.d.setdefault("missingCommands", []):
            run.d["missingCommands"].append(key)
            run.event("command_missing", setting=key, detail=why)
            notify(f"{run.d['name']}: {key} is gone", f"{why}. Sessions get plain instructions instead; "
                                                      f"fix {key} in {paths.LIMITS}.")
        return ""

    def implementor_prompt(self, run, t):
        ref = f" ({t['ref']})" if t.get("ref") else ""
        cmd = self.command(run, "implement_command")
        return (f"{cmd + ' ticket' if cmd else 'Implement ticket'} #{t['id']}{ref}: {t['title']}\n\n{t['body']}\n\n"
                f"You are running unattended under ai-fleet. Ask questions only with the AskUserQuestion tool. "
                f"Commit your work on the current branch. Never push, and don't merge into `{run.d['base']}`: "
                f"the fleet merges finished tickets itself.")

    async def spawn_implementor(self, run, t, prompt=None):
        t["state"] = RUNNING
        t["attempt"] = t.get("attempt", 0) + 1
        t["fixRound"] = 0
        t["attn"] = None
        name = f"fleet-{slug(run.d['name'])}-{t['id']}" + (f"-r{t['attempt']}" if t["attempt"] > 1 else "")
        sid = str(uuid.uuid4())
        try:
            short = await claude.spawn_bg(
                cwd=run.d["repo"], prompt=prompt or self.implementor_prompt(run, t),
                name=f"{run.d['name']} #{t['id']} implementor", settings=self.write_settings(run, "implementor", t["id"]),
                session_id=sid, worktree=name, permission_mode=self.cfg["permission_mode"], model=self.cfg["model"] or None)
        except RuntimeError as e:
            t["state"] = ATTN
            t["attn"] = {"kind": "spawn_failed", "msg": f"Couldn't start the implementor: {e}"}
            run.event("attention", ticket=t["id"], kind="spawn_failed", detail=str(e))
            run.save()
            return
        t["session"] = {"sessionId": None, "short": short, "worktree": f"{run.d['repo']}/.claude/worktrees/{name}",
                        "started": time.time()}
        self.log(run, t, f"implementor {short} started")
        run.event("started", ticket=t["id"], session=short)
        run.save()

    # ------------------------------------------------------------------ hooks
    async def hook(self, event, inp):
        sid = inp.get("session_id")
        run, role, obj = self.locate(sid)
        if not run:
            return {}
        if event == "ask":
            return await self.hook_ask(run, role, obj, inp)
        if event == "stop":
            if LIMIT_TEXT.search(inp.get("last_assistant_message") or ""):
                run.event("usage_limit", role=role, ticket=obj.get("id") if role == "implementor" else obj.get("ticket"))
                return {}
            if role == "implementor":
                return await self.stop_implementor(run, obj, inp)
            if role == "merger":
                return await self.stop_merger(run, obj, inp)
            if role == "fixer":
                return await self.stop_fixer(run, obj, inp)
        return {}

    async def hook_ask(self, run, role, obj, inp):
        tool_use_id = inp.get("tool_use_id")
        q = next((q for q in self.questions.values() if q.tool_use_id == tool_use_id), None)
        if q is None:
            tid = obj["id"] if role == "implementor" else obj.get("ticket")
            q = Question(run.id, tid, inp.get("session_id"), tool_use_id, inp.get("tool_input") or {})
            self.questions[q.id] = q
            if not self.orchestrator_alive(run):
                q.state, q.why = "user", "No orchestrator is attached to this run, so it came straight to you."
            if role == "implementor":
                obj["state"], obj["attn"] = ATTN, {"kind": "question", "qid": q.id}
            run.event("question", qid=q.id, ticket=tid, role=role, questions=q.questions,
                      hint=f"Answer with: fleet answer {q.id} '<answer>' --source '<where you found it>' "
                           f"or hand it to the user with: fleet escalate {q.id} --why '<why>'")
            run.save()
        answers = await q.future
        self.questions.pop(q.id, None)
        if role == "implementor" and obj["state"] == ATTN:
            obj["state"], obj["attn"] = RUNNING, None
            run.save()
        return {"output": {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "allow",
            "updatedInput": {**q.tool_input, "answers": answers}}}}

    def answer(self, qid, answers, answer, by, source):
        q = self._q(qid)
        if not answers:
            if not q.questions:
                raise ValueError("this question has nothing to answer")
            answers = {q.questions[0]["question"]: answer}
        run = self.runs.get(q.run)
        if run and q.ticket and run.ticket(q.ticket):
            self.log(run, run.ticket(q.ticket), f"question answered by {by}" + (f" from {source}" if source else ""))
            run.event("answered", qid=qid, ticket=q.ticket, by=by, source=source, answers=answers)
        if not q.future.done():
            q.future.set_result(answers)
        return {}

    async def wait_verdict(self, run, t, kind, default, **info):
        if not self.orchestrator_alive(run):
            return {"action": default}
        fut = asyncio.get_running_loop().create_future()
        self.verdicts[(run.id, t["id"])] = fut
        run.event("verdict_needed", ticket=t["id"], kind=kind, **info,
                  hint=f"Decide with: fleet verdict {run.id} {t['id']} fix --note '...' | "
                       f"fleet verdict {run.id} {t['id']} escalate --diagnosis '...' --quote 'label::text' ...")
        try:
            return await asyncio.wait_for(fut, self.cfg["verdict_timeout_sec"])
        except asyncio.TimeoutError:
            run.event("verdict_timeout", ticket=t["id"], used=default)
            return {"action": default}
        finally:
            self.verdicts.pop((run.id, t["id"]), None)

    def verdict(self, rid, tid, req):
        run = self._run(rid)
        fut = self.verdicts.get((run.id, str(tid).lstrip("#")))
        if not fut or fut.done():
            raise ValueError(f"ticket #{tid} isn't waiting for a verdict")
        if req.get("action") not in ("fix", "escalate"):
            raise ValueError("action must be fix or escalate")
        fut.set_result({k: req.get(k) for k in ("action", "note", "diagnosis", "quotes")})
        return {}

    def block(self, reason):
        return {"output": {"decision": "block", "reason": reason}}

    async def stop_implementor(self, run, t, inp):
        if t["state"] == KILLED or run.d["status"] == "aborted":
            return {}
        wt = inp.get("cwd") or t["session"]["worktree"]
        base = run.d["base"]
        if await git.commits_ahead(wt, base) == 0:
            v = await self.wait_verdict(run, t, "stopped_without_commit", "escalate",
                                        last_message=trunc(inp.get("last_assistant_message"), 1200))
            if v["action"] == "fix":
                return self.block(v.get("note") or "You stopped without committing any work. Finish the ticket and commit it.")
            return self.escalate(run, t, "stopped", "Stopped without committing anything.",
                                 trunc(inp.get("last_assistant_message"), 600))
        if await git.tracked_changes(wt):
            t["dirtyBlocks"] = t.get("dirtyBlocks", 0) + 1
            if t["dirtyBlocks"] <= 2:
                return self.block("You have uncommitted changes. Commit your work on this branch before finishing.")
        test = (run.d["checks"] or {}).get("test")
        if test:
            t["state"] = TESTING
            run.save()
            rc, out = await run_shell(test, wt)
            if rc != 0:
                t["fixRound"] = t.get("fixRound", 0) + 1
                if t["fixRound"] == 1:
                    t["redAt"] = (await git.git(wt, "rev-parse", "HEAD"))[1]
                if t["fixRound"] > self.cfg["fix_rounds"]:
                    return self.escalate(run, t, "gave_up",
                                         f"Tests still fail after {self.cfg['fix_rounds']} fix rounds.", tail(out, 1500))
                tests_touched = [f for f in await git.changed_files(wt, t.get("redAt") or base)
                                 if re.search(r"(^|/)(tests?|spec|__tests__)/|[._-](test|spec)\.", f)]
                t["state"] = REVIEW
                run.save()
                v = await self.wait_verdict(run, t, "tests_red", "fix", round=t["fixRound"], output=tail(out),
                                            test_files_changed_in_fix=tests_touched)
                if v["action"] == "escalate":
                    return self.escalate(run, t, "business_logic", v.get("diagnosis") or "The tests and the ticket disagree.",
                                         tail(out, 1500), quotes=v.get("quotes") or [])
                t["state"] = RUNNING
                self.log(run, t, f"tests red, sent back (round {t['fixRound']})")
                run.save()
                note = f"\n\nNote from the orchestrator: {v['note']}" if v.get("note") else ""
                return self.block(f"Tests are failing (fix round {t['fixRound']} of {self.cfg['fix_rounds']}). "
                                  f"Fix the code, not the tests.{note}\n\n```\n{tail(out)}\n```")
        t["state"] = READY
        self.log(run, t, "tests green, ready to merge")
        run.event("ready", ticket=t["id"])
        run.save()
        asyncio.create_task(self.merge_ticket(run, t))
        return {}

    def escalate(self, run, t, kind, msg, output="", quotes=None):
        t["state"] = ATTN
        t["attn"] = {"kind": kind, "msg": msg, "output": output, "quotes": quotes or []}
        self.log(run, t, f"needs you: {msg}")
        run.event("attention", ticket=t["id"], kind=kind, msg=msg)
        run.save()
        return {}

    async def stop_merger(self, run, h, inp):
        wt = inp.get("cwd")
        base = run.d["base"]
        if not await git.is_ancestor(wt, base, "HEAD") or await git.tracked_changes(wt):
            h["blocks"] = h.get("blocks", 0) + 1
            if h["blocks"] <= 2:
                return self.block(f"`{base}` isn't fully merged into this branch yet, or there are uncommitted changes. "
                                  f"Finish `git merge {base}`, resolve every conflict, and commit.")
            h["state"] = "failed"
            return self.escalate(run, run.ticket(h["ticket"]), "merge_failed", "The merger couldn't finish the merge.")
        h["state"] = "done"
        run.save()
        t = run.ticket(h["ticket"])
        t["state"], t["attn"] = READY, None
        asyncio.create_task(self.merge_ticket(run, t))
        return {}

    async def stop_fixer(self, run, h, inp):
        wt = inp.get("cwd")
        if await git.commits_ahead(wt, run.d["base"]) == 0 and h.get("blocks", 0) < 1:
            h["blocks"] = 1
            return self.block("Commit your fix on this branch before finishing.")
        h["state"] = "done"
        run.save()
        asyncio.create_task(self.merge_fixer(run, h))
        return {}

    # ------------------------------------------------------------------ merging
    async def checkout_ok(self, run):
        repo, base = run.d["repo"], run.d["base"]
        if await git.current_branch(repo) != base:
            return f"{repo} isn't on `{base}` any more"
        if await git.tracked_changes(repo):
            return f"{repo} has uncommitted changes"
        return None

    def hold(self, run, reason, kind="hold"):
        run.d["held"] = {"kind": kind, "reason": reason, "since": time.time()}
        run.event("held", reason=reason)
        run.save()

    async def merge_ticket(self, run, t):
        async with self.lock(run.d["repo"]):
            problem = await self.checkout_ok(run)
            if problem:
                self.hold(run, f"Can't merge #{t['id']}: {problem}. Fix it, then resume the run.", "repo")
                notify(f"{run.d['name']}: merge paused", problem)
                return
            wt = t["session"]["worktree"]
            branch = await git.current_branch(wt)
            if not branch:
                return self.escalate(run, t, "merge_failed", f"Couldn't find the branch in {wt}.")
            t["state"] = MERGING
            run.save()
            ok, conflicted, out = await git.merge(run.d["repo"], branch, f"Merge #{t['id']}: {t['title']} (ai-fleet)")
            if conflicted:
                t["state"] = CONFLICT
                self.log(run, t, "merge conflict, merger started")
                run.event("conflict", ticket=t["id"], files=out.splitlines())
                run.save()
                await self.spawn_merger(run, t, out)
                return
            if not ok:
                return self.escalate(run, t, "merge_failed", "git merge failed.", tail(out, 1500))
            t["state"], t["attn"] = MERGED, None
            self.log(run, t, f"merged into {run.d['base']}")
            run.event("merged", ticket=t["id"])
            run.save()
            for s in [t["session"]] + [h for h in run.d["helpers"] if h.get("ticket") == t["id"]]:
                await claude.stop(s["short"])   # done; don't leave idle agents around
            quick = (run.d["checks"] or {}).get("quick")
            if quick:
                rc, out = await run_shell(quick, run.d["repo"])
                if rc != 0:
                    self.hold(run, f"`{run.d['base']}` went red after merging #{t['id']}. A fixer is on it.")
                    await self.spawn_fixer(run, f"merging ticket #{t['id']} ({t['title']})", quick, out)

    async def final_check(self, run):
        try:
            await self._final_check(run)
        except Exception as e:   # a crash here would leave the run looking busy forever
            run.d["finalCheck"] = "error"
            run.d["problem"] = {"kind": "final_check_failed", "msg": f"The final check crashed: {type(e).__name__}: {e}. "
                                                                     "Resume the run to try again."}
            run.event("attention", kind="final_check_failed", msg=run.d["problem"]["msg"])
            run.save()

    async def _final_check(self, run):
        full = (run.d["checks"] or {}).get("full") or (run.d["checks"] or {}).get("test")
        run.event("final_check", cmd=full or "", tickets=len(run.tickets))
        notify(f"{run.d['name']}: all {len(run.tickets)} tickets merged",
               f"Running the full suite on {run.d['base']} before calling the run done." if full else "Wrapping up.",
               urgent=False)
        async with self.lock(run.d["repo"]):
            rc, out = (await run_shell(full, run.d["repo"], timeout=3600)) if full else (0, "")
        if rc == 0:
            run.d["finalCheck"] = "cleanup"
            run.save()
            run.d["kept"] = await self.cleanup(run)
            run.d["status"], run.d["finalCheck"] = "done", "green"
            run.event("run_done", tickets=len(run.tickets), kept=run.d["kept"])
            run.save()
            notify(f"{run.d['name']}: run done",
                   f"All {len(run.tickets)} tickets merged and the full suite is green on {run.d['base']}. "
                   f"Nothing was pushed.", urgent=False)
        else:
            run.d["finalCheck"] = "red"
            self.hold(run, f"The full suite fails on `{run.d['base']}`. A fixer is on it.")
            await self.spawn_fixer(run, "the last ticket of the run", full, out, final=True)

    async def cleanup(self, run):
        """Remove a finished run's sessions and worktrees. Claude Code refuses to drop a worktree with commits that
        aren't pushed anywhere; we override that only after checking the branch is merged into the base branch.
        A worktree with any other leftovers (uncommitted or untracked files) is kept and reported."""
        kept = []
        for s in run.sessions():
            wt = s.get("worktree")
            branch = await git.current_branch(wt) if wt and os.path.isdir(wt) else None
            await claude.stop(s["short"])
            rc, out = await claude.rm(s["short"])
            token = re.search(r"--discard-unpushed (\S+)", out)
            if token and branch and await git.is_ancestor(run.d["repo"], branch, run.d["base"]):
                rc, out = await claude.rm(s["short"], token.group(1))
            if wt and os.path.isdir(wt):
                kept.append({"worktree": wt, "reason": out.strip().splitlines()[-1][:200] if out.strip() else "kept"})
        return kept

    async def spawn_merger(self, run, t, files):
        sid = str(uuid.uuid4())
        base = run.d["base"]
        quick = (run.d["checks"] or {}).get("quick")
        cmd = self.command(run, "merge_command")
        prompt = ((f"{cmd}\n\n" if cmd else "") + f"Merge `{base}` into this branch (`git merge {base}`) and resolve "
                  f"every conflict. This branch implements ticket #{t['id']}: {t['title']}. Conflicting files:\n{files}\n\n"
                  f"Keep the intent of both sides." + (f" Then run `{quick}` until it passes." if quick else "") +
                  " Commit the merge. Never push. If a conflict needs a product decision, ask with AskUserQuestion.")
        try:
            short = await claude.spawn_bg(cwd=t["session"]["worktree"], prompt=prompt, name=f"{run.d['name']} #{t['id']} merger",
                                          settings=self.write_settings(run, "merger", t["id"]), session_id=sid,
                                          permission_mode=self.cfg["permission_mode"], model=self.cfg["model"] or None)
        except RuntimeError as e:
            return self.escalate(run, t, "merge_failed", f"Merge conflict, and the merger couldn't start: {e}")
        run.d["helpers"].append({"kind": "merger", "ticket": t["id"], "sessionId": None, "short": short,
                                 "state": "run", "started": time.time(), "worktree": t["session"]["worktree"]})
        run.save()

    async def spawn_fixer(self, run, after, cmd, output, final=False):
        run.d["fixerRound"] = run.d.get("fixerRound", 0) + 1
        n = run.d["fixerRound"]
        if n > self.cfg["fix_rounds"]:
            run.d["problem"] = {"kind": "fixer_gave_up", "msg": f"`{run.d['base']}` is still red after {n - 1} fixers.",
                                "output": tail(output, 1500)}
            run.event("attention", kind="fixer_gave_up")
            run.save()
            return
        name = f"fleet-{slug(run.d['name'])}-fix{n}"
        sid = str(uuid.uuid4())
        prompt = (f"`{run.d['base']}` fails its checks after {after}. Find the cause and fix it with the smallest change "
                  f"that keeps every ticket's intent. Check command: `{cmd}`. Output:\n```\n{tail(output)}\n```\n"
                  f"Run the check until it passes, then commit on this branch. Never push.")
        try:
            short = await claude.spawn_bg(cwd=run.d["repo"], prompt=prompt, name=f"{run.d['name']} fixer {n}",
                                          settings=self.write_settings(run, "fixer", f"fix{n}"), session_id=sid,
                                          worktree=name, permission_mode=self.cfg["permission_mode"], model=self.cfg["model"] or None)
        except RuntimeError as e:
            run.d["problem"] = {"kind": "fixer_failed", "msg": f"Couldn't start a fixer: {e}"}
            run.save()
            return
        run.d["helpers"].append({"kind": "fixer", "sessionId": None, "short": short, "state": "run", "final": final,
                                 "started": time.time(), "worktree": f"{run.d['repo']}/.claude/worktrees/{name}",
                                 "cmd": cmd, "after": after})
        run.save()

    async def merge_fixer(self, run, h):
        async with self.lock(run.d["repo"]):
            problem = await self.checkout_ok(run)
            if problem:
                self.hold(run, f"Can't merge the fix: {problem}. Fix it, then resume the run.", "repo")
                return
            branch = await git.current_branch(h["worktree"])
            ok, conflicted, out = await git.merge(run.d["repo"], branch, "Fix checks (ai-fleet fixer)")
            if not ok:
                run.d["problem"] = {"kind": "fixer_failed", "msg": "The fixer's branch didn't merge cleanly.", "output": tail(out, 1500)}
                run.save()
                return
            rc, out = await run_shell(h["cmd"], run.d["repo"], timeout=3600)
        if rc == 0:
            run.d["held"] = None
            run.d["problem"] = None
            run.event("green_again")
            if h.get("final"):
                run.d["finalCheck"] = None   # schedule() re-runs the full check, then finishes the run
            run.save()
        else:
            await self.spawn_fixer(run, h["after"], h["cmd"], out, final=h.get("final"))

    # ------------------------------------------------------------------ control
    async def ctl(self, req):
        a = req["action"]
        if a == "open":
            short = req["session"]
            subprocess.Popen(["setsid", "uwsm-app", "--", "xdg-terminal-exec", "--app-id=ai-fleet.attach",
                              f"--title=claude {short}", "-e", claude.CLAUDE, "attach", short],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return {}
        if a == "kill-session":
            await claude.stop(req["session"])
            return {}
        if a == "continue":
            return await self.continue_limited(req.get("note"))
        run = self._run(req["run"])
        if a == "pause":
            run.d["status"] = "paused"
        elif a == "resume":
            run.d["status"] = "active"
            if run.d.get("finalCheck") == "error":
                run.d["finalCheck"], run.d["problem"] = None, None
            if (run.d.get("held") or {}).get("kind") == "repo":
                run.d["held"] = None
                for t in run.tickets.values():
                    if t["state"] in (READY, MERGING):
                        t["state"] = READY
                        asyncio.create_task(self.merge_ticket(run, t))
        elif a == "abort":
            await self.abort(run)
        else:
            t = run.ticket(req["ticket"])
            if not t:
                raise ValueError(f"no ticket #{req['ticket']} in {run.id}")
            if a == "kill":
                await self.kill_ticket(run, t)
            elif a == "retry" and (t.get("attn") or {}).get("kind") == "merge_failed":
                for h in run.d["helpers"]:   # a stalled merger would share the worktree with the next one
                    if h["kind"] == "merger" and h.get("ticket") == t["id"] and h.get("state") == "run":
                        await claude.stop(h["short"])
                        h["state"] = "killed"
                t["state"], t["attn"] = READY, None     # the work is done; only the merge needs another go
                asyncio.create_task(self.merge_ticket(run, t))
            elif a == "retry":
                if t.get("session"):
                    await claude.stop(t["session"]["short"])
                t["state"], t["attn"] = WAIT, None
                self.log(run, t, "retry requested")
            elif a == "sendback":
                await self.send_back(run, t, req.get("note") or "Continue the ticket.")
            else:
                raise ValueError(f"unknown action {a!r}")
        run.save()
        return {}

    async def kill_ticket(self, run, t):
        if t.get("session"):
            await claude.stop(t["session"]["short"])
        fut = self.verdicts.get((run.id, t["id"]))
        if fut and not fut.done():
            fut.set_result({"action": "escalate"})
        for q in list(self.questions.values()):
            if q.run == run.id and q.ticket == t["id"] and not q.future.done():
                q.future.set_result({})
        t["state"], t["attn"] = KILLED, None
        self.log(run, t, "killed; worktree kept")
        run.event("killed", ticket=t["id"])

    async def send_back(self, run, t, note):
        s = t.get("session")
        if not s:
            raise ValueError("this ticket never started")
        await claude.stop(s["short"])
        t["state"], t["attn"], t["fixRound"] = RUNNING, None, 0
        s["started"] = time.time()   # the stall check waits for a reply after this
        try:
            short = await claude.spawn_bg(cwd=s["worktree"], prompt=note, resume=s["sessionId"],
                                          name=f"{run.d['name']} #{t['id']} implementor",
                                          settings=self.write_settings(run, "implementor", t["id"]),
                                          permission_mode=self.cfg["permission_mode"], model=self.cfg["model"] or None)
            s["short"] = short
            self.log(run, t, "sent back with your note")
        except RuntimeError as e:
            self.escalate(run, t, "spawn_failed", f"Couldn't resume the implementor: {e}")

    # ------------------------------------------------------------------ usage limit
    def usage(self):
        """The account's rate limits, from the freshest statusline input any session wrote, and whether they're hit.
        Past `resets_at` a window counts as reset even if no session has reported since."""
        now = time.time()
        if now - getattr(self, "_usage_at", 0) < 1:
            return self._usage
        newest, rl = 0, {}
        for p in paths.STATUSLINE.glob("*.json"):
            try:
                mt = p.stat().st_mtime
                if mt > newest:
                    d = json.loads(p.read_text())
                    if d.get("rate_limits"):
                        newest, rl = mt, d["rate_limits"]
            except (OSError, json.JSONDecodeError):
                pass
        windows, until = {}, None
        for k in ("five_hour", "seven_day"):
            w = rl.get(k) or {}
            reset = w.get("resets_at")
            pct = 0 if reset and reset <= now else w.get("used_percentage")
            windows[k] = {"used": pct, "resetsAt": reset}
            if pct is not None and pct >= 100:
                until = max(until or 0, reset or 0) or None
        hit = [v.main.limited for v in self.views.values() if v.main and v.main.limited]
        if hit and not until:   # a session hit it; the statusline may not have caught up
            until = windows["five_hour"]["resetsAt"] if (windows["five_hour"]["resetsAt"] or 0) > now else None
        limited = bool(until and until > now) or (bool(hit) and until is None and not rl)
        self._usage_at, self._usage = now, {**windows, "limited": limited, "until": until if limited else None,
                                            "stopped": len(self.limited_sessions())}
        return self._usage

    def limited_sessions(self):
        return [sid for sid, v in self.views.items() if v.main and v.main.limited]

    async def continue_limited(self, note=None):
        """Resume every background session the usage limit stopped, telling it to carry on."""
        note = note or ("Your last turn was cut off by the account's usage limit, which has reset now. "
                        "Continue exactly where you left off.")
        resumed, skipped = [], []
        for sid in self.limited_sessions():
            a, main = self.agents.get(sid) or {}, self.views[sid].main
            if a.get("kind") != "background":
                skipped.append(a.get("name") or sid[:8])
                continue
            run, role, obj = self.locate(sid)
            if run:
                settings = self.write_settings(run, role, obj["id"] if role == "implementor" else obj.get("ticket"))
                mode, model = self.cfg["permission_mode"], self.cfg["model"] or None
            else:
                settings = paths.STATE / "manual-settings.json"
                settings.write_text(json.dumps({"statusLine": {"type": "command", "command": str(paths.STATUSLINE_HOOK), "padding": 0}}))
                mode, model = main.permission_mode or "default", None
            await claude.stop(a.get("id") or sid[:8])
            try:
                short = await claude.spawn_bg(cwd=a.get("cwd") or main.workdir, prompt=note, resume=sid,
                                              name=a.get("name") or "claude", settings=settings,
                                              permission_mode=mode, model=model)
            except RuntimeError as e:
                skipped.append(f"{a.get('name') or sid[:8]} ({e})")
                continue
            main.limited = None
            if run:
                obj = obj.get("session") if role == "implementor" else obj
                obj["short"], obj["started"] = short, time.time()   # `started` keeps poll() from calling it ended
                run.event("continued", role=role, session=short)
                run.save()
            resumed.append(short)
        self._usage_at = 0
        return {"resumed": resumed, "skipped": skipped}

    async def abort(self, run):
        for t in run.tickets.values():
            if t["state"] not in (MERGED, KILLED, WAIT):
                await self.kill_ticket(run, t)
            elif t["state"] == WAIT:
                t["state"] = KILLED
        for h in run.d["helpers"]:
            if h.get("state") == "run":
                await claude.stop(h["short"])
                h["state"] = "killed"
        run.d["status"] = "aborted"
        run.event("aborted")

    # ------------------------------------------------------------------ sudo (askpass through the panel)
    async def sudo_request(self, req, pid):
        sid = await self.session_for_pid(pid)
        rid = "s" + uuid.uuid4().hex[:8]
        fut = asyncio.get_running_loop().create_future()
        a = self.agents.get(sid or "", {})
        self.sudo[rid] = {"id": rid, "session": sid, "short": a.get("id") or (sid or "")[:8],
                          "name": a.get("name") or "a Claude session", "command": req.get("command", ""),
                          "prompt": req.get("prompt", ""), "created": time.time(), "future": fut}
        try:
            pw = await asyncio.wait_for(fut, 300)
        except asyncio.TimeoutError:
            pw = None
        finally:
            self.sudo.pop(rid, None)
        return {"password": pw} if pw is not None else {"denied": True}

    def sudo_answer(self, rid, password, deny):
        s = self.sudo.get(rid)
        if not s:
            raise ValueError("that sudo request is gone")
        if not s["future"].done():
            s["future"].set_result(None if deny else password)
        return {}

    # ------------------------------------------------------------------ polling
    async def poll(self):
        agents = await claude.agents(include_done=True)
        self.agents = {a.get("sessionId"): a for a in agents if a.get("sessionId")}
        by_short = {a.get("id"): a.get("sessionId") for a in agents if a.get("id")}
        for r in self.runs.values():   # learn the real session id behind each short id
            changed = False
            for s in r.sessions():
                real = by_short.get(s.get("short"))
                if real and s.get("sessionId") != real:
                    s["sessionId"], changed = real, True
            if changed:
                r.save()
        wanted = set()
        for r in self.runs.values():
            if r.d["status"] in ("done", "aborted") and time.time() - r.d.get("created", 0) > 86400:
                continue
            for sid in [r.d.get("orchestrator")] + [(t.get("session") or {}).get("sessionId") for t in r.tickets.values()] \
                    + [h.get("sessionId") for h in r.d["helpers"]]:
                if sid:
                    wanted.add(sid)
        for a in agents:
            if alive(a) and not str(a.get("cwd", "")).startswith(str(paths.STATE)):
                wanted.add(a.get("sessionId"))
        for sid in wanted:
            a = self.agents.get(sid, {})
            v = self.views.get(sid)
            if v is None:
                v = self.views[sid] = SessionView(sid, a.get("cwd"))
            v.poll()
            self._learn_window(sid)
        for sid in list(self.views):
            if sid not in wanted:
                del self.views[sid]
        # implementors whose session ended without passing the stop gate
        for r in self.runs.values():
            for t in r.tickets.values():
                s = t.get("session") or {}
                a = self.agents.get(s.get("sessionId"))
                if t["state"] == RUNNING and a and not alive(a) and time.time() - s.get("started", 0) > 60:
                    self.escalate(r, t, "session_ended", "The implementor's session ended before the ticket was done.")
        self.check_stalls()

    def stalled(self, s):
        """Why a fleet session that should be working isn't, or None. A session that never got past an unknown slash
        command counts at once; any other gets `stall_sec` to send its first reply after it started."""
        sid = (s or {}).get("sessionId")
        v = self.views.get(sid)
        main = v.main if v else None
        if main and main.unknown_command:
            return f"never started: {main.unknown_command}"
        wait = self.cfg["stall_sec"]
        if not s or time.time() - s.get("started", time.time()) < wait or not alive(self.agents.get(sid)):
            return None   # too early, or ended (the session_ended check covers that)
        if (main and main.limited) or self.usage()["limited"]:
            return None
        if not main:
            return f"has no transcript {wait // 60} min after starting"
        if (main.replied_at or 0) < s["started"]:
            return f"hasn't replied in the {wait // 60} min since it started"
        return None

    def check_stalls(self):
        for r in self.runs.values():
            if r.d["status"] not in LIVE_RUN:
                continue
            for t in r.tickets.values():
                why = self.stalled(t.get("session")) if t["state"] == RUNNING else None
                if why:
                    self.escalate(r, t, "stalled", f"The implementor {why}. Open it, or retry the ticket.")
            for h in r.d["helpers"]:
                why = self.stalled(h) if h.get("state") == "run" and not h.get("stalled") else None
                if not why:
                    continue
                h["stalled"] = True
                t = r.ticket(h.get("ticket")) if h["kind"] == "merger" else None
                if t and t["state"] == CONFLICT:
                    self.escalate(r, t, "merge_failed", f"The merger {why}. Retry starts a new merger.")
                elif h["kind"] == "fixer":
                    r.d["problem"] = {"kind": "fixer_stalled", "msg": f"The fixer {why}. Open it to nudge it."}
                    r.event("attention", kind="fixer_stalled", msg=r.d["problem"]["msg"])
                r.save()

    def _learn_window(self, sid):
        p = paths.STATUSLINE / f"{sid}.json"
        try:
            d = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            return
        model, size = (d.get("model") or {}).get("id"), (d.get("context_window") or {}).get("context_window_size")
        if model and size and self.windows.get(model) != size:
            self.windows[model] = size
            paths.MODEL_WINDOWS.write_text(json.dumps(self.windows))

    def window_for(self, model):
        if model in self.windows:
            return self.windows[model]
        return 1_000_000 if model and re.search(r"-5(-\d+)?(-|$)", model) else 200_000

    # ------------------------------------------------------------------ AI summaries
    async def summarize(self):
        if self.cfg["summaries"] != "ai" or time.time() - self.last_view > 15:
            return
        if time.time() - getattr(self, "_last_sum", 0) < self.cfg["summary_interval_sec"]:
            return
        self._last_sum = time.time()
        items = {}
        self._sum_sig = getattr(self, "_sum_sig", {})

        def collect(n):
            if n.get("events") and n.get("state") in ("run", "attn"):
                sig = (len(n["events"]), n["events"][-1], n.get("activity"))
                if self._sum_sig.get(n["id"]) != sig or n["id"] not in self.summaries:
                    items[n["id"]] = {"task": n.get("task", ""), "activity": n.get("activity", "working"),
                                      "recent_steps": n["events"][-12:]}
                    self._sum_sig[n["id"]] = sig
            for c in n.get("children", []):
                collect(c)

        snap = self.snapshot()
        for r in snap["runs"]:
            collect(r["tree"])
        for s in snap["sessions"]:
            collect(s)
        if not items:
            return
        prompt = ("You write the one-line status shown beside each AI coding agent on a dashboard. For each agent below, "
                  "write ONE plain sentence of at most 18 words saying what it is working on and where it is in that work, "
                  "using its task and recent steps. Describe the activity in your own words; don't quote or restate its last "
                  "message. If activity is idle or finished, say what it got done and that it's waiting for the user. "
                  "If it's waiting for you, say what it needs. Skip file paths unless they're the point. "
                  "Reply with only a JSON object mapping each id to its sentence.\n\n" + json.dumps(items, indent=1))
        out = await claude.print_once(prompt, model=self.cfg["summary_model"], cwd=paths.SUMMARY_CWD)
        try:
            self.summaries.update(json.loads(out[out.index("{"): out.rindex("}") + 1]))
        except ValueError:
            pass

    # ------------------------------------------------------------------ state for the panel
    def session_node(self, sid, kind, name, tag="", state=None, status=None, extra=None):
        a = self.agents.get(sid or "", {})
        v = self.views.get(sid)
        main = v.main if v else None
        live = alive(a)
        ctx = {"used": main.ctx if main else 0, "size": self.window_for(main.model if main else None)}
        try:
            cw = json.loads((paths.STATUSLINE / f"{sid}.json").read_text()).get("context_window") or {}
            if cw.get("context_window_size"):
                cu = cw.get("current_usage") or {}
                ctx = {"used": sum(cu.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens",
                                                              "cache_read_input_tokens")) or ctx["used"],
                       "size": cw["context_window_size"]}
        except (OSError, json.JSONDecodeError):
            pass
        waiting = a.get("waitingFor") if a.get("status") == "waiting" else None
        if state is None:
            state = "attn" if waiting else ("run" if live else "done")
        limited = bool(main and main.limited)
        if limited and state in ("run", "attn", "done"):
            until = self.usage().get("until")
            state = "wait"
            status = "Stopped by the usage limit" + (time.strftime(" · resets %H:%M", time.localtime(until)) if until else "") \
                + ("" if a.get("kind") == "background" else " · type `continue` in its terminal")
        if status is None:
            status = (main.status if main else "Starting…")
            if waiting:
                open_tool = next(iter(main.open_tools.values()), None) if main else None
                status = f"Waiting for {waiting}" + (f": {describe(open_tool[0], open_tool[1], a.get('cwd'))}" if open_tool else "")
            elif live and a.get("status") == "idle":
                status = "Idle · " + status.removeprefix("Said: ")
        started = (a.get("startedAt") or 0) / 1000 or (main.first_ts if main else None)
        node = {"id": sid, "sessionId": sid, "short": a.get("id") or (sid or "")[:8], "kind": kind, "name": name,
                "tag": tag, "state": state, "alive": live, "waitingFor": waiting, "ctx": ctx,
                "tokens": main.tokens if main else 0, "startedAt": started,
                "endedAt": (main.last_ts if main else None) if not live else None,
                "status": status, "summary": self.summaries.get(sid), "events": list(main.events) if main else [],
                "task": main.task if main else "", "activity": "waiting for you" if waiting else
                ("working" if a.get("status") == "busy" else "idle" if live else "finished"),
                "limited": limited,
                "children": v.tree(self.cfg["roles"], self.window_for, session_alive=live) if v else []}
        for c in node["children"]:
            self._add_summaries(c)
        node["claudeMd"] = memory.claude_md(a.get("cwd") or (main.workdir if main else None) or (v.cwd if v else None))
        node.update(extra or {})
        if limited:
            node["note"] = "usage limit"
        return node

    def _add_summaries(self, n):
        n["summary"] = self.summaries.get(n["id"])
        for c in n.get("children", []):
            self._add_summaries(c)

    def ticket_node(self, run, t):
        s = t.get("session") or {}
        st, status = t["state"], None
        state = {RUNNING: "run", TESTING: "run", REVIEW: "run", READY: "run", MERGING: "run", CONFLICT: "run",
                 ATTN: "attn", MERGED: "done", KILLED: "killed"}.get(st, "wait")
        notes = {TESTING: "testing", REVIEW: "tests red", READY: "merging", MERGING: "merging", CONFLICT: "conflict"}
        if st == TESTING:
            status = f"Running the tests: {run.d['checks'].get('test')}"
        elif st == REVIEW:
            status = "Tests failed; the orchestrator is deciding what to do"
        elif st == ATTN:
            status = (t.get("attn") or {}).get("msg") or "Needs you"
        elif st == MERGED:
            status = f"Merged into {run.d['base']}"
        node = self.session_node(s.get("sessionId"), "implementor", "implementor", f"#{t['id']} {t['title']}",
                                 state=state, status=status,
                                 extra={"ticket": t["id"], "note": notes.get(st) or (
                                     f"fix round {t['fixRound']}/{self.cfg['fix_rounds']}" if t.get("fixRound") else "")})
        if node["limited"]:
            node["state"], node["status"] = "wait", self.session_node(s.get("sessionId"), "x", "x")["status"]
        elif node["waitingFor"] and state == "run":
            node["state"] = "attn"
            node["status"] = self.session_node(s.get("sessionId"), "x", "x")["status"]
        return node

    def snapshot(self):
        runs_out, attention = [], []
        fleet_sids = set()
        for r in sorted(self.runs.values(), key=lambda r: r.d["created"]):
            if r.d["status"] in ("done", "aborted") and time.time() - r.d.get("created", 0) > 6 * 3600:
                continue
            fleet_sids.add(r.d.get("orchestrator"))
            tickets = [{"id": t["id"], "title": t["title"], "blockedBy": t["blockedBy"],
                        "state": t["state"], "blockedOn": r.blocked_by_problem(t) if t["state"] == WAIT else [],
                        "short": (t.get("session") or {}).get("short")}
                       for t in r.tickets.values()]
            if r.d["status"] == "queued":
                runs_out.append({"id": r.id, "name": r.d["name"], "repo": r.d["repo"], "status": "queued", "tickets": tickets})
                continue
            lanes = []
            for t in r.tickets.values():
                if t.get("session"):
                    fleet_sids.add(t["session"]["sessionId"])
                    if t["state"] != MERGED:   # a merged ticket's session stays reachable from the graph
                        lanes.append(self.ticket_node(r, t))
            for h in r.d["helpers"]:
                fleet_sids.add(h["sessionId"])
                if h.get("state") == "run" or time.time() - h.get("started", 0) < 600:
                    tag = f"#{h['ticket']} → {r.d['base']}" if h["kind"] == "merger" else f"{r.d['base']} after {h.get('after', '')}"
                    lanes.append(self.session_node(h["sessionId"], h["kind"], h["kind"], tag,
                                                   state=None if h.get("state") == "run" else "done"))
            orch = r.d.get("orchestrator")
            tree = self.session_node(orch, "orchestrator", "orchestrator", r.d["name"]) if orch else {
                "id": f"orch-{r.id}", "kind": "orchestrator", "name": "orchestrator", "tag": r.d["name"],
                "state": "run", "status": "No orchestrator session attached", "children": [], "ctx": None, "tokens": 0}
            tree["children"] = lanes + [c for c in tree.get("children", []) if c["kind"] != "implementor"]
            if orch and r.d["status"] in LIVE_RUN and not tree["alive"]:
                # The orchestrator's session ended (often a usage limit) but the run goes on; don't call it done.
                states = {c.get("state") for c in lanes}
                tree["state"] = "attn" if "attn" in states else "run" if "run" in states or \
                    r.d.get("finalCheck") in ("running", "cleanup") else "wait"
                tree["status"] = "Orchestrator stopped; the run goes on without it · " + (
                    (r.d.get("held") or {}).get("reason") or f"{sum(t['state'] == MERGED for t in r.tickets.values())}"
                                                             f"/{len(r.tickets)} merged")
                tree["note"], tree["endedAt"] = "no orchestrator", None
            runs_out.append({"id": r.id, "name": r.d["name"], "repo": r.d["repo"], "base": r.d["base"],
                             "status": r.d["status"], "held": r.d.get("held"), "problem": r.d.get("problem"),
                             "finalCheck": r.d.get("finalCheck"), "finalCheckAt": r.d.get("finalCheckAt"),
                             "finalCmd": (r.d["checks"] or {}).get("full") or (r.d["checks"] or {}).get("test") or "",
                             "slots": {"used": r.slots_used(), "max": self.cfg["implementors_per_orchestrator"]},
                             "tickets": tickets, "tree": tree})
            for t in r.tickets.values():
                at = t.get("attn") or {}
                if t["state"] == ATTN and at.get("kind") != "question":
                    attention.append({"id": f"{r.id}:{t['id']}:{at.get('kind')}", "type": at.get("kind"), "run": r.id,
                                      "ticket": t["id"], "who": f"implementor · #{t['id']} {t['title']}", "where": r.d["name"],
                                      "msg": at.get("msg"), "output": at.get("output"), "quotes": at.get("quotes") or [],
                                      "session": (t.get("session") or {}).get("short")})
            if r.d.get("problem"):
                p = r.d["problem"]
                attention.append({"id": f"{r.id}:problem:{p['kind']}", "type": p["kind"], "run": r.id,
                                  "who": f"run · {r.d['name']}", "where": r.d["repo"], "msg": p["msg"], "output": p.get("output")})
            if (r.d.get("held") or {}).get("kind") == "repo":
                attention.append({"id": f"{r.id}:held", "type": "repo", "run": r.id, "who": f"run · {r.d['name']}",
                                  "where": r.d["repo"], "msg": r.d["held"]["reason"]})
        for q in self.questions.values():
            if q.state == "user":
                r = self.runs.get(q.run)
                t = r.ticket(q.ticket) if r and q.ticket else None
                attention.append({"id": q.id, "type": "question", "qid": q.id, "run": q.run, "ticket": q.ticket,
                                  "who": f"implementor · #{q.ticket} {t['title'] if t else ''}", "where": r.d["name"] if r else "",
                                  "msg": (q.questions[0] if q.questions else {}).get("question", ""), "why": q.why,
                                  "questions": q.questions, "session": (self.agents.get(q.session) or {}).get("id")})
        for s in self.sudo.values():
            attention.append({"id": s["id"], "type": "sudo", "who": s["name"], "where": "sudo", "session": s["short"],
                              "msg": s["command"] or "A command needs sudo", "why": s["prompt"]})
        sessions = []
        for sid, a in self.agents.items():
            if sid in fleet_sids or not alive(a) or str(a.get("cwd", "")).startswith(str(paths.STATE)):
                continue
            cwd = str(a.get("cwd", "")).replace(str(paths.HOME), "~", 1)
            sessions.append(self.session_node(sid, "session", "claude", cwd, extra={"label": a.get("name")}))
        for n in [*(r.get("tree") for r in runs_out if r.get("tree")), *sessions]:
            self._collect_permission(n, attention)
        return {"updated": time.time(), "daemon": os.getpid(),
                "limits": {"orchestrators": self.cfg["orchestrators"],
                           "implementors_per_orchestrator": self.cfg["implementors_per_orchestrator"]},
                "summaries": self.cfg["summaries"], "usage": self.usage(), "attention": attention, "runs": runs_out, "sessions": sessions}

    def _collect_permission(self, n, out):
        if n.get("waitingFor") and "permission" in n["waitingFor"]:
            out.append({"id": f"perm:{n['sessionId']}", "type": "permission", "session": n.get("short"),
                        "who": f"{n['name']} · {n.get('tag', '')}", "where": "", "msg": n.get("status")})
        for c in n.get("children", []):
            if c.get("sessionId"):
                self._collect_permission(c, out)

    async def write_state(self):
        snap = self.snapshot()
        for a in snap["attention"]:
            if a["id"] not in self.notified:
                self.notified.add(a["id"])
                notify(f"{a['who']}", a.get("msg") or a["type"])
        u = snap["usage"]
        if u["limited"] and ("limit", u["until"]) not in self.notified:
            self.notified.add(("limit", u["until"]))
            notify("Usage limit reached", "Agents stop until it resets" + (
                time.strftime(" at %H:%M", time.localtime(u["until"])) if u["until"] else "") + ". No new tickets start until then.")
        elif not u["limited"] and u["stopped"] and ("limit-reset", u["five_hour"]["resetsAt"]) not in self.notified:
            self.notified.add(("limit-reset", u["five_hour"]["resetsAt"]))
            notify("Usage limit reset", f"{u['stopped']} agent(s) are waiting. Click Continue in the Fleet panel.")
        body = json.dumps(snap)
        if body != self.last_state:
            self.last_state = body
            tmp = paths.STATE_JSON.with_suffix(".tmp")
            tmp.write_text(body)
            tmp.replace(paths.STATE_JSON)


def main():
    fleet = Fleet()
    print(f"ai-fleet daemon on {paths.SOCK}", flush=True)
    asyncio.run(fleet.serve())
