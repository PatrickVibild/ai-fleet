import json
import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()

from fleet import config, memory, paths, skills, testcounts  # noqa: E402
from fleet.daemon import Fleet  # noqa: E402
from fleet.runs import ATTN, CONFLICT, KILLED, MERGED, RUNNING, WAIT, Run  # noqa: E402
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


class TestCounts(unittest.TestCase):
    def check(self, out, passed, failed, skipped, total):
        self.assertEqual(testcounts.parse(out), {"passed": passed, "failed": failed, "skipped": skipped, "total": total})

    def test_reads_each_runners_summary(self):
        self.check("collected 43\n..F\n===== 1 failed, 40 passed, 2 skipped in 1.20s =====\n", 40, 1, 2, 43)
        self.check("40 passed, 1 error in 0.50s\n", 40, 1, 0, 41)
        self.check("....\n------\nRan 41 tests in 4.012s\n\nOK (skipped=2)\n", 39, 0, 2, 41)
        self.check("Ran 10 tests in 0.1s\n\nFAILED (failures=2, errors=1)\n", 7, 3, 0, 10)
        self.check("Test Suites: 1 failed, 3 passed, 4 total\nTests:       1 failed, 2 skipped, 40 passed, 43 total\n", 40, 1, 2, 43)
        self.check(" Test Files  1 failed | 3 passed (4)\n      Tests  1 failed | 40 passed (41)\n", 40, 1, 0, 41)
        self.check("\x1b[32m  40 passed\x1b[39m (1.2m)\n  1 failed\n  3 flaky\n", 43, 1, 0, 44)
        self.check("  40 passing (2s)\n  2 pending\n  1 failing\n", 40, 1, 2, 43)
        self.check("test result: ok. 5 passed; 0 failed; 1 ignored\ntest result: FAILED. 3 passed; 1 failed; 0 ignored\n", 8, 1, 1, 10)
        self.check("=== RUN TestA\n--- PASS: TestA (0.00s)\n--- FAIL: TestB (0.01s)\n", 1, 1, 0, 2)

    def test_chained_runs_add_up(self):
        self.check("10 passed in 1.0s\n...\n===== 1 failed, 4 passed in 9.0s =====\n", 14, 1, 0, 15)

    def test_counts_tests_as_the_output_streams_in(self):
        p = testcounts.Progress()
        p.feed(b"============ test session starts ============\ncollected 12 items\n\n")
        p.feed(b"tests/test_a.py ..F.")
        self.assertEqual(p.snapshot(), {"passed": 3, "failed": 1, "skipped": 0, "total": 4,
                                        "expected": 12, "estimated": False})
        p.feed(b"s.   [ 50%]\ntests/test_b.py ..")
        self.assertEqual(p.snapshot()["total"], 8)
        p.feed(b"\x1b[32m....\x1b[0m [100%]\n=== 1 failed, 10 passed, 1 skipped in 2.0s ===\n"
               b"collected 3 items\nsmoke.py::test_x PASSED [ 33%]\n")
        self.assertEqual(p.snapshot(), {"passed": 11, "failed": 1, "skipped": 1, "total": 13,
                                        "expected": 15, "estimated": False})

    def test_pytest_q_expected_total_comes_from_its_percentages(self):
        p = testcounts.Progress()
        p.feed("." * 80 + " [ 20%]\n")
        self.assertEqual((p.snapshot()["expected"], p.snapshot()["estimated"]), (400, True))
        p.feed("." * 320 + " [100%]\n400 passed in 9.0s\n" + "s" * 10 + " [ 50%]\n")
        self.assertEqual(p.snapshot()["expected"], 420)   # the first run's 400, then half of a second run

    def test_a_quiet_run_then_one_that_states_its_count_add_up(self):
        # what the Aegir full check prints: pytest -q (no count, only percentages), then the smoke test
        p = testcounts.Progress()
        p.feed("." * 4848 + " [100%]\n4848 passed in 60.0s\ncollected 51 items\n\ntests/test_render_smoke.py ss")
        self.assertEqual(p.snapshot()["total"], 4850)
        self.assertEqual((p.snapshot()["expected"], p.snapshot()["estimated"]), (4899, False))

    def test_unittest_dots_count_before_their_line_ends(self):
        p = testcounts.Progress()
        p.feed("..s.F")
        self.assertEqual(p.snapshot(), {"passed": 3, "failed": 1, "skipped": 1, "total": 5,
                                        "expected": 0, "estimated": False})

    def test_only_test_commands_count(self):
        self.assertTrue(testcounts.is_test_command("/x/.venv/bin/python -m pytest -q"))
        self.assertTrue(testcounts.is_test_command("pnpm run e2e --headed"))
        self.assertFalse(testcounts.is_test_command("grep '\"ticket\": \"34\"' events.jsonl"))

    def test_output_that_isnt_a_test_run(self):
        self.assertIsNone(testcounts.parse("src/a.py\nsrc/b.py\n"))
        self.assertIsNone(testcounts.parse(""))

    def test_an_agents_latest_test_command_is_counted(self):
        projects = Path(tempfile.mkdtemp())
        self.addCleanup(setattr, paths, "CLAUDE_PROJECTS", paths.CLAUDE_PROJECTS)
        paths.CLAUDE_PROJECTS = projects
        (projects / "-r").mkdir()
        lines = [entry("assistant", "2026-10-16T10:00:00.000Z",
                       [{"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": "pytest -q"}}], id="a1"),
                 entry("user", "2026-10-16T10:00:05.000Z",
                       [{"type": "tool_result", "tool_use_id": "b1", "content": "2 failed, 9 passed in 0.3s"}])]
        (projects / "-r" / "s1.jsonl").write_text("".join(json.dumps(e) + "\n" for e in lines))
        v = SessionView("s1")
        v.poll()
        self.assertEqual({k: v.main.tests[k] for k in ("passed", "failed", "total", "cmd")},
                         {"passed": 9, "failed": 2, "total": 11, "cmd": "pytest -q"})


class Skills(unittest.TestCase):
    def setUp(self):
        root = Path(tempfile.mkdtemp())
        for attr in ("HOME", "CLAUDE_PLUGINS"):
            self.addCleanup(setattr, paths, attr, getattr(paths, attr))
        paths.HOME = root / "home"
        paths.CLAUDE_PLUGINS = paths.HOME / ".claude/plugins"
        install = root / "cache/mp/1.3.1"
        (install / "skills/engineering/implement").mkdir(parents=True)
        (install / "skills/engineering/implement/SKILL.md").write_text("---\nname: implement\n---\n")
        (install / ".claude-plugin").mkdir()
        (install / ".claude-plugin/plugin.json").write_text(json.dumps({"skills": ["./skills/engineering/implement"]}))
        paths.CLAUDE_PLUGINS.mkdir(parents=True)
        (paths.CLAUDE_PLUGINS / "installed_plugins.json").write_text(json.dumps(
            {"plugins": {"mp@official": [{"installPath": str(install), "version": "1.3.1"}]}}))
        (paths.HOME / ".claude/skills/mine").mkdir(parents=True)
        (paths.HOME / ".claude/skills/mine/SKILL.md").write_text("x")

    def test_finds_plugin_skills_listed_in_the_manifest(self):
        self.assertIsNone(skills.missing("/mp:implement"))
        self.assertIsNone(skills.missing(""))

    def test_names_what_is_missing(self):
        self.assertEqual(skills.missing("/mp:resolving-merge-conflicts"),
                         "`/mp:resolving-merge-conflicts`: mp 1.3.1 has no skill or command named resolving-merge-conflicts")
        self.assertIn("plugin isn't installed", skills.missing("/other:implement"))

    def test_plain_names_look_in_user_and_repo_skills(self):
        self.assertIsNone(skills.missing("/mine"))
        self.assertIsNone(skills.missing("/implement"))
        self.assertIn("isn't an installed", skills.missing("/nope"))


class Stalls(unittest.TestCase):
    """Fleet sessions that start but never do anything raise attention instead of sitting there."""

    def setUp(self):
        self.projects = Path(tempfile.mkdtemp())
        self.addCleanup(setattr, paths, "CLAUDE_PROJECTS", paths.CLAUDE_PROJECTS)
        paths.CLAUDE_PROJECTS = self.projects
        (self.projects / "-repo").mkdir()
        self.fleet = Fleet.__new__(Fleet)
        self.fleet.cfg = {**config.DEFAULTS, "stall_sec": 300}
        self.fleet.views, self.fleet.agents, self.fleet.runs, self.fleet.checks = {}, {}, {}, {}
        self.fleet.usage = lambda: {"limited": False}
        self.run = Run.from_plan({"repo": "/tmp/x", "base": "main", "tickets": [{"id": "1", "title": "A"}]})
        self.run.d["status"] = "active"
        self.fleet.runs[self.run.id] = self.run

    def session(self, sid, started_ago, lines):
        (self.projects / "-repo" / f"{sid}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in lines))
        self.fleet.agents[sid] = {"sessionId": sid, "pid": 123}
        v = self.fleet.views[sid] = SessionView(sid)
        v.poll()
        return {"sessionId": sid, "short": sid[:8], "started": time.time() - started_ago}

    def iso(self, dt):
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() + dt)) + ".000Z"

    def test_unknown_slash_command_fails_the_merger_at_once(self):
        t = self.run.ticket("1")
        t["state"] = CONFLICT
        h = self.session("m1", 10, [{"type": "system", "subtype": "informational", "timestamp": self.iso(-9),
                                     "content": "Unknown command: /mp:resolving-merge-conflicts"}])
        self.run.d["helpers"].append({"kind": "merger", "ticket": "1", "state": "run", **h})
        self.fleet.check_stalls()
        self.assertEqual(t["state"], ATTN)
        self.assertEqual(t["attn"]["kind"], "merge_failed")
        self.assertIn("Unknown command", t["attn"]["msg"])
        self.fleet.check_stalls()   # reported once
        events = (self.run.dir / "events.jsonl").read_text().splitlines()
        self.assertEqual(sum('"attention"' in e for e in events), 1)

    def test_implementor_without_a_reply_after_stall_sec(self):
        t = self.run.ticket("1")
        t["state"] = RUNNING
        t["session"] = self.session("i1", 400, [entry("user", self.iso(-399), "do the ticket")])
        self.fleet.check_stalls()
        self.assertEqual(t["state"], ATTN)
        self.assertEqual(t["attn"]["kind"], "stalled")

    def test_quiet_but_working_or_young_sessions_are_left_alone(self):
        t = self.run.ticket("1")
        t["state"] = RUNNING
        t["session"] = self.session("i2", 400, [entry("user", self.iso(-399), "do it"),
                                                entry("assistant", self.iso(-390), [{"type": "text", "text": "on it"}], id="a")])
        self.fleet.check_stalls()
        self.assertEqual(t["state"], RUNNING)
        t["session"] = self.session("i3", 100, [entry("user", self.iso(-99), "do it")])
        self.fleet.check_stalls()
        self.assertEqual(t["state"], RUNNING)


    def test_a_live_run_whose_orchestrator_ended_is_not_shown_as_done(self):
        self.fleet.questions, self.fleet.sudo, self.fleet.summaries, self.fleet.windows = {}, {}, {}, {}
        self.run.d["orchestrator"] = "o1"
        self.run.ticket("1")["state"] = MERGED
        self.run.d["held"] = {"kind": "hold", "reason": "The full suite fails on `main`. A fixer is on it."}
        self.session("o1", 900, [entry("assistant", self.iso(-800), [{"type": "text", "text": "stopping"}], id="o")])
        self.fleet.agents["o1"] = {"sessionId": "o1"}   # ended: no pid
        h = self.session("f1", 60, [entry("assistant", self.iso(-50), [{"type": "text", "text": "fixing"}], id="f")])
        self.run.d["helpers"].append({"kind": "fixer", "state": "run", "after": "the last ticket", **h})
        tree = next(r for r in self.fleet.snapshot()["runs"] if r["id"] == self.run.id)["tree"]
        self.assertEqual(tree["state"], "run")
        self.assertIn("Orchestrator stopped", tree["status"])
        self.assertIn("fixer is on it", tree["status"])

    def test_a_finished_run_shows_its_idle_orchestrator_as_done_with_git_ticks(self):
        self.fleet.questions, self.fleet.sudo, self.fleet.summaries, self.fleet.windows = {}, {}, {}, {}
        self.fleet.gitinfo, self.fleet.pushes = {"/tmp/x": {"merged": True, "pushed": False}}, {}
        self.fleet.listening = set()
        self.run.d["orchestrator"], self.run.d["status"] = "o1", "done"
        self.run.ticket("1")["state"] = MERGED
        self.session("o1", 900, [entry("assistant", self.iso(-800), [{"type": "text", "text": "all merged"}], id="o")])
        self.fleet.agents["o1"].update(status="idle")
        out = next(r for r in self.fleet.snapshot()["runs"] if r["id"] == self.run.id)
        self.assertEqual(out["tree"]["state"], "done")
        self.assertEqual(out["git"], {"merged": True, "pushed": False, "push": None})

    def test_closing_a_finished_run_takes_it_off_the_panel(self):
        import asyncio
        from fleet import claude
        self.fleet.questions, self.fleet.sudo, self.fleet.summaries, self.fleet.windows = {}, {}, {}, {}
        self.fleet.gitinfo, self.fleet.pushes, self.fleet.listening = {}, {}, set()
        with self.assertRaisesRegex(ValueError, "abort it first"):
            asyncio.run(self.fleet.ctl({"action": "close", "run": self.run.id}))
        self.run.d["status"], self.run.d["orchestrator"] = "done", "o1"
        self.fleet.agents["o1"] = {"sessionId": "o1", "pid": 9, "id": "o1"}
        stopped = []

        async def stop(short):
            stopped.append(short)
        self.addCleanup(setattr, claude, "stop", claude.stop)
        claude.stop = stop
        asyncio.run(self.fleet.ctl({"action": "close", "run": self.run.id}))
        self.assertEqual(stopped, ["o1"])
        self.assertNotIn(self.run.id, [r["id"] for r in self.fleet.snapshot()["runs"]])
        self.assertNotIn("/tmp/x", self.fleet.git_targets())

    def test_closing_a_run_whose_orchestrator_is_a_terminal_asks_it_to_exit(self):
        import asyncio
        import signal
        from unittest import mock
        self.fleet.questions, self.fleet.sudo, self.fleet.summaries, self.fleet.windows = {}, {}, {}, {}
        self.fleet.gitinfo, self.fleet.pushes, self.fleet.listening = {}, {}, set()
        self.run.d["status"], self.run.d["orchestrator"] = "done", "o1"
        self.fleet.agents["o1"] = {"sessionId": "o1", "pid": 9, "kind": "interactive"}   # no `id` to `claude stop`
        with mock.patch("os.kill") as kill:
            asyncio.run(self.fleet.ctl({"action": "close", "run": self.run.id}))
        kill.assert_called_once_with(9, signal.SIGTERM)
        self.assertTrue(self.run.d["closed"])


    def test_a_running_check_shows_under_the_orchestrator_beside_its_ticket(self):
        import asyncio
        self.fleet.questions, self.fleet.sudo, self.fleet.summaries, self.fleet.windows = {}, {}, {}, {}
        self.fleet.listening = set()
        t = self.run.ticket("1")
        t["state"] = RUNNING
        t["session"] = self.session("i4", 30, [entry("user", self.iso(-29), "do it")])

        def lanes():
            return next(r for r in self.fleet.snapshot()["runs"] if r["id"] == self.run.id)["tree"]["children"]

        async def go():
            task = asyncio.create_task(self.fleet.run_check(self.run, "tests", "#1 A", "sleep 0.3", "/tmp", ticket="1"))
            await asyncio.sleep(0.1)
            seen = lanes()
            await task
            failed = await self.fleet.run_check(self.run, "full suite", "main", "echo 'Ran 5 tests in 0.1s'; echo; echo 'FAILED (failures=1)'; exit 3", "/tmp")
            return seen, failed
        seen, failed = asyncio.run(go())
        self.assertEqual([n["kind"] for n in seen], ["implementor", "check"])
        self.assertEqual((seen[1]["name"], seen[1]["state"], seen[1]["note"]), ("daemon · tests", "run", "running"))
        self.assertEqual(failed[0], 3)
        done = {n["name"]: n for n in lanes() if n["kind"] == "check"}
        self.assertEqual((done["daemon · tests"]["state"], done["daemon · tests"]["note"]), ("done", "green"))
        self.assertEqual(done["daemon · full suite"]["note"], "red")
        self.assertIn("exit 3", done["daemon · full suite"]["status"])
        self.assertEqual(done["daemon · full suite"]["tests"], {"passed": 4, "failed": 1, "skipped": 0, "total": 5})


class WakeOrchestrator(Stalls):
    """An orchestrator that stopped following its run is resumed when an event it should see arrives."""

    def setUp(self):
        super().setUp()
        import asyncio
        from fleet import claude
        self.asyncio = asyncio
        self.fleet.listening, self.fleet.heard = set(), {}
        self.spawned, self.stopped = [], []

        async def spawn_bg(**kw):
            self.spawned.append(kw)
            return "newshort"

        async def stop(short):
            self.stopped.append(short)
        for name, fn in (("spawn_bg", spawn_bg), ("stop", stop)):
            self.addCleanup(setattr, claude, name, getattr(claude, name))
            setattr(claude, name, fn)
        from fleet import daemon
        self.addCleanup(setattr, daemon, "notify", daemon.notify)
        daemon.notify = lambda *a, **kw: None
        self.run.d["orchestrator"] = "o1"
        self.session("o1", 900, [entry("assistant", self.iso(-800), [{"type": "text", "text": "stopping"}], id="o")])
        self.fleet.agents["o1"] = {"sessionId": "o1", "pid": 9, "id": "o1", "kind": "background", "status": "idle"}

    def check(self, followers):
        self.fleet.listeners = lambda: set(followers)
        self.asyncio.run(self.fleet.check_orchestrators())

    def test_wakes_an_idle_orchestrator_that_missed_an_event(self):
        self.run.event("held", reason="red")
        self.run._last_judgment -= 60
        self.check([])
        self.assertEqual(self.stopped, ["o1"])
        self.assertEqual(self.spawned[0]["resume"], "o1")
        self.assertIn(f"fleet events {self.run.id} --since", self.spawned[0]["prompt"])
        self.check([])   # not again right away
        self.assertEqual(len(self.spawned), 1)

    def test_leaves_a_following_orchestrator_alone(self):
        self.run.event("held", reason="red")
        self.run._last_judgment -= 60
        self.check([self.run.id[:10]])
        self.assertEqual(self.spawned, [])
        self.assertIn(self.run.id, self.fleet.listening)

    def test_never_takes_over_your_terminal(self):
        self.fleet.agents["o1"]["kind"] = "interactive"
        self.run.event("held", reason="red")
        self.run._last_judgment -= 60
        self.check([])
        self.assertEqual((self.spawned, self.stopped), ([], []))


class StopFinishedOrchestrator(WakeOrchestrator):
    """A done run's orchestrator is stopped once the work is merged and pushed; there's nothing left for it."""

    def finish(self, pushed):
        self.run.d["status"] = "done"
        self.fleet.gitinfo = {self.run.d["repo"]: {"merged": True, "pushed": pushed}}
        self.asyncio.run(self.fleet.stop_finished_orchestrators())

    def test_stopped_once_pushed(self):
        self.finish(pushed=False)
        self.assertEqual(self.stopped, [])
        self.finish(pushed=True)
        self.assertEqual(self.stopped, ["o1"])
        self.finish(pushed=True)   # resumed by you afterwards: stays
        self.assertEqual(self.stopped, ["o1"])

    def test_never_stops_your_terminal(self):
        self.fleet.agents["o1"]["kind"] = "interactive"
        self.finish(pushed=True)
        self.assertEqual(self.stopped, [])


class InactiveSessions(unittest.TestCase):
    """Your idle sessions say how long they've been inactive, and whether a terminal is showing them."""

    def setUp(self):
        self.projects = Path(tempfile.mkdtemp())
        self.addCleanup(setattr, paths, "CLAUDE_PROJECTS", paths.CLAUDE_PROJECTS)
        paths.CLAUDE_PROJECTS = self.projects
        (self.projects / "-repo").mkdir()
        self.fleet = Fleet.__new__(Fleet)
        self.fleet.views, self.fleet.runs, self.fleet.attached = {}, {}, set()
        run = Run.from_plan({"repo": "/tmp/x", "base": "main", "tickets": [{"id": "1", "title": "A"}]})
        run.d["orchestrator"] = "o1"
        self.fleet.runs[run.id] = run
        idle = {"kind": "background", "status": "idle", "startedAt": (time.time() - 7200) * 1000}
        self.fleet.agents = {"o1": {"sessionId": "o1", "pid": 9, "id": "o1", "cwd": "/tmp/x", **idle},
                             "u1": {"sessionId": "u1", "pid": 7, "id": "u1", "cwd": "/tmp/u", **idle}}
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 7000)) + ".000Z"
        (self.projects / "-repo" / "u1.jsonl").write_text(
            json.dumps(entry("assistant", stamp, [{"type": "text", "text": "done"}], id="u")) + "\n")
        v = self.fleet.views["u1"] = SessionView("u1")
        v.poll()
        self.u1 = self.fleet.agents["u1"]

    def test_counts_from_the_last_transcript_line(self):
        self.assertAlmostEqual(self.fleet.idle_for("u1", self.u1), 7000, delta=60)

    def test_not_inactive_while_working_or_waiting_on_you(self):
        for status in ("busy", "waiting"):
            self.u1["status"] = status
            self.assertIsNone(self.fleet.idle_for("u1", self.u1))

    def test_detached_only_for_a_background_session_no_terminal_shows(self):
        self.assertTrue(self.fleet.detached(self.u1))
        self.fleet.attached = {"u1"}
        self.assertFalse(self.fleet.detached(self.u1))
        self.u1["kind"] = "interactive"
        self.fleet.attached = set()
        self.assertFalse(self.fleet.detached(self.u1))

    def test_a_runs_sessions_are_not_yours(self):
        self.assertEqual(list(self.fleet.my_sessions()), ["u1"])


class LiveUsage(unittest.TestCase):
    def test_parses_the_usage_endpoint(self):
        from fleet import account
        got = account.parse({"five_hour": {"utilization": 12.4, "resets_at": "2026-10-16T16:00:00+00:00"},
                             "seven_day": {"utilization": None}})
        self.assertEqual(got, {"five_hour": {"used": 12, "resetsAt": 1792166400.0}})

    def test_fresh_live_numbers_beat_a_stale_statusline(self):
        st = Path(tempfile.mkdtemp())
        self.addCleanup(setattr, paths, "STATUSLINE", paths.STATUSLINE)
        paths.STATUSLINE = st
        later = time.time() + 3600
        (st / "old.json").write_text(json.dumps({"rate_limits": {"five_hour": {"used_percentage": 96, "resets_at": later}}}))
        f = Fleet.__new__(Fleet)
        f.views, f.agents = {}, {}
        f.live_usage = None
        self.assertEqual(f.usage()["five_hour"]["used"], 96)
        f.live_usage, f._usage_at = (time.time(), {"five_hour": {"used": 0, "resetsAt": later}}), 0
        self.assertEqual(f.usage()["five_hour"]["used"], 0)
        # a session that hit the old limit doesn't keep the account limited once Anthropic says it isn't
        v = SessionView("x")
        v.main = type("T", (), {"limited": (0, "You've hit your limit")})()
        f.views, f._usage_at = {"x": v}, 0
        self.assertFalse(f.usage()["limited"])
        f.views = {}
        f.live_usage, f._usage_at = (time.time() - 3600, {"five_hour": {"used": 0, "resetsAt": later}}), 0
        self.assertEqual(f.usage()["five_hour"]["used"], 96)   # too old: back to the statusline


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


class GitRepo(unittest.TestCase):
    """A throwaway repo on `main` with one commit, and helpers to drive it."""

    def setUp(self):
        import asyncio
        import subprocess
        from fleet import git
        self.asyncio, self.subprocess, self.git = asyncio, subprocess, git
        from unittest import mock
        env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
                                           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        env.start()
        self.addCleanup(env.stop)
        self.root = Path(tempfile.mkdtemp())
        self.repo = self.root / "repo"
        self.sh("git", "init", "-q", "-b", "main", str(self.repo))
        self.commit("one")

    def sh(self, *args, cwd=None):
        return self.subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, msg, cwd=None):
        cwd = cwd or self.repo
        (Path(cwd) / f"{msg}.txt").write_text(msg)
        self.sh("git", "add", ".", cwd=cwd)
        self.sh("git", "commit", "-q", "-m", msg, cwd=cwd)

    def remote(self, name="origin"):
        bare = self.root / f"{name}.git"
        self.sh("git", "init", "-q", "--bare", "-b", "main", str(bare))
        self.sh("git", "remote", "add", name, str(bare), cwd=self.repo)
        return bare

    def status(self, path=None, base=None):
        return self.asyncio.run(self.git.status(path or self.repo, base))

    def push(self, path=None):
        return self.asyncio.run(self.git.push(path or self.repo, self.status(path)))


class MergedAndPushed(GitRepo):
    """The panel's two ticks for finished work, and the push behind the second one, against real git repos."""

    def test_merged_work_pushes_the_base_branch_and_ticks_both(self):
        self.remote()
        st = self.status()
        self.assertEqual((st["merged"], st["pushed"], st["target"], st["remote"], st["unpushed"]),
                         (True, False, "main", "origin", 1))
        ok, kind, msg, _ = self.push()
        self.assertTrue(ok, msg)
        st = self.status()
        self.assertTrue(st["pushed"])
        self.commit("two")   # main has an upstream now: a plain push, no -u
        self.assertEqual(self.status()["unpushed"], 1)
        self.assertTrue(self.push()[0])

    def test_unmerged_branch_pushes_itself(self):
        self.remote()
        wt = self.root / "wt"
        self.sh("git", "worktree", "add", "-q", "-b", "feature", str(wt), cwd=self.repo)
        self.commit("feat", cwd=wt)
        st = self.status(wt)
        self.assertEqual((st["branch"], st["base"], st["merged"], st["target"]), ("feature", "main", False, "feature"))
        self.assertTrue(self.push(wt)[0])
        self.assertIn("origin/feature", self.sh("git", "branch", "-r", cwd=self.repo))
        self.sh("git", "merge", "-q", "feature", cwd=self.repo)
        st = self.status(wt)
        self.assertEqual((st["merged"], st["target"], st["pushed"]), (True, "main", True))

    def test_uncommitted_changes_are_counted(self):
        (self.repo / "one.txt").write_text("changed")
        self.assertEqual(self.status()["dirty"], 1)

    def test_no_remote_says_how_to_add_one(self):
        st = self.status()
        self.assertEqual((st["remote"], st["pushed"]), ("", False))
        ok, kind, msg, _ = self.push()
        self.assertEqual((ok, kind), (False, "no_remote"))
        self.assertIn("git remote add origin", msg)

    def test_missing_remote_repository(self):
        self.sh("git", "remote", "add", "origin", str(self.root / "gone.git"), cwd=self.repo)
        ok, kind, msg, _ = self.push()
        self.assertEqual((ok, kind), (False, "not_found"))
        self.assertIn("doesn't exist", msg)

    def test_remote_ahead_is_rejected_with_a_pull_hint(self):
        bare = self.remote()
        self.assertTrue(self.push()[0])
        other = self.root / "other"
        self.sh("git", "clone", "-q", str(bare), str(other))
        self.commit("theirs", cwd=other)
        self.sh("git", "push", "-q", "origin", "main", cwd=other)
        self.commit("mine")
        ok, kind, msg, _ = self.push()
        self.assertEqual((ok, kind), (False, "behind"))
        self.assertIn("Pull", msg)

    def test_explains_what_hosts_print(self):
        cases = {
            "ERROR: Repository not found.\nfatal: Could not read from remote repository.": "not_found",
            "git@github.com: Permission denied (publickey).\nfatal: Could not read from remote repository.": "no_access",
            "remote: Permission to me/x.git denied to someone.\nfatal: unable to access 'https://github.com/me/x.git/': "
            "The requested URL returned error: 403": "no_access",
            "fatal: could not read Username for 'https://github.com': terminal prompts disabled": "no_access",
            "Host key verification failed.": "host_key",
            "remote: error: GH006: Protected branch update failed for refs/heads/main.": "protected",
            "! [rejected]        main -> main (fetch first)": "behind",
            "ssh: Could not resolve host: github.com": "network",
            "fatal: something new": "other",
        }
        for out, kind in cases.items():
            self.assertEqual(self.git.explain_push(out, "origin", "git@github.com:me/x.git", "main")[0], kind, out)
        self.assertEqual(self.git.explain_push("fatal: something new")[1], "git push failed: fatal: something new")

    def test_daemon_push_keeps_the_reason_on_the_row(self):
        f = Fleet.__new__(Fleet)
        f.runs, f.gitinfo, f.pushes = {}, {}, {}
        f.agents = {"s1": {"sessionId": "s1", "pid": 1, "cwd": str(self.repo)}}
        with self.assertRaisesRegex(ValueError, "no remote"):
            self.asyncio.run(f.push(str(self.repo)))
        self.assertEqual(f.git_view(str(self.repo))["push"]["kind"], "no_remote")
        self.remote()
        self.assertIn("Pushed", self.asyncio.run(f.push(str(self.repo)))["msg"])
        self.assertTrue(f.git_view(str(self.repo))["pushed"])
        with self.assertRaisesRegex(ValueError, "isn't a finished run"):
            self.asyncio.run(f.push(str(self.root)))


class Worktrees(GitRepo):
    """Tickets start from the local base branch as it is when they spawn, never from origin."""

    def test_cut_from_the_local_base_with_unpushed_merges(self):
        self.remote()
        self.sh("git", "push", "-q", "-u", "origin", "main", cwd=self.repo)
        self.commit("blocker-merged")   # local main is now ahead of origin/main
        wt = self.asyncio.run(self.git.add_worktree(self.repo, "fleet-x-2", "main"))
        self.assertEqual(Path(wt), self.repo / ".claude/worktrees/fleet-x-2")
        self.assertEqual(self.sh("git", "rev-parse", "HEAD", cwd=wt), self.sh("git", "rev-parse", "main", cwd=self.repo))
        self.assertEqual(self.sh("git", "branch", "--show-current", cwd=wt), "worktree-fleet-x-2")

    def test_removed_only_when_clean_and_merged(self):
        wt = self.asyncio.run(self.git.add_worktree(self.repo, "t1", "main"))
        self.commit("work", cwd=wt)
        self.assertIn("isn't merged", self.asyncio.run(self.git.remove_worktree(self.repo, wt)))
        self.sh("git", "merge", "-q", "worktree-t1", cwd=self.repo)
        (Path(wt) / "scratch.txt").write_text("left behind")
        self.assertIn("untracked", self.asyncio.run(self.git.remove_worktree(self.repo, wt)))
        os.remove(Path(wt) / "scratch.txt")
        self.assertIsNone(self.asyncio.run(self.git.remove_worktree(self.repo, wt)))
        self.assertFalse(Path(wt).exists())
        self.assertNotIn("worktree-t1", self.sh("git", "branch", cwd=self.repo))


class RepoHold(GitRepo):
    """A merge paused on a dirty checkout resumes by itself once the checkout is clean."""

    def test_released_once_the_checkout_is_clean(self):
        fleet = Fleet.__new__(Fleet)
        fleet.cfg = {**config.DEFAULTS}
        fleet.runs = {}
        fleet.usage = lambda: {"limited": False}
        run = Run.from_plan({"repo": str(self.repo), "base": "main", "tickets": [{"id": "1", "title": "A"}]})
        run.d["status"] = "active"
        run.ticket("1")["state"] = MERGED
        run.d["finalCheck"] = "done"
        fleet.runs[run.id] = run
        (self.repo / "one.txt").write_text("dirty")
        fleet.hold(run, "Can't merge #1: dirty. Fix it, then resume the run.", "repo")
        self.asyncio.run(fleet.schedule())
        self.assertEqual(run.d["held"]["kind"], "repo")
        self.sh("git", "checkout", "one.txt", cwd=self.repo)
        self.asyncio.run(fleet.schedule())
        self.assertIsNone(run.d["held"])


class Popups(unittest.TestCase):
    """A desktop popup for a "needs you" item closes once the item clears, e.g. a merge the orchestrator retried."""

    def test_closed_when_the_item_clears_and_shown_again_if_it_returns(self):
        import asyncio
        from unittest import mock
        from fleet import daemon
        paths.STATE_JSON.parent.mkdir(parents=True, exist_ok=True)
        fleet = Fleet.__new__(Fleet)
        fleet.notified, fleet.popups, fleet.last_state = set(), {}, ""
        usage = {"limited": False, "stopped": 0, "until": None, "five_hour": {}}
        item = {"id": "r:46:merge_failed", "type": "merge_failed", "who": "#46", "msg": "The merger couldn't finish the merge."}
        snaps = [[item], [item], [], [item]]
        fleet.snapshot = lambda: {"attention": snaps.pop(0), "usage": usage}
        ids = iter([7, 8])

        async def notify_id(title, body):
            return next(ids)
        closed = []
        with mock.patch.object(daemon, "notify_id", notify_id), \
             mock.patch.object(daemon, "close_notification", closed.append):
            for _ in range(4):
                asyncio.run(fleet.write_state())
        self.assertEqual(closed, [7])
        self.assertEqual(fleet.popups, {"r:46:merge_failed": 8})


if __name__ == "__main__":
    unittest.main()
