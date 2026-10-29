"""Pushes to your phone through ntfy (https://ntfy.sh). The topic is the only secret: anyone who knows it reads the pushes."""
import json
import secrets
import threading
import urllib.request

PRIORITY = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5}
MAX_BODY = 200
TIMEOUT = 10


def new_topic():
    """Long and random, since knowing the topic is all it takes to read it. ntfy allows [-_A-Za-z0-9]{1,64}."""
    return "ai-fleet-" + secrets.token_urlsafe(24)


def send(server, topic, title, body, priority="default", timeout=None):
    """POST one message. Raises on any failure (network, bad server, non-2xx)."""
    if len(body) > MAX_BODY:
        body = body[:MAX_BODY - 1] + "…"
    msg = {"topic": topic, "title": title, "message": body, "priority": PRIORITY[priority]}
    req = urllib.request.Request(server.rstrip("/") + "/", data=json.dumps(msg).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout or TIMEOUT) as r:
        r.read()


def push(cfg, title, body, priority="default"):
    """Send in a background thread so no daemon loop waits on the network. A failure is logged (to the journal)
    and dropped, never retried. Does nothing while `ntfy_topic` is empty. Returns the thread, or None."""
    server, topic = cfg["ntfy_server"], cfg.get("ntfy_topic")
    if not topic:
        return None

    def run():
        try:
            send(server, topic, title, body, priority)
        except Exception as e:
            print(f"[phone] push failed: {type(e).__name__}: {e}", flush=True)
    th = threading.Thread(target=run, name="phone-push", daemon=True)
    th.start()
    return th
