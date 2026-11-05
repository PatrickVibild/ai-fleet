"""The playbooks in the panel's How-to tab: Markdown files in ~/.config/ai-fleet/howto, one sub-tab each.

The folder is seeded from the repo's howto/ the first time it's missing; after that it's yours to edit.
"""
import re
import shutil

from . import paths, skills


def docs():
    """[{name, path}] for every playbook, by file name; the name is its first `# ` heading, else the file name."""
    if not paths.HOWTO.exists() and paths.HOWTO_SEED.is_dir():
        shutil.copytree(paths.HOWTO_SEED, paths.HOWTO)
    out = []
    for p in sorted(paths.HOWTO.glob("*.md")):
        try:
            m = re.search(r"^#\s+(.+)$", p.read_text(errors="replace"), re.M)
        except OSError:
            continue
        out.append({"name": m.group(1).strip() if m else p.stem, "path": str(p)})
    return out


def listing():
    """What the How-to tab needs: the playbooks and which skill names are installed."""
    return {"dir": str(paths.HOWTO), "docs": docs(), "skills": sorted(skills.installed())}
