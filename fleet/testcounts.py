"""Pass/fail counts read from a test runner's output (pytest, unittest, jest, vitest, playwright, mocha, cargo, go -v).

parse() returns {"passed", "failed", "skipped", "total"} from the runner's summary, or None when the output
has no summary we recognise (it isn't a test run, or it was cut off before the end). Progress counts the
same while the output streams in, from the per-test marks runners print as they go.
"""
import re

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
WORDS = re.compile(r"(\d+) ([a-z]+(?: not run)?)")
TEST_COMMAND = re.compile(
    r"\b(pytest|py\.test|unittest|nose2|tox|nox|jest|vitest|playwright|mocha|cypress|rspec|phpunit|ctest"
    r"|cargo (?:test|nextest)|go test|(?:bun|deno) test|(?:npm|pnpm|yarn|bun)(?: run)? (?:test|e2e|smoke)"
    r"|(?:make|just) (?:test|check|e2e|smoke)|tests?\.sh)")


def is_test_command(cmd):
    """Whether a shell command runs tests, so a grep or cat that happens to print a summary isn't counted."""
    return bool(TEST_COMMAND.search(cmd or ""))


def counts(passed=0, failed=0, skipped=0, total=None):
    return {"passed": passed, "failed": failed, "skipped": skipped,
            "total": total if total is not None else passed + failed + skipped}


def tally(text):
    out = {}
    for n, w in WORDS.findall(text):
        out[w] = out.get(w, 0) + int(n)
    return out


def _jest(t):   # Tests:       1 failed, 2 skipped, 40 passed, 43 total
    m = re.findall(r"^Tests:\s+(.+?)\s*$", t, re.M)
    if not m:
        return None
    w = tally(m[-1])
    return counts(w.get("passed", 0), w.get("failed", 0), w.get("skipped", 0) + w.get("todo", 0), w.get("total"))


def _vitest(t):   # Tests  1 failed | 40 passed (41)
    m = re.findall(r"^\s*Tests\s+(.+?)\s*\(\s*(\d+)\s*\)\s*$", t, re.M)
    if not m:
        return None
    w = tally(m[-1][0])
    return counts(w.get("passed", 0), w.get("failed", 0), w.get("skipped", 0) + w.get("todo", 0), int(m[-1][1]))


def _cargo(t):   # test result: ok. 40 passed; 1 failed; 2 ignored; ... (one per test binary)
    m = re.findall(r"test result: \w+\. (\d+) passed; (\d+) failed; (\d+) ignored", t)
    if not m:
        return None
    return counts(*(sum(int(x[i]) for x in m) for i in range(3)))


def add(a, b):
    return {k: a[k] + b[k] for k in a} if a else b


def _unittest(t):   # Ran 41 tests in 4.0s \n\n OK (skipped=2) | FAILED (failures=1, errors=2)   (each run, summed)
    out = None
    for m in re.finditer(r"^Ran (\d+) tests? in ", t, re.M):
        total = int(m.group(1))
        r = re.search(r"^(OK|FAILED)(?: \((.*)\))?\s*$", t[m.end():], re.M)
        if not r:
            continue
        kv = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", r.group(2) or "")}
        failed = kv.get("failures", 0) + kv.get("errors", 0) + kv.get("unexpected_successes", 0)
        skipped = kv.get("skipped", 0) + kv.get("expected_failures", 0)
        out = add(out, counts(total - failed - skipped, failed, skipped, total))
    return out


def _pytest(t):   # ===== 1 failed, 40 passed, 2 skipped in 1.20s =====   (or without the rules, with -q; each run, summed)
    out = None
    for line in re.findall(r"^=*\s*((?:\d+ [a-z]+(?:, )?)+) in [\d.]+s\b.*$", t, re.M):
        w = tally(line)
        out = add(out, counts(w.get("passed", 0) + w.get("xpassed", 0),
                              w.get("failed", 0) + w.get("error", 0) + w.get("errors", 0),
                              w.get("skipped", 0) + w.get("xfailed", 0)))
    return out


def _mocha(t):   # 40 passing (2s) \n 1 failing \n 2 pending
    p = re.findall(r"^\s*(\d+) passing\b", t, re.M)
    if not p:
        return None
    f = re.findall(r"^\s*(\d+) failing\b", t, re.M)
    s = re.findall(r"^\s*(\d+) pending\b", t, re.M)
    return counts(int(p[-1]), int(f[-1]) if f else 0, int(s[-1]) if s else 0)


def _playwright(t):   # 40 passed (1.2m) \n 1 failed \n 3 flaky \n 2 skipped
    w = tally("\n".join(re.findall(r"^\s*(\d+ (?:passed|failed|flaky|skipped|did not run))\b", t, re.M)))
    if not ("passed" in w or "failed" in w):
        return None
    return counts(w.get("passed", 0) + w.get("flaky", 0), w.get("failed", 0),
                  w.get("skipped", 0) + w.get("did not run", 0))


def _go(t):   # go test -v: --- PASS: TestX (0.00s)
    m = re.findall(r"^\s*--- (PASS|FAIL|SKIP):", t, re.M)
    if not m:
        return None
    return counts(m.count("PASS"), m.count("FAIL"), m.count("SKIP"))


def parse(text):
    t = ANSI.sub("", text or "").replace("\r", "")
    for f in (_jest, _vitest, _cargo, _unittest, _pytest, _mocha, _playwright, _go):
        r = f(t)
        if r and r["total"]:
            return r
    return None


# ---- while the output streams in ------------------------------------------------------------------
DOTS = re.compile(r"^(?:\S+\.py\s+)?([.FEsxX]+)\s*(?:\[\s*(\d+)%\])?$")   # pytest, pytest -q, unittest: one mark per test
PYTEST_END = re.compile(r"^=*\s*(?:\d+ [a-z]+(?:, )?)+ in [\d.]+s\b")
DOT_MARK = {".": "passed", "X": "passed", "F": "failed", "E": "failed", "s": "skipped", "x": "skipped"}
LINE_MARKS = [   # one test per matching line: (pattern, {group text: outcome})
    (re.compile(r"::\S.*?\s(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b"),                     # pytest -v
     {"PASSED": "passed", "XPASS": "passed", "FAILED": "failed", "ERROR": "failed", "SKIPPED": "skipped", "XFAIL": "skipped"}),
    (re.compile(r" \.\.\. (ok|FAIL|ERROR|skipped|expected failure|unexpected success)\b"),  # unittest -v
     {"ok": "passed", "FAIL": "failed", "ERROR": "failed", "unexpected success": "failed",
      "skipped": "skipped", "expected failure": "skipped"}),
    (re.compile(r"^test \S+ \.\.\. (ok|FAILED|ignored)\b"), {"ok": "passed", "FAILED": "failed", "ignored": "skipped"}),  # cargo
    (re.compile(r"^\s*--- (PASS|FAIL|SKIP):"), {"PASS": "passed", "FAIL": "failed", "SKIP": "skipped"}),               # go -v
    (re.compile(r"^\s+(✓|✘|-)\s+\d+ "), {"✓": "passed", "✘": "failed", "-": "skipped"}),                             # playwright list
]
VITEST_FILE = re.compile(r"^\s*[✓❯×]\s+\S+\s+\((\d+) tests?(?: \| (\d+) failed)?(?: \| (\d+) skipped)?\)")
EXPECTED = [re.compile(r"^collected (\d+) items?(?: / \d+ deselected / (\d+) selected)?"),   # pytest
            re.compile(r"^Running (\d+) tests? using"),                                       # playwright
            re.compile(r"^running (\d+) tests?$")]                                            # cargo, per test binary


class Progress:
    """Counts tests as a runner's output arrives.

    snapshot() gives the counts so far and the expected total, 0 when unknown. Chained runs (`pytest a && pytest b`)
    are tracked one at a time and added up: each finished run counts what it ran, and the current one counts what
    it said it would run, or for pytest -q (which never says) an estimate from its [ 42%] markers.
    """

    def __init__(self):
        self.n = {"passed": 0, "failed": 0, "skipped": 0}
        self.partial = ""
        self.before = 0     # tests run by runs that have finished
        self.said = 0       # what the current run said it will run
        self.ran = 0        # tests the current run has finished
        self.pct = 0        # the current run's latest [ 42%]

    def feed(self, data):
        text = self.partial + ANSI.sub("", data.decode(errors="replace") if isinstance(data, bytes) else data)
        lines = text.replace("\r", "\n").split("\n")
        self.partial = lines.pop()
        for line in lines:
            self._line(line)

    def _count(self, outcome, k=1):
        self.n[outcome] += k
        self.ran += k

    def _line(self, line):
        s = line.strip()
        m = DOTS.match(s)
        if m:
            for c in m.group(1):
                self._count(DOT_MARK[c])
            self.pct = int(m.group(2) or self.pct)
            return
        if PYTEST_END.match(s):   # this pytest run is over; a chained one starts afresh
            self.before += self.ran
            self.said = self.ran = self.pct = 0
            return
        for pat, outcome in LINE_MARKS:
            m = pat.search(line)
            if m:
                self._count(outcome[m.group(1)])
                pct = re.search(r"\[\s*(\d+)%\]\s*$", s)   # pytest -v ends its lines with one too
                self.pct = int(pct.group(1)) if pct else self.pct
                return
        m = VITEST_FILE.match(line)
        if m:
            total, failed, skipped = (int(x or 0) for x in m.groups())
            self._count("failed", failed)
            self._count("skipped", skipped)
            self._count("passed", total - failed - skipped)
            return
        for pat in EXPECTED:
            m = pat.match(s)
            if m:
                self.said += int(m.groups()[-1] or m.group(1))   # cargo says it once per test binary
                return

    def snapshot(self):
        n = dict(self.n)
        m = DOTS.match(self.partial.strip())   # unittest prints its dots on one line that ends only at the end
        if m:
            for c in m.group(1):
                n[DOT_MARK[c]] += 1
        out = counts(n["passed"], n["failed"], n["skipped"])
        current = self.said or (round(self.ran * 100 / self.pct) if self.pct else 0)
        known = bool(current) or self.ran == 0
        expected = self.before + current if known else 0
        out["expected"] = expected if expected >= out["total"] else 0
        out["estimated"] = bool(out["expected"]) and not self.said and bool(self.pct)
        return out
