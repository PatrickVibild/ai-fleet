"""The account's usage windows straight from Anthropic, the same numbers Claude Code's /usage shows.

Statusline input only changes when a session makes a request, and a long-running session keeps the plan it
started with, so after a plan change it can report old numbers for hours. This asks the source instead.
"""
import asyncio
import json
import time
import urllib.request
from datetime import datetime

from . import paths

URL = "https://api.anthropic.com/api/oauth/usage"


def _token():
    """Claude Code's OAuth access token, or None if there isn't a current one. We never refresh it ourselves:
    the CLI owns that file."""
    try:
        oauth = json.loads((paths.HOME / ".claude/.credentials.json").read_text())["claudeAiOauth"]
    except (OSError, ValueError, KeyError):
        return None
    if (oauth.get("expiresAt") or 0) / 1000 < time.time():
        return None
    return oauth.get("accessToken")


def parse(d):
    """{five_hour: {used, resetsAt}, seven_day: {...}} from the endpoint's reply."""
    out = {}
    for k in ("five_hour", "seven_day"):
        w = d.get(k) or {}
        if w.get("utilization") is None:
            continue
        try:
            reset = datetime.fromisoformat(w["resets_at"]).timestamp() if w.get("resets_at") else None
        except ValueError:
            reset = None
        out[k] = {"used": round(w["utilization"]), "resetsAt": reset}
    return out


def _fetch():
    tok = _token()
    if not tok:
        return None
    req = urllib.request.Request(URL, headers={"Authorization": f"Bearer {tok}", "anthropic-beta": "oauth-2025-04-20"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return parse(json.loads(r.read())) or None
    except (OSError, ValueError):
        return None


async def usage():
    """Usage windows, or None when there's no login to ask with or the request fails."""
    return await asyncio.to_thread(_fetch)
