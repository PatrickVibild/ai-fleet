"""A made-up run for looking at the panel without spending agents: `fleet mock on`.

It exists only in the panel's snapshot. No Run is created, so nothing is scheduled, stalled, woken, merged or
notified, and its rows have no session to open or kill. It is shaped like the docs-diet run (six tickets, two
waves of blockers) and moves with the clock: the daemon's check on #40 counts its tests up over CHECK_SEC,
turns a test red on the way, finishes, and starts again.
"""

CHECK_SEC = 100   # one pass of the daemon's check on #40
PAUSE_SEC = 20    # how long it shows the finished result before starting again
EXPECTED = 4904
FAIL_AT = 0.63    # share of the run after which one test has failed

TICKETS = [
    ("38", "Docs diet: tighten the user-docs style guide", [], "merged"),
    ("39", "Docs diet: rewrite Get started and the front page (the sample)", ["38"], "merged"),
    ("40", "Docs diet: shrink the generated settings reference", ["38"], "testing"),
    ("41", "Docs diet: settings reference intros, CLI page and hint sentences", ["39", "40"], "wait"),
    ("42", "Docs diet: guides for configurations, the runs catalogue and the studio sandbox", ["39"], "running"),
    ("43", "Docs diet: guides for export, regate, and stereo/sonar/depth", ["39"], "review"),
]
TITLE = {tid: title for tid, title, _, _ in TICKETS}
WINDOW = 1_000_000


def agent(id, kind, name, tag, status, started, ctx, tokens, note="", tests=None, children=(), ticket=None):
    return {"id": id, "sessionId": None, "short": "", "kind": kind, "name": name, "tag": tag, "state": "run",
            "alive": True, "waitingFor": None, "ctx": {"used": ctx, "size": WINDOW}, "tokens": tokens,
            "startedAt": started, "endedAt": None, "status": status, "summary": None, "events": [], "task": "",
            "activity": "working", "limited": False, "tests": tests, "note": note, "ticket": ticket,
            "children": list(children)}


def counts(passed, failed, skipped, **extra):
    return {"passed": passed, "failed": failed, "skipped": skipped, "total": passed + failed + skipped, **extra}


def check(id, what, where, cmd, started, ended, tests, ticket=None, red=False):
    if ended is None:
        state, status, note = "run", f"Running `{cmd}`", "running"
    else:
        state, status, note = "done", (f"Failed (exit 1): `{cmd}`" if red else f"Passed: `{cmd}`"), "red" if red else "green"
    return {"id": id, "kind": "check", "name": f"daemon · {what}", "tag": where, "state": state, "status": status,
            "note": note, "ticket": ticket, "startedAt": started, "endedAt": ended, "tests": tests, "children": []}


def live_check(now, started):
    """The daemon's check on #40: counting up, then the finished result, then again."""
    cycle = CHECK_SEC + PAUSE_SEC
    t = (now - started) % cycle
    began = now - t
    done = min(1.0, t / CHECK_SEC)
    ran = int(EXPECTED * done)
    skipped = int(ran * 91 / EXPECTED)
    failed = 1 if done >= FAIL_AT else 0
    cmd = "/home/patrick/repos/Aegir/.venv/bin/python -m pytest -q"
    if t < CHECK_SEC:
        tests = counts(ran - skipped - failed, failed, skipped, expected=EXPECTED, estimated=True)
        return check("mock-check-40", "tests", "#40 " + TITLE["40"], cmd, began, None, tests, ticket="40")
    tests = counts(EXPECTED - 91 - 1, 1, 91)
    return check("mock-check-40", "tests", "#40 " + TITLE["40"], cmd, began, began + CHECK_SEC, tests,
                 ticket="40", red=True)


def run(now, started, max_slots):
    orch_started = started - 2 * 3600 - 9 * 60
    shell = {"id": "mock-shell-42", "kind": "shell", "name": "pytest -q tests/test_docs.py", "tag": "",
             "state": "run", "startedAt": now - 7, "status": "Run the docs tests", "children": []}
    tdd = {"id": "mock-skill-42", "kind": "skill", "name": "tester", "tag": "/tdd", "state": "run",
           "startedAt": now - 300, "endedAt": None, "status": "", "children": [shell]}
    lanes = [
        agent("mock-impl-42", "implementor", "implementor", "#42 " + TITLE["42"],
              "Editing docs/guides/configurations.md", started - 14 * 60, 86_000, 1_240_000, ticket="42",
              tests=counts(212, 0, 3, cmd="pytest -q tests/test_docs.py"), children=[tdd]),
        agent("mock-impl-40", "implementor", "implementor", "#40 " + TITLE["40"],
              "Running the tests: /home/patrick/repos/Aegir/.venv/bin/python -m pytest -q", started - 31 * 60,
              143_000, 2_010_000, note="testing", ticket="40"),
        live_check(now, started),
        agent("mock-impl-43", "implementor", "implementor", "#43 " + TITLE["43"],
              "Tests failed; the orchestrator is deciding what to do", started - 26 * 60, 171_000, 2_380_000,
              note="tests red", ticket="43", tests=counts(4811, 2, 91, cmd="pytest -q")),
        check("mock-quick-39", "quick check", "main after #39", "/home/patrick/repos/Aegir/.venv/bin/python -m pytest -q",
              now - 260, now - 170, counts(4812, 0, 91)),
    ]
    tree = agent("mock-orch", "orchestrator", "orchestrator", "docs-diet (mock)",
                 "Said: #40 is in its tests; #43 failed 2 tests, so I'm reading them to tell a code bug from a spec gap.",
                 orch_started, 212_000, 406_700, children=lanes)
    tree["activity"] = "idle"
    return {"id": "mock-docs-diet", "name": "docs-diet (mock)", "repo": "/home/patrick/repos/Aegir", "base": "main",
            "status": "active", "held": None, "problem": None, "finalCheck": None, "finalCheckAt": None,
            "finalCmd": "/home/patrick/repos/Aegir/.venv/bin/python -m pytest -q",
            "slots": {"used": 3, "max": max_slots},
            "tickets": [{"id": tid, "title": title, "blockedBy": blocked, "state": state, "blockedOn": [], "short": ""}
                        for tid, title, blocked, state in TICKETS],
            "tree": tree, "git": None, "mock": True}
