"""Incremental readers for Claude Code transcripts, and the agent tree built from them.

A session's transcript is ~/.claude/projects/<munged cwd>/<session-id>.jsonl. Its subagents live in
<session-id>/subagents/agent-<id>.jsonl, each with a .meta.json naming its description, agent type and
the Agent tool_use id that started it (which may sit in the main transcript or in another subagent's).
"""
import json
import os
import re
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from . import paths

SHELL_MIN_SEC = 3          # a Bash call shows as its own row once it has run this long
AGENT_IDLE_DONE_SEC = 90   # a subagent with no new lines for this long counts as finished


def parse_ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def short_path(p, cwd=None):
    if not p:
        return ""
    if cwd and p.startswith(cwd.rstrip("/") + "/"):
        return p[len(cwd.rstrip("/")) + 1:]
    return p.replace(str(paths.HOME), "~", 1)


def trunc(s, n=70):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def describe(name, inp, cwd=None):
    """One mechanical status line for a tool call."""
    i = inp or {}
    fp = lambda: short_path(i.get("file_path") or i.get("notebook_path") or "", cwd)
    if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return f"Editing {fp()}"
    if name == "Read":
        return f"Reading {fp()}"
    if name == "Bash":
        return f"Running {trunc(i.get('command'), 60)}"
    if name == "Grep":
        return f"Searching for {trunc(i.get('pattern'), 40)!r}"
    if name == "Glob":
        return f"Finding files {trunc(i.get('pattern'), 40)}"
    if name in ("Agent", "Task"):
        return f"Started agent: {trunc(i.get('description'), 50)}"
    if name == "Skill":
        return f"Using /{i.get('skill', '').split(':')[-1]}"
    if name == "AskUserQuestion":
        qs = i.get("questions") or [{}]
        return f"Asked: {trunc(qs[0].get('question'), 60)}"
    if name in ("WebSearch", "WebFetch"):
        return f"Searching the web: {trunc(i.get('query') or i.get('url'), 50)}"
    if name in ("TodoWrite", "TaskCreate", "TaskUpdate"):
        return "Updating its task list"
    if name == "SubagentHandback":
        return f"Reported back: {trunc(i.get('message'), 60)}"
    return f"Using {name}"


LIMIT_TEXT = re.compile(r"usage limit|hit your (session |weekly )?limit|limit reached|rate.?limit", re.I)


def is_limit_error(d):
    """A synthetic assistant message Claude Code writes when the account's usage limit stops a turn."""
    if not d.get("isApiErrorMessage"):
        return False
    if d.get("error") in ("rate_limit", "usage_limit"):
        return True
    content = (d.get("message") or {}).get("content")
    text = " ".join(x.get("text", "") for x in content if isinstance(x, dict)) if isinstance(content, list) else str(content or "")
    return bool(LIMIT_TEXT.search(text))


class Track:
    """One transcript file, read incrementally."""

    def __init__(self, path: Path, cwd=None):
        self.path, self.cwd = path, cwd
        self.pos = 0
        self.buf = b""
        self.msg_ids = set()
        self.model = None
        self.ctx = 0               # tokens in context after the latest request
        self.tokens = 0            # fresh tokens processed (input + cache writes + output)
        self.first_ts = self.last_ts = None
        self.mtime = 0
        self.status = ""
        self.events = deque(maxlen=24)   # recent human-readable steps, for AI summaries
        self.open_tools = {}             # tool_use_id -> (name, input, ts, skill_id)
        self.skills = []                 # [(tool_use_id, skill, ts)]
        self.agent_parent_skill = {}     # Agent tool_use_id -> skill tool_use_id (or None)
        self.current_skill = None
        self.handed_back = False
        self.slash = None                # leading /command of the first prompt
        self.task = ""                   # what the session or subagent was asked to do
        self.workdir = None              # cwd recorded in the transcript
        self.permission_mode = None      # latest permissionMode recorded on a prompt
        self.limited = None              # (ts, message) while the last reply was a usage-limit error
        self.replied_at = None           # ts of the model's latest real reply
        self.unknown_command = None      # "Unknown command: /x" while the session never got past its slash command

    def poll(self):
        try:
            st = self.path.stat()
        except FileNotFoundError:
            return
        self.mtime = st.st_mtime
        if st.st_size < self.pos:   # rewritten; start over
            self.__init__(self.path, self.cwd)
        if st.st_size == self.pos:
            return
        with open(self.path, "rb") as f:
            f.seek(self.pos)
            data = f.read()
        self.pos += len(data)
        data = self.buf + data
        lines = data.split(b"\n")
        self.buf = lines.pop()
        for line in lines:
            if line.strip():
                try:
                    self._entry(json.loads(line))
                except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
                    pass

    def _entry(self, d):
        ts = parse_ts(d.get("timestamp"))
        if ts:
            self.first_ts = self.first_ts or ts
            self.last_ts = ts
        self.workdir = self.workdir or d.get("cwd")
        self.permission_mode = d.get("permissionMode") or self.permission_mode
        m = d.get("message") or {}
        content = m.get("content")
        kind = d.get("type")
        if kind == "system" and str(d.get("content") or "").startswith("Unknown command:"):
            self.unknown_command = d["content"]
        if kind == "user" and isinstance(content, str) and not self.task and not d.get("isMeta"):
            text = content
            if "<command-args>" in text:
                text = text.split("<command-args>")[1].split("</command-args>")[0]
            if text.strip() and not text.lstrip().startswith("<"):
                self.task = trunc(text, 400)
        if kind == "user" and isinstance(content, str):
            if self.slash is None and "<command-name>" in content:
                self.slash = content.split("<command-name>")[1].split("</command-name>")[0]
            elif self.slash is None:
                self.slash = ""
        if kind == "assistant" and is_limit_error(d):
            self.limited = (ts, trunc(content[0].get("text") if isinstance(content, list) and content else "", 120))
            self.status = "Stopped by the usage limit"
            return
        if kind == "assistant":
            self.limited = None
            self.unknown_command = None
            self.replied_at = ts or self.replied_at
            self.model = m.get("model") or self.model
            u = m.get("usage")
            mid = m.get("id")
            if u and mid not in self.msg_ids:
                self.msg_ids.add(mid)
                fresh = (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)
                self.ctx = fresh + (u.get("cache_read_input_tokens") or 0)
                self.tokens += fresh + (u.get("output_tokens") or 0)
            for x in content if isinstance(content, list) else []:
                t = x.get("type")
                if t == "tool_use":
                    name, inp = x.get("name"), x.get("input") or {}
                    self.open_tools[x.get("id")] = (name, inp, ts, self.current_skill)
                    self.status = describe(name, inp, self.cwd)
                    self.events.append(self.status)
                    if name == "Skill":
                        self.skills.append((x.get("id"), inp.get("skill", ""), ts))
                        self.current_skill = x.get("id")
                    elif name in ("Agent", "Task"):
                        self.agent_parent_skill[x.get("id")] = self.current_skill
                    elif name == "SubagentHandback":
                        self.handed_back = True
                elif t == "text" and x.get("text", "").strip():
                    self.status = "Said: " + trunc(x["text"], 80)
                    self.events.append(self.status)
        elif kind == "user" and isinstance(content, list):
            for x in content:
                if x.get("type") == "tool_result":
                    self.open_tools.pop(x.get("tool_use_id"), None)

    def running_shells(self, now):
        return [(tid, inp, t0, sk) for tid, (name, inp, t0, sk) in self.open_tools.items()
                if name == "Bash" and t0 and now - t0 >= SHELL_MIN_SEC]


def find_transcript(session_id: str):
    hits = list(paths.CLAUDE_PROJECTS.glob(f"*/{session_id}.jsonl"))
    return max(hits, key=lambda p: p.stat().st_mtime) if hits else None


class SessionView:
    """A session's main transcript plus all its subagents."""

    def __init__(self, session_id, cwd=None):
        self.session_id, self.cwd = session_id, cwd
        self.main = None
        self.subs = {}   # agent id -> (Track, meta)

    def poll(self):
        if self.main is None:
            p = find_transcript(self.session_id)
            if p is None:
                return
            self.main = Track(p, self.cwd)
        self.main.poll()
        sub_dir = self.main.path.with_suffix("") / "subagents"
        if sub_dir.is_dir():
            for meta_path in sub_dir.glob("agent-*.meta.json"):
                aid = meta_path.name[len("agent-"):-len(".meta.json")]
                if aid not in self.subs:
                    try:
                        meta = json.loads(meta_path.read_text())
                    except (OSError, json.JSONDecodeError):
                        continue
                    self.subs[aid] = (Track(sub_dir / f"agent-{aid}.jsonl", self.cwd), meta)
            for tr, _ in self.subs.values():
                tr.poll()

    # ---- tree ----
    def tree(self, roles, window_for, now=None, session_alive=True):
        """Children of this session's node: skill rows, subagent rows and long-running shell rows."""
        now = now or time.time()
        if not self.main:
            return []
        return self._children(self.main, roles, window_for, now, session_alive)

    def _children(self, tr, roles, window_for, now, alive):
        skill_nodes, order, loose = {}, [], []
        for i, (tid, skill, t0) in enumerate(tr.skills):
            short = skill.split(":")[-1]
            nxt = tr.skills[i + 1][2] if i + 1 < len(tr.skills) else None
            node = {"id": tid, "kind": "skill", "name": roles.get(short, short), "tag": f"/{short}",
                    "state": "done" if (nxt or not alive) else "run", "startedAt": t0,
                    "endedAt": nxt, "status": "", "children": []}
            skill_nodes[tid] = node
            order.append(node)

        def place(node, skill_id):
            (skill_nodes[skill_id]["children"] if skill_id in skill_nodes else loose).append(node)

        for aid, (sub, meta) in self.subs.items():
            if meta.get("toolUseId") not in tr.agent_parent_skill:
                continue
            idle = now - (sub.mtime or now)
            done = sub.handed_back or idle > AGENT_IDLE_DONE_SEC or not alive
            atype = meta.get("agentType") or ""
            desc = meta.get("description") or atype
            name = roles.get(atype, desc.lower()) if atype not in ("general-purpose", "") else desc.lower()
            node = {"id": aid, "kind": "agent", "name": name,
                    "tag": "" if atype in ("general-purpose", "", "fork") else atype,
                    "state": "done" if done else "run", "startedAt": sub.first_ts,
                    "endedAt": sub.last_ts if done else None, "tokens": sub.tokens,
                    "ctx": {"used": sub.ctx, "size": window_for(sub.model)}, "status": sub.status,
                    "events": list(sub.events), "task": sub.task or desc, "children": self._children(sub, roles, window_for, now, alive and not done)}
            place(node, tr.agent_parent_skill[meta.get("toolUseId")])

        if alive:
            for tid, inp, t0, skill_id in tr.running_shells(now):
                place({"id": tid, "kind": "shell", "name": trunc(inp.get("command"), 48), "tag": "",
                       "state": "run", "startedAt": t0, "status": trunc(inp.get("description"), 70),
                       "children": []}, skill_id)
        for n in order:
            if n["state"] == "run" and not n["children"]:
                n["status"] = tr.status
        return order + loose
