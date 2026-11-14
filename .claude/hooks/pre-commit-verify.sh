#!/usr/bin/env bash
# PreToolUse hook for Bash. Blocks `git commit` when scripts/verify.sh fails.
# Reads the tool call JSON on stdin; any other command passes straight through.
input="$(cat)"
if ! printf '%s' "$input" | grep -Eq '"command"[[:space:]]*:[[:space:]]*"[^"]*git([[:space:]]+-[^[:space:]]+([[:space:]]+[^-][^[:space:]]*)?)*[[:space:]]+commit'; then
  exit 0
fi
root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
if ! bash "$root/scripts/verify.sh" >&2; then
  echo "Commit blocked: scripts/verify.sh failed. Fix the problems above, then commit again." >&2
  exit 2
fi
exit 0
