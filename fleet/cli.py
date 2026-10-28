"""`fleet` command line: the orchestrator skill, the panel and you all talk to the daemon through this."""
import argparse
import json
import os
import socket
import sys
import time

from . import paths
from .runs import JUDGMENT


def call(req, timeout=None):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            s.connect(str(paths.SOCK))
        except OSError:
            sys.exit("ai-fleet daemon isn't running. Start it with: systemctl --user start ai-fleet")
        s.sendall((json.dumps(req) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(1 << 20)
            if not chunk:
                break
            buf += chunk
    resp = json.loads(buf or b'{"ok": false, "error": "no reply"}')
    if not resp.get("ok"):
        sys.exit(f"fleet: {resp.get('error')}")
    return resp


def cmd_status(a):
    st = call({"op": "state"})["state"]
    if a.json:
        print(json.dumps(st, indent=1))
        return
    lim = st["limits"]
    u = st.get("usage") or {}
    if u.get("limited") or u.get("stopped"):
        until = time.strftime("%H:%M", time.localtime(u["until"])) if u.get("until") else "?"
        print(f"usage limit: {'hit, resets ' + until if u.get('limited') else 'reset'} · "
              f"{u.get('stopped', 0)} agents stopped (fleet continue)")
    print(f"limits: {lim['orchestrators']} orchestrators × {lim['implementors_per_orchestrator']} implementors · summaries: {st['summaries']}")
    for r in st["runs"]:
        merged = sum(t["state"] == "merged" for t in r["tickets"])
        print(f"\n{r['id']}  [{r['status']}]  {merged}/{len(r['tickets'])} merged  {r['repo']}")
        if r.get("held"):
            print(f"  held: {r['held']['reason']}")
        g = r.get("git")
        if g and g["pushed"]:
            print(f"  pushed to {g['remote']}")
        elif g:
            why = (g.get("push") or {}).get("msg") or (f"{g['unpushed']} commits only here" if g["remote"] else "no remote")
            print(f"  not pushed: {why}  (fleet push {r['repo']})")
        if r.get("finalCheck") in ("running", "cleanup") and r["status"] == "active":
            mins = int((time.time() - (r.get("finalCheckAt") or time.time())) // 60)
            print(f"  every ticket merged; final check running for {mins} min: {r.get('finalCmd') or '(none)'}"
                  if r["finalCheck"] == "running" else "  every ticket merged and green; cleaning up worktrees")
        for t in r["tickets"]:
            blocked = f" (blocked by {', '.join('#' + b for b in t['blockedBy'])})" if t["blockedBy"] else ""
            print(f"  #{t['id']:<5} {t['state']:<9} {t['title']}{blocked}")
    if st["attention"]:
        print("\nneeds you:")
        for x in st["attention"]:
            print(f"  [{x['type']}] {x['who']}: {x.get('msg')}  ({x['id']})")
    if st["sessions"]:
        print("\nyour sessions:")
        for s in st["sessions"]:
            forgotten = f"  [forgotten: idle {s['idleFor'] / 3600:.1f}h, no terminal]" if s.get("forgotten") else ""
            print(f"  {s['short']}  {s['state']:<5} {s['tag']}  {s['status']}{forgotten}")
        if any(s.get("forgotten") for s in st["sessions"]):
            print("  (fleet stop-forgotten stops them)")


def cmd_submit(a):
    plan = json.load(sys.stdin if a.plan == "-" else open(a.plan))
    r = call({"op": "submit", "plan": plan})
    print(json.dumps({k: r[k] for k in ("run", "status", "events")}))


def cmd_events(a):
    path = call({"op": "events", "run": a.run})["path"]
    pos = 0
    while True:
        try:
            with open(path) as f:
                f.seek(pos)
                for line in f:
                    if not line.endswith("\n"):
                        break
                    pos += len(line.encode())
                    ev = json.loads(line)
                    if (a.all or ev["type"] in JUDGMENT) and ev["ts"] > a.since:
                        print(json.dumps(ev), flush=True)
        except FileNotFoundError:
            pass
        if not a.follow:
            return
        time.sleep(1)


def cmd_answer(a):
    req = {"op": "answer", "qid": a.qid, "by": a.by, "source": a.source}
    if a.json:
        req["answers"] = json.loads(a.json)
    else:
        req["answer"] = a.answer
    call(req)


def cmd_verdict(a):
    quotes = [q.split("::", 1) if "::" in q else ["", q] for q in a.quote or []]
    call({"op": "verdict", "run": a.run, "ticket": a.ticket, "action": a.action, "note": a.note,
          "diagnosis": a.diagnosis, "quotes": quotes})


def cmd_ctl(a):
    req = {"op": "ctl", "action": a.cmd}
    for k in ("run", "ticket", "note", "session"):
        if getattr(a, k, None) is not None:
            req[k] = getattr(a, k)
    if a.cmd == "stop":
        req["action"] = "kill-session"
    call(req)


def cmd_continue(a):
    r = call({"op": "ctl", "action": "continue", "note": a.note}, timeout=600)
    print(f"resumed {len(r['resumed'])}: {' '.join(r['resumed']) or '-'}")
    for x in r["skipped"]:
        print(f"skipped {x}")


def cmd_push(a):
    r = call({"op": "ctl", "action": "push", "path": os.path.realpath(os.path.expanduser(a.path))}, timeout=300)
    print(r["msg"])


def cmd_limits(a):
    req = {"op": "limits"}
    if a.orchestrators:
        req["orchestrators"] = a.orchestrators
    if a.per:
        req["implementors_per_orchestrator"] = a.per
    if a.summaries:
        req["summaries"] = a.summaries
    if a.stop_forgotten_after is not None:
        req["stop_forgotten_after_hours"] = a.stop_forgotten_after
    call(req)
    lim = call({"op": "state"})["state"]["limits"]
    print(f"{lim['orchestrators']} orchestrators × {lim['implementors_per_orchestrator']} implementors each")


def cmd_cc(a):
    """Start your own Claude session in the background (survives closing the terminal), then attach to it."""
    from . import claude as c
    import asyncio
    settings = paths.STATE / "manual-settings.json"
    paths.ensure()
    settings.write_text(json.dumps({"statusLine": {"type": "command", "command": str(paths.STATUSLINE_HOOK), "padding": 0}}))
    prompt = " ".join(a.prompt) or None
    name = a.name or os.path.basename(os.getcwd())
    short = asyncio.run(c.spawn_bg(cwd=os.getcwd(), prompt=prompt, name=name, settings=settings,
                                   worktree=a.worktree, permission_mode=a.permission_mode))
    os.execvp(c.CLAUDE, [c.CLAUDE, "attach", short])


def cmd_askpass(a):
    """SUDO_ASKPASS helper: asks for the password through the Fleet panel. sudo passes the prompt as argv[1]."""
    command = os.environ.get("AI_FLEET_SUDO_CMD", "")
    r = call({"op": "sudo", "prompt": " ".join(a.prompt), "command": command})
    if r.get("denied") or r.get("password") is None:
        sys.exit(1)
    print(r["password"])


def cmd_sudo_answer(a):
    """Answer a sudo request from the panel. The password comes on stdin so it never shows in `ps`."""
    if a.deny:
        call({"op": "sudo-answer", "id": a.id, "deny": True})
        return
    password = sys.stdin.readline().rstrip("\n")
    call({"op": "sudo-answer", "id": a.id, "password": password})


def main():
    p = argparse.ArgumentParser(prog="fleet", description="Run and watch Claude agents (ai-fleet).")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("daemon", help="run the daemon in the foreground")
    s = sub.add_parser("status", help="show runs, tickets and what needs you")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("submit", help="submit a plan (JSON file, or - for stdin)")
    s.add_argument("plan")
    s = sub.add_parser("events", help="print a run's events; --follow to keep watching")
    s.add_argument("run")
    s.add_argument("--follow", "-f", action="store_true")
    s.add_argument("--all", action="store_true", help="include routine events too")
    s.add_argument("--since", type=float, default=0, help="only events after this unix time")
    s = sub.add_parser("answer", help="answer an implementor's question")
    s.add_argument("qid")
    s.add_argument("answer", nargs="?", default="")
    s.add_argument("--json", help='answers as {"question text": "answer"}')
    s.add_argument("--source", default="", help="where the answer came from (spec section, ADR…)")
    s.add_argument("--by", default="orchestrator", choices=["orchestrator", "user"])
    s = sub.add_parser("escalate", help="hand a question to the user")
    s.add_argument("qid")
    s.add_argument("--why", default="")
    s = sub.add_parser("verdict", help="decide what happens after a ticket's tests fail")
    s.add_argument("run")
    s.add_argument("ticket")
    s.add_argument("action", choices=["fix", "escalate"])
    s.add_argument("--note")
    s.add_argument("--diagnosis")
    s.add_argument("--quote", action="append", help="label::text, e.g. 'Ticket #15::Round each line'")
    for name in ("pause", "resume", "abort"):
        sub.add_parser(name).add_argument("run")
    sub.add_parser("close", help="take a finished or aborted run off the panel").add_argument("run")
    for name in ("kill", "retry"):
        s = sub.add_parser(name)
        s.add_argument("run")
        s.add_argument("ticket")
    s = sub.add_parser("sendback", help="send a stopped ticket back to its implementor with a note")
    s.add_argument("run")
    s.add_argument("ticket")
    s.add_argument("note")
    for name in ("open", "stop"):
        sub.add_parser(name, help=f"{name} a session by short id").add_argument("session")
    s = sub.add_parser("push", help="push a finished run's repo, or a session's work, to its remote")
    s.add_argument("path", help="the run's repo or the session's working directory")
    s = sub.add_parser("continue", help="resume every agent the usage limit stopped")
    s.add_argument("--note", help="the message sent to each agent (default: carry on where you left off)")
    s = sub.add_parser("limits", help="show or change the limits")
    s.add_argument("--orchestrators", type=int)
    s.add_argument("--per", type=int, help="implementors per orchestrator")
    s.add_argument("--summaries", choices=["tool", "ai"])
    s.add_argument("--stop-forgotten-after", type=int, metavar="HOURS",
                   help="stop your sessions left idle with no terminal this long on their own (0 = never)")
    sub.add_parser("stop-forgotten", help="stop your sessions left idle with no terminal attached")
    s = sub.add_parser("cc", help="start a background Claude session here and attach to it")
    s.add_argument("prompt", nargs="*")
    s.add_argument("-n", "--name")
    s.add_argument("-w", "--worktree")
    s.add_argument("--permission-mode", default="auto")
    s = sub.add_parser("sudo-answer", help="answer a sudo request (password on stdin)")
    s.add_argument("id")
    s.add_argument("--deny", action="store_true")
    sub.add_parser("viewing", help="tell the daemon the panel is open (AI summaries only run then)")
    s = sub.add_parser("askpass")
    s.add_argument("prompt", nargs="*")
    a = p.parse_args()

    if a.cmd == "daemon":
        from .daemon import main as daemon_main
        daemon_main()
    elif a.cmd == "status":
        cmd_status(a)
    elif a.cmd == "submit":
        cmd_submit(a)
    elif a.cmd == "events":
        cmd_events(a)
    elif a.cmd == "answer":
        cmd_answer(a)
    elif a.cmd == "escalate":
        call({"op": "escalate", "qid": a.qid, "why": a.why})
    elif a.cmd == "verdict":
        cmd_verdict(a)
    elif a.cmd in ("pause", "resume", "abort", "close", "kill", "retry", "sendback", "open", "stop"):
        cmd_ctl(a)
    elif a.cmd == "continue":
        cmd_continue(a)
    elif a.cmd == "push":
        cmd_push(a)
    elif a.cmd == "limits":
        cmd_limits(a)
    elif a.cmd == "stop-forgotten":
        r = call({"op": "ctl", "action": "stop-forgotten"}, timeout=120)
        print(f"stopped {len(r['stopped'])}: {', '.join(r['stopped']) or '-'}")
    elif a.cmd == "cc":
        cmd_cc(a)
    elif a.cmd == "sudo-answer":
        cmd_sudo_answer(a)
    elif a.cmd == "viewing":
        call({"op": "viewing"}, timeout=5)
    elif a.cmd == "askpass":
        cmd_askpass(a)
