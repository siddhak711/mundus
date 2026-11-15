#!/usr/bin/env bash
# Blocks git commits that would credit an AI as author, committer or co-author.
# Only humans are listed as contributors in this repository.
input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')
case "$cmd" in *"git commit"*|*"git merge"*|*"git rebase"*|*"git cherry-pick"*|*"git revert"*) ;; *) exit 0 ;; esac

bad='(noreply@anthropic\.com|Co-Authored-By:[^\n]*(Claude|Anthropic)|Claude-Session:|Generated with \[?Claude)'
if printf '%s' "$cmd" | grep -qiE "$bad"; then
  echo "Blocked: the commit message credits Claude. Remove Co-Authored-By/Claude-Session/Generated-with lines; only humans are contributors here." >&2
  exit 2
fi
for v in "$(git config user.email)" "$(git config user.name)" "$GIT_AUTHOR_EMAIL" "$GIT_COMMITTER_EMAIL" "$GIT_AUTHOR_NAME" "$GIT_COMMITTER_NAME"; do
  if printf '%s' "$v" | grep -qiE '^claude$|anthropic'; then
    echo "Blocked: git identity is '$v'. Set the human owner's identity first, e.g. git config user.name 'Siddha Kanthi' && git config user.email '125705843+siddhak711@users.noreply.github.com'" >&2
    exit 2
  fi
done
exit 0
