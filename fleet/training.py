"""AI training the agents started: one TensorBoard per watch on the training machine, read through a tunnel.

An agent registers a watch (`fleet train watch`) naming a log directory and which TensorBoard tags mean what. Each
TensorBoard run under that directory becomes a row in the panel's AI-train tab. Nothing here knows a framework: all
tag meanings come from the agent. training.json holds the watches and the latest metrics, so it's both what the
panel reads and what survives a restart or a host going away.
"""
import asyncio
import fnmatch
import hashlib
import json
import math
import os
import re
import shlex
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from . import paths

RUNNING, FINISHED, STALLED, STOPPED, WAITING = "running", "finished", "stalled", "stopped", "waiting"
POLL_VIEWED_SEC = 15
POLL_IDLE_SEC = 60
VIEW_FRESH_SEC = 15
ETA_WINDOW = 6            # epochs of history the ETA and the stall limit look at
STALL_EPOCHS = 3          # no new data for this many epochs of recent speed means stalled
STALL_MIN_SEC = 120       # fast epochs still get a moment for a slow validation or a checkpoint
STALL_NO_SPEED_SEC = 3600 # before two epochs there's no speed to go by
MAX_POINTS = 300          # per curve in training.json
SAFE_RUN = re.compile(r"[\w./=+@:,-]+")


def _ssh(host):
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host]


async def sh(host, script, timeout=30):
    """Run a shell script on `host` (None = here). Returns (exit code, combined output). A timeout is exit code 124."""
    args = [*_ssh(host), script] if host else ["sh", "-c", script]
    proc = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, f"timed out after {timeout}s"
    return proc.returncode, out.decode(errors="replace").strip()


def http_json(port, path, timeout=20):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
        return json.load(r)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def path_expr(path):
    """`path` as a shell word: a leading ~ still expands on whichever machine runs it."""
    if path == "~" or path.startswith("~/"):
        return '"$HOME"' + shlex.quote(path[1:])
    return shlex.quote(path)


# ---------------------------------------------------------------------- metrics, pure so they're testable
def summed(series):
    """Add several [[wall, step, value], ...] series by step. A step counts only once every series has it: partial
    sums would make the curve jump at the step still being written."""
    if len(series) == 1:
        return series[0]
    maps = [{p[1]: p for p in s} for s in series]
    steps = set(maps[0]).intersection(*maps[1:]) if maps else set()
    return [[max(m[st][0] for m in maps), st, sum(m[st][2] for m in maps)] for st in sorted(steps)]


def thin(points, limit=MAX_POINTS):
    """Evenly thin a curve to `limit` points, always keeping the last."""
    if len(points) <= limit:
        return points
    stride = (len(points) - 1) / (limit - 1)
    return [points[round(i * stride)] for i in range(limit)]


def finite(points):
    return [p for p in points if math.isfinite(p[2])]


def epoch_of(points):
    """The epoch reached, from the epoch tag's steps. Frameworks count from 0 or from 1; a first step of 0 tells which."""
    return points[-1][1] + (1 if points[0][1] == 0 else 0) if points else 0


def seconds_per_epoch(points):
    recent = points[-ETA_WINDOW:]
    if len(recent) < 2 or recent[-1][1] <= recent[0][1]:
        return None
    return (recent[-1][0] - recent[0][0]) / (recent[-1][1] - recent[0][1])


def on_epoch_axis(points, epoch):
    """Curves log per step or per epoch, so each is scaled to run from its first step to the current epoch."""
    if not points:
        return []
    last = points[-1][1]
    if last <= 0:   # only step 0 so far: it was logged when the epoch ended, so it belongs at that epoch
        return [[epoch, p[2]] for p in thin(points)]
    return [[round(p[1] * epoch / last, 3), p[2]] for p in thin(points)]


def classify(run, tags, series, now, epochs):
    """Update one run's metrics and status from its scalars. `tags` is the watch's mapping; `series` is
    {tag: [[wall, step, value], ...]}. A stopped or finished run keeps its status."""
    def mapped(pattern):
        if not pattern:
            return []
        hits = [series[t] for t in sorted(series) if fnmatch.fnmatchcase(t, pattern) and series[t]]
        return summed(hits) if hits else []

    train, val, m, m50 = (mapped(tags.get(k)) for k in ("trainLoss", "valLoss", "map", "map50"))
    epoch = epoch_of(m)
    speed = seconds_per_epoch(m)
    last_data = max((s[-1][0] for s in series.values() if s), default=run.get("lastData") or run.get("firstSeen") or now)
    remaining = max(0, epochs - epoch) if epochs else None
    eta = max(0, remaining * speed - (now - m[-1][0])) if speed and remaining is not None else None

    classes = []
    if tags.get("classMap"):
        rx = re.compile(tags["classMap"])
        for tag in sorted(series):
            hit = rx.search(tag)
            if hit and series[tag]:
                classes.append({"name": hit.group(1), "map": series[tag][-1][2], "curve": on_epoch_axis(series[tag], epoch)})
        classes.sort(key=lambda c: c["map"])  # the classes in trouble first

    run.update(epoch=epoch, etaSec=eta, lastData=last_data, classes=classes,
               trainLoss=train[-1][2] if train else None, valLoss=val[-1][2] if val else None,
               map=m[-1][2] if m else None, map50=m50[-1][2] if m50 else None,
               curves={"trainLoss": on_epoch_axis(train, epoch), "valLoss": on_epoch_axis(val, epoch),
                       "map": on_epoch_axis(m, epoch), "map50": on_epoch_axis(m50, epoch)},
               raw={t: on_epoch_axis(s, epoch) for t, s in sorted(series.items()) if s})
    if run.get("status") in (STOPPED, FINISHED):
        return
    if epochs and epoch >= epochs:
        run["status"] = FINISHED
        run["etaSec"] = 0
        return
    limit = max(STALL_EPOCHS * speed, STALL_MIN_SEC) if speed else STALL_NO_SPEED_SEC
    run["status"] = STALLED if now - last_data > limit else RUNNING


# ---------------------------------------------------------------------- the monitor
class Training:
    def __init__(self):
        self.watches = {}
        self.runs = {}        # run id -> the row the panel shows
        self.forwards = {}    # watch id -> ssh -L process; dies with the daemon's cgroup, so never persisted
        self.viewed_at = 0
        self.polled_at = 0
        self.last_body = None
        self.lock = asyncio.Lock()
        self.load()

    def load(self):
        try:
            d = json.loads(paths.TRAINING_JSON.read_text())
        except (OSError, json.JSONDecodeError):
            return
        self.watches = {w["id"]: w for w in d.get("watches", [])}
        self.runs = {r["id"]: r for r in d.get("runs", []) if not r.get("placeholder")}

    def save(self):
        body = json.dumps({"watches": list(self.watches.values()), "runs": self.rows()})
        if body == self.last_body:
            return
        self.last_body = body
        paths.ensure()
        tmp = paths.TRAINING_JSON.with_suffix(".tmp")
        tmp.write_text(body)
        tmp.replace(paths.TRAINING_JSON)

    def rows(self):
        """What the tab lists: every run, plus a stand-in for a watch with none yet, which otherwise couldn't be seen
        or removed."""
        rows = sorted(self.runs.values(), key=lambda r: r.get("firstSeen") or 0, reverse=True)
        for w in self.watches.values():
            if not any(r["watch"] == w["id"] for r in self.runs.values()):
                rows.append({"id": w["id"], "watch": w["id"], "placeholder": True, "status": WAITING,
                             "name": os.path.basename(w["dir"].rstrip("/")) or w["dir"], "machine": self.machine(w),
                             "unreachable": w.get("unreachable", False), "error": w.get("error", ""),
                             "epochs": w.get("epochs"), "epoch": 0, "curves": {}, "classes": [], "raw": {}})
        return rows

    @staticmethod
    def machine(w):
        return w.get("host") or socket.gethostname()

    def training_sessions(self):
        """Session ids with a run still going, for the Agentic tab's pill."""
        return {self.watches[r["watch"]].get("session") for r in self.runs.values()
                if r.get("status") in (RUNNING, STALLED) and r["watch"] in self.watches} - {None}

    # ------------------------------------------------------------------ registering
    async def watch(self, req, session):
        directory = req["dir"]
        host = req.get("host") or None
        for key in ("tensorboard", "stop", "trainLoss", "map"):
            if not req.get(key):
                raise ValueError(f"{key} is required")
        epochs = int(req["epochs"])
        if epochs < 1:
            raise ValueError("--epochs must be at least 1")
        if req.get("classMap"):
            try:
                groups = re.compile(req["classMap"]).groups
            except re.error as e:
                raise ValueError(f"--class-map isn't a valid regex: {e}")
            if groups != 1:
                raise ValueError("--class-map needs exactly one capture group, the class name")
        wid = hashlib.sha1(f"{host}\0{directory}".encode()).hexdigest()[:10]
        w = self.watches.get(wid, {})
        w.update(id=wid, host=host, dir=directory, tensorboard=req["tensorboard"], epochs=epochs, stop=req["stop"],
                 session=session, removed=[], tags={k: req.get(k) or "" for k in
                                                    ("trainLoss", "valLoss", "map", "map50", "classMap")})
        w.setdefault("created", time.time())
        await self.ensure(w)     # a watch that can't start is the agent's to fix now, so it isn't kept
        self.watches[wid] = w
        self.polled_at = 0
        self.save()
        return {"watch": wid, "machine": self.machine(w)}

    # ------------------------------------------------------------------ TensorBoard and its tunnel
    @staticmethod
    def _tb_files(wid):
        return f'"$HOME/.cache/ai-fleet/tb-{wid}"'

    async def tb_port(self, w):
        """The port of this watch's TensorBoard if it's alive, else None. Raises OSError if the host can't be reached.
        One started without --reload_multifile is stopped so it comes back with it: without that flag, TensorBoard
        stops following training's log as soon as something else writes a newer file beside it."""
        files = self._tb_files(w["id"])
        rc, out = await sh(w.get("host"), f'''f={files}; p=$(cat "$f.pid" 2>/dev/null) || exit 0
a=$(ps -o args= -p "$p" 2>/dev/null); case "$a" in *tensorboard*) ;; *) exit 0;; esac
case "$a" in *reload_multifile*) ;; *) kill "$p"; exit 0;; esac
sed -n 's|.*http://[^:]*:\\([0-9][0-9]*\\)/.*|PORT=\\1|p' "$f.log" | head -1''')
        if rc in (124, 255):
            raise OSError(out or f"can't reach {w.get('host')}")
        m = re.search(r"PORT=(\d+)", out)
        return int(m.group(1)) if m else None

    async def start_tb(self, w):
        files = self._tb_files(w["id"])
        rc, out = await sh(w.get("host"), f'''f={files}; mkdir -p "$(dirname "$f")"; tb={path_expr(w["tensorboard"])}
[ -x "$tb" ] || command -v "$tb" >/dev/null 2>&1 || {{ echo "no tensorboard at $tb"; exit 3; }}
: > "$f.log"
setsid nohup "$tb" --logdir {path_expr(w["dir"])} --host 127.0.0.1 --port 0 --reload_interval 15 --reload_multifile true >"$f.log" 2>&1 </dev/null &
echo $! > "$f.pid"
for i in $(seq 1 60); do
  grep -q 'http://' "$f.log" && exit 0
  kill -0 $! 2>/dev/null || {{ tail -5 "$f.log"; exit 4; }}
  sleep 1
done
echo "tensorboard didn't start within 60s"; tail -5 "$f.log"; exit 5''', timeout=80)
        if rc in (124, 255):
            raise OSError(out or f"can't reach {w.get('host')}")
        if rc != 0:
            raise ValueError(out or "tensorboard didn't start")
        port = await self.tb_port(w)
        if not port:
            raise ValueError("tensorboard started but didn't say which port it's on")
        return port

    async def forward(self, w, port):
        """A local port reaching TensorBoard's: the port itself on this machine, an ssh -L for anywhere else."""
        if not w.get("host"):
            return port
        cur = self.forwards.get(w["id"])
        if cur and cur["proc"].returncode is None and cur["remote"] == port:
            return cur["local"]
        await self.drop_forward(w["id"])
        local = free_port()
        proc = await asyncio.create_subprocess_exec(
            *_ssh(w["host"]), "-N", "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=15",
            "-L", f"127.0.0.1:{local}:127.0.0.1:{port}", stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        self.forwards[w["id"]] = {"proc": proc, "local": local, "remote": port}
        for _ in range(40):
            with socket.socket() as s:
                s.settimeout(0.5)
                if s.connect_ex(("127.0.0.1", local)) == 0:
                    return local
            if proc.returncode is not None:
                break
            await asyncio.sleep(0.25)
        await self.drop_forward(w["id"])
        raise OSError(f"can't forward to {w['host']}")

    async def drop_forward(self, wid):
        cur = self.forwards.pop(wid, None)
        if cur and cur["proc"].returncode is None:
            cur["proc"].terminate()
            await cur["proc"].wait()

    async def ensure(self, w):
        """TensorBoard running and reachable, restarted if the machine rebooted. Returns the local port."""
        port = await self.tb_port(w) or await self.start_tb(w)
        return await self.forward(w, port)

    async def end_watch(self, w):
        await self.drop_forward(w["id"])
        files = self._tb_files(w["id"])
        rc, out = await sh(w.get("host"), f'''f={files}; p=$(cat "$f.pid" 2>/dev/null)
[ -n "$p" ] && ps -o args= -p "$p" 2>/dev/null | grep -q tensorboard && kill "$p"
rm -f "$f.pid" "$f.log"; true''')
        if rc != 0:   # the machine is away: the row still goes, but its TensorBoard has to be cleaned up by hand
            print(f"[training] couldn't stop TensorBoard for {w['dir']} on {self.machine(w)}: {out}", flush=True)
        self.watches.pop(w["id"], None)

    # ------------------------------------------------------------------ polling
    async def poll(self):
        interval = POLL_VIEWED_SEC if time.time() - self.viewed_at < VIEW_FRESH_SEC else POLL_IDLE_SEC
        if not self.watches or time.time() - self.polled_at < interval:
            return
        self.polled_at = time.time()
        async with self.lock:
            await asyncio.gather(*(self.poll_watch(w) for w in list(self.watches.values())))
            self.save()

    def _set_reachable(self, w, ok, error=""):
        w["unreachable"] = not ok
        w["error"] = error
        for r in self.runs.values():
            if r["watch"] == w["id"]:
                r["unreachable"] = not ok

    async def poll_watch(self, w):
        """Runs even with every known run done: a queue can always start another."""
        try:
            port = await self.ensure(w)
            tags = await asyncio.to_thread(http_json, port, "/data/plugin/scalars/tags")
        except OSError as e:   # URLError is an OSError: the host, the tunnel or TensorBoard is away
            await self.drop_forward(w["id"])
            self._set_reachable(w, False, str(e))
            return
        except ValueError as e:   # it answers, but TensorBoard won't start
            self._set_reachable(w, True, str(e))
            return
        self._set_reachable(w, True)
        now = time.time()
        for name, run_tags in tags.items():
            if name in w.get("removed", []):
                continue
            rid = f"{w['id']}-{hashlib.sha1(name.encode()).hexdigest()[:8]}"
            run = self.runs.get(rid)
            if run and run.get("status") in (STOPPED, FINISHED) and run.get("closedOut"):
                continue
            series = await self.fetch(port, name, list(run_tags))
            if series is None:
                continue
            if not run:
                run = self.runs[rid] = {"id": rid, "watch": w["id"], "firstSeen": now, "status": RUNNING,
                                        "name": os.path.basename(w["dir"].rstrip("/")) if name == "." else name,
                                        "tbRun": name, "machine": self.machine(w), "epochs": w["epochs"], "unreachable": False}
            classify(run, w["tags"], series, now, w["epochs"])
            if run["status"] in (STOPPED, FINISHED):
                run["closedOut"] = True   # one last read happened; its curves won't change

    @staticmethod
    async def fetch(port, name, tags):
        run = urllib.parse.quote(name, safe="")

        async def one(tag):
            q = f"/data/plugin/scalars/scalars?tag={urllib.parse.quote(tag, safe='')}&run={run}&format=json"
            return tag, finite(await asyncio.to_thread(http_json, port, q))
        try:
            return dict(await asyncio.gather(*(one(t) for t in tags)))
        except (OSError, ValueError) as e:
            print(f"[training] reading {name}: {e}", flush=True)
            return None

    # ------------------------------------------------------------------ the panel's actions
    def _row(self, rid):
        r = self.runs.get(rid)
        if not r:
            raise ValueError(f"no training run {rid!r}")
        return r, self.watches.get(r["watch"])

    async def stop(self, rid):
        run, w = self._row(rid)
        if run["status"] not in (RUNNING, STALLED):
            raise ValueError(f"{run['name']} isn't running")
        name = run["tbRun"]
        if name == ".":
            name = run["name"]
        if not SAFE_RUN.fullmatch(name):   # it goes into a shell command the agent wrote
            raise ValueError(f"can't stop {name!r}: its name has characters that aren't safe in a command")
        rc, out = await sh(w.get("host"), w["stop"].replace("{run}", name), timeout=60)
        if rc != 0:
            run["error"] = f"stop command failed: {out or f'exit {rc}'}"
            self.save()
            raise ValueError(run["error"])
        run.update(status=STOPPED, error="", etaSec=None, closedOut=True)
        self.save()
        return {}

    async def remove(self, rid):
        """Takes a run out of ai-fleet; its logs on the training machine stay. A watch with no rows left ends."""
        if rid in self.watches:   # the stand-in row of a watch with no runs
            await self.end_watch(self.watches[rid])
            self.save()
            return {}
        run, w = self._row(rid)
        if run["status"] == RUNNING and not run.get("unreachable"):
            raise ValueError(f"{run['name']} is still running; stop it first")
        del self.runs[rid]
        if w:
            w.setdefault("removed", []).append(run["tbRun"])
            if not any(r["watch"] == w["id"] for r in self.runs.values()):
                await self.end_watch(w)
        self.save()
        return {}
