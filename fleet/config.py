"""User-editable settings in ~/.config/ai-fleet/limits.toml. The panel writes the same file."""
import tomllib

from . import paths

DEFAULTS = {
    "orchestrators": 2,
    "implementors_per_orchestrator": 4,
    "summaries": "tool",  # "tool" = built from the latest tool call, "ai" = Haiku summary
    "summary_model": "haiku",
    "summary_interval_sec": 20,
    "implement_command": "/mattpocock-skills:implement",
    "merge_command": "/mattpocock-skills:resolving-merge-conflicts",
    "permission_mode": "auto",
    "model": "",  # model for fleet sessions; empty = your Claude Code default
    "fix_rounds": 3,
    "verdict_timeout_sec": 600,
    "roles": {
        # skill name (namespace stripped) -> name shown in the panel
        "tdd": "tester",
        "code-review": "reviewer",
        "resolving-merge-conflicts": "merger",
        "diagnosing-bugs": "debugger",
        "implement": "implementor",
        "research": "researcher",
    },
}


def load() -> dict:
    cfg = {**DEFAULTS, "roles": dict(DEFAULTS["roles"])}
    try:
        with open(paths.LIMITS, "rb") as f:
            user = tomllib.load(f)
    except FileNotFoundError:
        return cfg
    roles = user.pop("roles", {})
    cfg.update(user)
    cfg["roles"].update(roles)
    return cfg


def _toml(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def save(cfg: dict):
    paths.ensure()
    lines = ["# ai-fleet settings. The Fleet panel edits this file too.", ""]
    lines += [f"{k} = {_toml(v)}" for k, v in cfg.items() if k != "roles"]
    lines += ["", "# skill -> name shown in the panel", "[roles]"]
    lines += [f'"{k}" = {_toml(v)}' for k, v in cfg["roles"].items()]
    tmp = paths.LIMITS.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(paths.LIMITS)
