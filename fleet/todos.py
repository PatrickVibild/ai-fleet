"""Your todos and reminders: one global list in todos.json, shown in the panel's Todo tab.

The CLI writes the file directly under a lock, so todos work while the daemon is down; the daemon only reads it to
pop a desktop notification when a todo comes due. A todo with a due time is a reminder.
"""
import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import time

from . import paths

DEFAULT_HOUR = 9   # a due date with no time means 09:00

_UNITS = {"m": 60, "h": 3600, "d": 86400}


def parse_due(text, now=None):
    """Unix time for `14:00`, `today 14:00`, `tomorrow [9:00]`, `2026-11-12 [14:00]`, `+30m`, `+2h` or `+3d`.
    Raises ValueError on anything else."""
    now = now if now is not None else time.time()
    s = " ".join(str(text).lower().split())
    m = re.fullmatch(r"\+(\d+)\s*([mhd])", s)
    if m:
        return now + int(m.group(1)) * _UNITS[m.group(2)]
    today = dt.datetime.fromtimestamp(now).date()
    m = re.fullmatch(r"(?:(today|tomorrow|\d{4}-\d{2}-\d{2})\s*)?(?:(\d{1,2}):(\d{2}))?", s)
    if not s or not m:
        raise ValueError(f"can't read due time {text!r}; try 14:00, tomorrow 9:00, 2026-11-12 14:00, +2h or +3d")
    day, hh, mm = m.groups()
    if day == "tomorrow":
        date = today + dt.timedelta(days=1)
    elif day and day != "today":
        date = dt.date.fromisoformat(day)
    else:
        date = today
    hour, minute = (int(hh), int(mm)) if hh else (DEFAULT_HOUR, 0)
    if hour > 23 or minute > 59:
        raise ValueError(f"can't read due time {text!r}: no such time of day")
    return dt.datetime.combine(date, dt.time(hour, minute)).timestamp()


def md_path(path):
    """The absolute path of a Markdown file to link, or ValueError if there's no such file."""
    p = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(p):
        raise ValueError(f"no such file: {p}")
    return p


@contextlib.contextmanager
def _locked():
    """The list, held under a lock for the block; whatever the block leaves in it is saved."""
    paths.ensure()
    with open(paths.TODOS_JSON.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        d = load()
        yield d
        tmp = paths.TODOS_JSON.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1))
        tmp.replace(paths.TODOS_JSON)


def load():
    try:
        return json.loads(paths.TODOS_JSON.read_text())
    except (OSError, json.JSONDecodeError):
        return {"next": 1, "todos": []}


def ordered(todos):
    """Open reminders by due time, then open todos oldest first, then done ones, latest done first."""
    return (sorted((t for t in todos if not t["done"] and t.get("due")), key=lambda t: t["due"])
            + [t for t in todos if not t["done"] and not t.get("due")]
            + sorted((t for t in todos if t["done"]), key=lambda t: -(t.get("doneAt") or 0)))


def _find(d, tid):
    for t in d["todos"]:
        if t["id"] == int(tid):
            return t
    raise ValueError(f"no todo {tid}")


def add(text, due=None, md=None):
    text = text.strip()
    if not text:
        raise ValueError("a todo needs some text")
    with _locked() as d:
        t = {"id": d["next"], "text": text, "due": due, "md": md, "done": False, "created": time.time()}
        d["next"] += 1
        d["todos"].append(t)
    return t


def edit(tid, text=None, due=None, md=None):
    """Change the fields given; pass due=False or md=False to clear one. A new due time can notify again."""
    with _locked() as d:
        t = _find(d, tid)
        if text is not None:
            if not text.strip():
                raise ValueError("a todo needs some text")
            t["text"] = text.strip()
        if due is not None:
            t["due"] = due or None
            t.pop("notified", None)
        if md is not None:
            t["md"] = md or None
    return t


def set_done(tid, done=True):
    with _locked() as d:
        t = _find(d, tid)
        t["done"] = done
        t["doneAt"] = time.time() if done else None
    return t


def remove(tid):
    with _locked() as d:
        t = _find(d, tid)
        d["todos"].remove(t)
    return t


def clear_done():
    with _locked() as d:
        n = sum(t["done"] for t in d["todos"])
        d["todos"] = [t for t in d["todos"] if not t["done"]]
    return n


def take_due(now=None):
    """Open reminders that have come due and weren't announced yet, marked announced so each pops up once."""
    now = now if now is not None else time.time()
    if not any(not t["done"] and t.get("due") and t["due"] <= now and not t.get("notified") for t in load()["todos"]):
        return []
    with _locked() as d:
        due = [t for t in d["todos"] if not t["done"] and t.get("due") and t["due"] <= now and not t.get("notified")]
        for t in due:
            t["notified"] = True
    return due
