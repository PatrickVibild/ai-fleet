"""Runs and tickets: the plan an orchestrator submits, and its progress. Persisted as runs/<id>/run.json."""
import json
import re
import time
import uuid

from . import paths

# Ticket states
WAIT, RUNNING, TESTING, REVIEW, ATTN, READY, MERGING, CONFLICT, MERGED, KILLED = (
    "wait", "running", "testing", "review", "attn", "ready", "merging", "conflict", "merged", "killed")
HOLDS_SLOT = {RUNNING, TESTING, REVIEW}
LIVE_RUN = {"active", "paused"}
# Events the orchestrator acts on or reports; `fleet events` shows only these unless asked for all.
JUDGMENT = {"question", "verdict_needed", "attention", "held", "conflict", "run_done", "green_again",
            "verdict_timeout", "aborted", "run_started", "final_check", "command_missing"}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:24] or "run"


class Run:
    def __init__(self, d: dict):
        self.d = d
        self._last_judgment = None

    # -- construction ---------------------------------------------------------
    @classmethod
    def from_plan(cls, plan: dict, orchestrator=None):
        """plan = {repo, base?, name?, checks?: {test, quick, full}, tickets: [{id, title, body?, blockedBy?: []}]}"""
        repo = str(plan["repo"]).rstrip("/")
        name = plan.get("name") or repo.rsplit("/", 1)[-1]
        tickets = {}
        for t in plan["tickets"]:
            tid = str(t["id"]).lstrip("#")
            tickets[tid] = {"id": tid, "title": t.get("title", f"Ticket {tid}"), "body": t.get("body", ""),
                            "ref": t.get("ref", ""), "blockedBy": [str(b).lstrip("#") for b in t.get("blockedBy", [])],
                            "state": WAIT, "attempt": 0, "fixRound": 0, "session": None, "attn": None, "log": []}
        unknown = {b for t in tickets.values() for b in t["blockedBy"] if b not in tickets}
        if unknown:
            raise ValueError(f"tickets are blocked by unknown ids: {', '.join(sorted(unknown))}")
        cls._check_acyclic(tickets)
        rid = f"{slug(name)}-{uuid.uuid4().hex[:6]}"
        return cls({"id": rid, "name": name, "repo": repo, "base": plan.get("base") or "",
                    "checks": plan.get("checks") or {}, "status": "queued", "held": None,
                    "created": time.time(), "orchestrator": orchestrator, "tickets": tickets,
                    "helpers": [], "fixerRound": 0, "finalCheck": None})

    @staticmethod
    def _check_acyclic(tickets):
        seen, stack = set(), set()

        def visit(t):
            if t in stack:
                raise ValueError(f"tickets have a dependency cycle through #{t}")
            if t not in seen:
                stack.add(t)
                for b in tickets[t]["blockedBy"]:
                    visit(b)
                stack.discard(t)
                seen.add(t)

        for t in tickets:
            visit(t)

    @classmethod
    def load_all(cls):
        out = []
        for p in sorted(paths.RUNS.glob("*/run.json")):
            try:
                out.append(cls(json.loads(p.read_text())))
            except (OSError, json.JSONDecodeError):
                pass
        return out

    # -- persistence ----------------------------------------------------------
    @property
    def id(self):
        return self.d["id"]

    @property
    def dir(self):
        p = paths.RUNS / self.id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def save(self):
        tmp = self.dir / "run.json.tmp"
        tmp.write_text(json.dumps(self.d, indent=1))
        tmp.replace(self.dir / "run.json")

    def event(self, type_, **kw):
        """Append to the run's event log, which the orchestrator follows with `fleet events`."""
        ev = {"ts": time.time(), "run": self.id, "type": type_, **kw}
        with open(self.dir / "events.jsonl", "a") as f:
            f.write(json.dumps(ev) + "\n")
        if type_ in JUDGMENT:
            self._last_judgment = ev["ts"]
        return ev

    def last_judgment(self):
        """When the latest event the orchestrator should see was written (0 if none)."""
        if self._last_judgment is None:
            self._last_judgment = 0
            try:
                for line in (self.dir / "events.jsonl").read_text().splitlines():
                    ev = json.loads(line)
                    if ev.get("type") in JUDGMENT:
                        self._last_judgment = ev["ts"]
            except (OSError, json.JSONDecodeError):
                pass
        return self._last_judgment

    # -- graph ----------------------------------------------------------------
    @property
    def tickets(self):
        return self.d["tickets"]

    def ticket(self, tid):
        return self.tickets.get(str(tid).lstrip("#"))

    def ready(self):
        return [t for t in self.tickets.values()
                if t["state"] == WAIT and all(self.tickets[b]["state"] == MERGED for b in t["blockedBy"])]

    def slots_used(self):
        return sum(1 for t in self.tickets.values() if t["state"] in HOLDS_SLOT
                   or (t["state"] == ATTN and (t.get("attn") or {}).get("kind") == "question"))

    def blocked_by_problem(self, t):
        """Blockers (direct or not) that are stuck: killed or waiting on the user."""
        bad, todo, seen = [], list(t["blockedBy"]), set()
        while todo:
            b = todo.pop()
            if b in seen:
                continue
            seen.add(b)
            bt = self.tickets[b]
            if bt["state"] in (KILLED, ATTN):
                bad.append(b)
            todo.extend(bt["blockedBy"])
        return sorted(bad)

    def all_merged(self):
        return all(t["state"] == MERGED for t in self.tickets.values())

    def by_session(self, session_id):
        """Background sessions pick their own id; its first 8 characters are the short id `claude --bg` prints."""
        def match(s):
            return s and (s.get("sessionId") == session_id or (session_id or "").startswith(s.get("short") or "\0"))
        for t in self.tickets.values():
            if match(t.get("session")):
                return "implementor", t
        for h in self.d["helpers"]:
            if match(h):
                return h["kind"], h
        return None, None

    def sessions(self):
        """Every session record this run started (ticket sessions and helpers)."""
        return [t["session"] for t in self.tickets.values() if t.get("session")] + self.d["helpers"]
