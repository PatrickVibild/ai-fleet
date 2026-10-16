"""Whether a slash command a fleet prompt starts with (implement_command, merge_command) is installed.

Claude Code prints "Unknown command" for a missing one and the session sits idle, so we look before using it.
"""
import json
from pathlib import Path

from . import paths


def _plugin_names(install):
    """Skill and command names one installed plugin provides."""
    root = Path(install)
    dirs, files = [root / "skills"], [root / "commands"]
    try:
        manifest = json.loads((root / ".claude-plugin/plugin.json").read_text())
    except (OSError, json.JSONDecodeError):
        manifest = {}
    for key, out in (("skills", dirs), ("commands", files)):
        v = manifest.get(key) or []
        out += [root / p for p in ([v] if isinstance(v, str) else v)]
    names = set()
    for d in dirs:
        if (d / "SKILL.md").is_file():
            names.add(d.name)
        names |= {p.parent.name for p in d.glob("*/SKILL.md")}
    for c in files:
        if c.suffix == ".md" and c.is_file():
            names.add(c.stem)
        names |= {p.stem for p in c.glob("*.md")}
    return names


def _installed():
    """{plugin name: (version, skill names)} for every installed plugin."""
    try:
        d = json.loads((paths.CLAUDE_PLUGINS / "installed_plugins.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for key, installs in (d.get("plugins") or {}).items():
        name = key.split("@")[0]
        for i in installs or []:
            ver, names = out.get(name, ("", set()))
            out[name] = (i.get("version") or ver, names | _plugin_names(i.get("installPath") or ""))
    return out


def missing(command, repo=None):
    """None if `command` (like "/plugin:skill") is installed or empty, else a sentence saying what's missing."""
    if not command or not command.strip():
        return None
    name = command.strip().split()[0].lstrip("/")
    plugins = _installed()
    if ":" in name:
        plugin, skill = name.split(":", 1)
        if plugin not in plugins:
            return f"`/{name}`: the {plugin} plugin isn't installed"
        ver, names = plugins[plugin]
        if skill not in names:
            return f"`/{name}`: {plugin} {ver} has no skill or command named {skill}"
        return None
    for base in [paths.HOME / ".claude"] + ([Path(repo) / ".claude"] if repo else []):
        if (base / "skills" / name / "SKILL.md").is_file() or (base / "commands" / f"{name}.md").is_file():
            return None
    if any(name in names for _, names in plugins.values()):
        return None
    return f"`/{name}` isn't an installed skill or command"
