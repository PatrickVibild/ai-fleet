"""Where ai-fleet keeps things. Code lives in the repo; state and config follow XDG."""
import os
from pathlib import Path

HOME = Path.home()
ROOT = Path(__file__).resolve().parent.parent

# AI_FLEET_STATE / AI_FLEET_CONFIG let a test daemon run beside the real one without touching XDG_* (which git reads too)
STATE = Path(os.environ.get("AI_FLEET_STATE") or Path(os.environ.get("XDG_STATE_HOME", HOME / ".local/state")) / "ai-fleet")
CONFIG = Path(os.environ.get("AI_FLEET_CONFIG") or Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "ai-fleet")
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
SOCK = Path(os.environ.get("AI_FLEET_SOCK") or RUNTIME / "ai-fleet.sock")

STATE_JSON = STATE / "state.json"
RUNS = STATE / "runs"
STATUSLINE = STATE / "statusline"
SUMMARY_CWD = STATE / "summarizer"
LIMITS = CONFIG / "limits.toml"
MODEL_WINDOWS = STATE / "model-windows.json"

CLAUDE_PROJECTS = HOME / ".claude/projects"
CLAUDE_PLUGINS = HOME / ".claude/plugins"
HOOK = ROOT / "hooks/fleet-hook"
STATUSLINE_HOOK = ROOT / "hooks/fleet-statusline"


def ensure():
    for p in (STATE, RUNS, STATUSLINE, SUMMARY_CWD, CONFIG):
        p.mkdir(parents=True, exist_ok=True)
