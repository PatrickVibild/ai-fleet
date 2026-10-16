import json
import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()

from fleet import memory, paths  # noqa: E402
from fleet.runs import ATTN, KILLED, MERGED, RUNNING, WAIT, Run  # noqa: E402
from fleet.transcripts import SessionView, describe  # noqa: E402

PLAN = {"repo": "/tmp/x", "base": "main", "tickets": [
    {"id": "11", "title": "Money type"},
    {"id": "12", "title": "Currency table", "blockedBy": ["11"]},
    {"id": "13", "title": "Line items", "blockedBy": ["#11"]},
    {"id": "14", "title": "Refunds", "blockedBy": ["12", "13"]},
]}


class RunGraph(unittest.TestCase):
    def test_ready_follows_blockers(self):
        r = Run.from_plan(PLAN)
        self.assertEqual([t["id"] for t in r.ready()], ["11"])
        r.ticket("11")["state"] = MERGED
        self.assertEqual(sorted(t["id"] for t in r.ready()), ["12", "13"])
        r.ticket("12")["state"] = MERGED
        self.assertEqual(sorted(t["id"] for t in r.ready()), ["13"])

    def test_slots_count_running_and_open_questions(self):
        r = Run.from_plan(PLAN)
        r.ticket("11")["state"] = RUNNING
        r.ticket("12")["state"] = ATTN
        r.ticket("12")["attn"] = {"kind": "question"}
        r.ticket("13")["state"] = ATTN
        r.ticket("13")["attn"] = {"kind": "business_logic"}
        self.assertEqual(r.slots_used(), 2)

    def test_blocked_by_problem_is_transitive(self):
        r = Run.from_plan(PLAN)
        r.ticket("11")["state"] = KILLED
        self.assertEqual(r.blocked_by_problem(r.ticket("14")), ["11"])

    def test_rejects_cycles_and_unknown_blockers(self):
        with self.assertRaisesRegex(ValueError, "cycle"):
            Run.from_plan({"repo": "/x", "tickets": [{"id": 1, "blockedBy": [2]}, {"id": 2, "blockedBy": [1]}]})
        with self.assertRaisesRegex(ValueError, "unknown"):
            Run.from_plan({"repo": "/x", "tickets": [{"id": 1, "blockedBy": [9]}]})

    def test_round_trips_through_disk(self):
        r = Run.from_plan(PLAN)
        r.save()
        again = {x.id: x for x in Run.load_all()}[r.id]
        self.assertEqual(again.ticket("14")["blockedBy"], ["12", "13"])
        self.assertEqual(again.ticket("14")["state"], WAIT)


def entry(kind, ts, content, **kw):
    return {"type": kind, "timestamp": ts, "message": {"content": content, **kw}}


class Transcripts(unittest.TestCase):
    def setUp(self):
        self.projects = Path(tempfile.mkdtemp())
        paths.CLAUDE_PROJECTS = self.projects
        self.sid = "abc-123"
        proj = self.projects / "-tmp-repo"
        proj.mkdir()
        now = time.time()
        iso = lambda dt: time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now + dt)) + ".000Z"
        main = [
            entry("user", iso(-60), "<command-name>/mattpocock-skills:implement</command-name>"),
            entry("assistant", iso(-50), [{"type": "tool_use", "id": "sk1", "name": "Skill", "input": {"skill": "mattpocock-skills:tdd"}}],
                  id="m1", model="claude-opus-5-5", usage={"input_tokens": 10, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 5000, "output_tokens": 50}),
            entry("assistant", iso(-40), [{"type": "tool_use", "id": "ag1", "name": "Agent", "input": {"description": "Write failing tests"}}],
                  id="m2", model="claude-opus-5-5", usage={"input_tokens": 5, "cache_creation_input_tokens": 200, "cache_read_input_tokens": 6000, "output_tokens": 20}),
            entry("assistant", iso(-30), [{"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": "pnpm vitest run refunds", "description": "Run refund tests"}}],
                  id="m3", model="claude-opus-5-5", usage={"input_tokens": 5, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 6200, "output_tokens": 20}),
            entry("assistant", iso(-30), [{"type": "text", "text": "same message, second block"}],
                  id="m3", model="claude-opus-5-5", usage={"input_tokens": 5, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 6200, "output_tokens": 20}),
        ]
        (proj / f"{self.sid}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in main))
        sub = proj / self.sid / "subagents"
        sub.mkdir(parents=True)
        (sub / "agent-a1.meta.json").write_text(json.dumps({"agentType": "general-purpose", "description": "Write failing tests", "toolUseId": "ag1"}))
        (sub / "agent-a1.jsonl").write_text(json.dumps(entry("assistant", iso(-35), [{"type": "tool_use", "id": "e1", "name": "Edit", "input": {"file_path": "/tmp/repo/src/refund.test.ts"}}],
                                                             id="s1", model="claude-haiku-5-5", usage={"input_tokens": 3, "cache_creation_input_tokens": 900, "cache_read_input_tokens": 0, "output_tokens": 9})) + "\n")

    def test_usage_is_deduplicated_and_context_is_latest(self):
        v = SessionView(self.sid, "/tmp/repo")
        v.poll()
        self.assertEqual(v.main.tokens, 1060 + 225 + 125)
        self.assertEqual(v.main.ctx, 5 + 100 + 6200)
        self.assertEqual(v.main.slash, "/mattpocock-skills:implement")
        self.assertEqual(v.main.status, "Said: same message, second block")

    def test_tree_nests_agents_under_skills_with_role_names(self):
        v = SessionView(self.sid, "/tmp/repo")
        v.poll()
        kids = v.tree({"tdd": "tester"}, lambda m: 1_000_000)
        self.assertEqual([k["name"] for k in kids], ["tester"])
        tester = kids[0]
        self.assertEqual(tester["tag"], "/tdd")
        names = [c["name"] for c in tester["children"]]
        self.assertIn("write failing tests", names)
        self.assertIn("pnpm vitest run refunds", names)   # open Bash call, running > 3s
        agent = next(c for c in tester["children"] if c["kind"] == "agent")
        self.assertEqual(agent["status"], "Editing src/refund.test.ts")
        self.assertEqual(agent["tokens"], 912)

    def test_incremental_read_picks_up_appended_lines(self):
        v = SessionView(self.sid, "/tmp/repo")
        v.poll()
        with open(v.main.path, "a") as f:
            f.write(json.dumps(entry("user", "2026-01-01T00:00:00.000Z", [{"type": "tool_result", "tool_use_id": "b1", "content": "ok"}])) + "\n")
        v.poll()
        kids = v.tree({"tdd": "tester"}, lambda m: 1)
        self.assertNotIn("pnpm vitest run refunds", [c["name"] for c in kids[0]["children"]])

    def test_usage_limit_error_marks_the_session_until_a_real_reply(self):
        v = SessionView(self.sid, "/tmp/repo")
        v.poll()
        self.assertIsNone(v.main.limited)
        limit = {**entry("assistant", "2026-01-01T00:00:00.000Z", [{"type": "text", "text": "You've hit your limit · resets 3pm"}],
                         model="<synthetic>"), "isApiErrorMessage": True}
        with open(v.main.path, "a") as f:
            f.write(json.dumps(limit) + "\n")
        v.poll()
        self.assertEqual(v.main.limited[1], "You've hit your limit · resets 3pm")
        self.assertEqual(v.main.model, "claude-opus-5-5")
        with open(v.main.path, "a") as f:
            f.write(json.dumps(entry("assistant", "2026-01-01T01:00:00.000Z", [{"type": "text", "text": "carrying on"}], id="m9")) + "\n")
        v.poll()
        self.assertIsNone(v.main.limited)

    def test_describe(self):
        self.assertEqual(describe("Edit", {"file_path": "/r/src/a.ts"}, "/r"), "Editing src/a.ts")
        self.assertEqual(describe("Skill", {"skill": "mattpocock-skills:code-review"}), "Using /code-review")


class ClaudeMd(unittest.TestCase):
    def test_counts_user_file_and_files_up_to_the_git_root_not_beyond(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(setattr, paths, "HOME", paths.HOME)
        paths.HOME = root / "home"
        (paths.HOME / ".claude").mkdir(parents=True)
        (paths.HOME / ".claude/CLAUDE.md").write_text("u" * 400)
        (root / "CLAUDE.md").write_text("above the repo" * 100)
        repo = root / "repo"
        wt = repo / ".claude/worktrees/t1"
        (wt / "pkg").mkdir(parents=True)
        (repo / ".git").mkdir()
        (repo / "CLAUDE.md").write_text("r" * 4000)
        (wt / ".git").write_text("gitdir: ../../../.git/worktrees/t1")
        (wt / "CLAUDE.md").write_text("w" * 4000)
        (wt / "CLAUDE.local.md").write_text("l" * 40)
        md = memory.claude_md(wt / "pkg")
        self.assertEqual([f["tokens"] for f in md["files"]], [100, 1000, 10])
        self.assertEqual(md["files"][0]["path"], "~/.claude/CLAUDE.md")
        self.assertEqual(md["tokens"], 1110)
        self.assertEqual(memory.claude_md(None)["tokens"], 100)


if __name__ == "__main__":
    unittest.main()
