"""Pass/fail counts read from a test runner's output (pytest, unittest, jest, vitest, playwright, mocha, cargo, go -v).

parse() returns {"passed", "failed", "skipped", "total"} from the runner's summary, or None when the output
has no summary we recognise (it isn't a test run, or it was cut off before the end).
"""
import re

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
WORDS = re.compile(r"(\d+) ([a-z]+(?: not run)?)")


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


def _unittest(t):   # Ran 41 tests in 4.0s \n\n OK (skipped=2) | FAILED (failures=1, errors=2)
    m = list(re.finditer(r"^Ran (\d+) tests? in ", t, re.M))
    if not m:
        return None
    total = int(m[-1].group(1))
    r = re.search(r"^(OK|FAILED)(?: \((.*)\))?\s*$", t[m[-1].end():], re.M)
    if not r:
        return None
    kv = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", r.group(2) or "")}
    failed = kv.get("failures", 0) + kv.get("errors", 0) + kv.get("unexpected_successes", 0)
    skipped = kv.get("skipped", 0) + kv.get("expected_failures", 0)
    return counts(total - failed - skipped, failed, skipped, total)


def _pytest(t):   # ===== 1 failed, 40 passed, 2 skipped in 1.20s =====   (or the same without the rules, with -q)
    m = re.findall(r"^=*\s*((?:\d+ [a-z]+(?:, )?)+) in [\d.]+s\b.*$", t, re.M)
    if not m:
        return None
    w = tally(m[-1])
    return counts(w.get("passed", 0) + w.get("xpassed", 0),
                  w.get("failed", 0) + w.get("error", 0) + w.get("errors", 0),
                  w.get("skipped", 0) + w.get("xfailed", 0))


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
