#!/usr/bin/env bash
# Installs Matt Pocock's skills plugin, which provides the /implement command (and /tdd, /code-review, ...)
# the fleet runs in each session. Safe to re-run: an installed plugin is updated instead.
#   ./install-skills.sh
set -euo pipefail

marketplace="claude-plugins-official"
marketplace_repo="anthropics/claude-plugins-official"
plugin="mattpocock-skills@$marketplace"

command -v claude >/dev/null || { echo "claude isn't on PATH; install Claude Code first" >&2; exit 1; }

if ! claude plugin marketplace list 2>/dev/null | grep -q "$marketplace"; then
  echo "Adding marketplace $marketplace_repo"
  claude plugin marketplace add "$marketplace_repo"
else
  claude plugin marketplace update "$marketplace"
fi

if claude plugin list 2>/dev/null | grep -q "mattpocock-skills"; then
  echo "Updating $plugin"
  claude plugin update "$plugin"
else
  echo "Installing $plugin"
  claude plugin install --scope user "$plugin"
fi

echo "Done. Restart running Claude sessions to pick up the skills."
