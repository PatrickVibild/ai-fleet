#!/usr/bin/env bash
# Links ai-fleet into place. The code stays in this repo, so pulling or editing it updates the running system.
#   ./install.sh            install (safe to re-run)
#   ./install.sh --remove   undo everything this script did (your runs and settings are kept)
set -euo pipefail
repo="$(cd "$(dirname "$0")" && pwd)"

links=(
  "$repo/bin/fleet|$HOME/.local/bin/fleet"
  "$repo/systemd/ai-fleet.service|$HOME/.config/systemd/user/ai-fleet.service"
  "$repo/skill/implement-orchestrator|$HOME/.claude/skills/implement-orchestrator"
  "$repo/omarchy-plugin|$HOME/.config/omarchy/plugins/patrick.ai-fleet"
)

# The rules that tell every Claude session to register its training and to put reminders in the Todo tab.
# Each is kept between markers so it can be updated or removed.
md="$HOME/.claude/CLAUDE.md"
rules=(training todo)
strip_rule() {
  [ -f "$md" ] || return 0
  for r in "${rules[@]}"; do sed -i "/^<!-- ai-fleet:$r -->\$/,/^<!-- \\/ai-fleet:$r -->\$/d" "$md"; done
}

link() {
  local src="$1" dst="$2"
  [ -e "$src" ] || { echo "  skip  $dst (not built yet)"; return; }
  if [ -e "$dst" ] && [ ! -L "$dst" ]; then
    echo "  KEEP  $dst exists and isn't our link; move it away and re-run" >&2
    return
  fi
  mkdir -p "$(dirname "$dst")"
  ln -sfn "$src" "$dst"
  echo "  link  $dst"
}

if [ "${1:-}" = "--remove" ]; then
  systemctl --user disable --now ai-fleet.service 2>/dev/null || true
  for l in "${links[@]}"; do
    dst="${l#*|}"
    [ -L "$dst" ] && rm "$dst" && echo "  removed $dst"
  done
  strip_rule
  systemctl --user daemon-reload
  echo "Removed. Runs and settings are still in ~/.local/state/ai-fleet and ~/.config/ai-fleet."
  exit 0
fi

echo "Installing ai-fleet from $repo"
for l in "${links[@]}"; do link "${l%%|*}" "${l#*|}"; done
mkdir -p "$(dirname "$md")"
strip_rule
for r in "${rules[@]}"; do
  { echo "<!-- ai-fleet:$r -->"; cat "$repo/skill/$r-rule.md"; echo "<!-- /ai-fleet:$r -->"; } >> "$md"
done
echo "  rules $md"
command -v claude >/dev/null || echo "  WARN  claude isn't on PATH; the daemon needs it"
command -v jq >/dev/null || echo "  WARN  jq isn't installed; the statusline hook needs it"
systemctl --user daemon-reload
systemctl --user enable --now ai-fleet.service
systemctl --user restart ai-fleet.service
sleep 1
if fleet status >/dev/null 2>&1; then
  echo "Daemon is running. Try: fleet status"
  echo
  fleet phone || true
else
  echo "Daemon didn't answer; see: journalctl --user -u ai-fleet -n 50" >&2
fi
