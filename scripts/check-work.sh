#!/usr/bin/env bash
# Validates work/. With --board, also prints the board to stdout.
# The board is never committed: a shared generated file would conflict
# on every pair of parallel branches.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work="$root/work"
mode="${1:-}"
errors=0

fail() { echo "check-work: $1" >&2; errors=$((errors + 1)); }

# Reads one frontmatter field from a file whose first line is '---'.
field() {
  awk -v key="$2" '
    NR == 1 && $0 != "---" { exit }
    NR > 1 && $0 == "---" { exit }
    NR > 1 && index($0, key ":") == 1 {
      sub("^" key ":[ \t]*", ""); sub("[ \t]+$", ""); print; exit
    }' "$1"
}

rows=""
if [ -d "$work" ]; then
  for dir in "$work"/*/; do
    [ -d "$dir" ] || continue
    name="$(basename "$dir")"
    case "$name" in _*) continue ;; esac

    if ! [[ "$name" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
      fail "$name: directory name must be lowercase letters, digits and hyphens"
    fi
    spec="$dir/spec.md"
    if [ ! -f "$spec" ]; then
      fail "$name: missing spec.md"
      continue
    fi

    title="$(field "$spec" title)"
    status="$(field "$spec" status)"
    [ -n "$title" ] || fail "$name: spec.md frontmatter has no title"

    case "$status" in
      draft | approved) ;;
      building | shipped)
        [ -s "$dir/acceptance.md" ] || fail "$name: status $status requires a non-empty acceptance.md"
        [ -s "$dir/log.md" ] || fail "$name: status $status requires a non-empty log.md"
        ;;
      "") fail "$name: spec.md frontmatter has no status" ;;
      *) fail "$name: invalid status '$status' (allowed: draft, approved, building, shipped)" ;;
    esac

    if [ "$status" = "shipped" ] && ! grep -q '^## Verification' "$dir/log.md" 2>/dev/null; then
      fail "$name: status shipped requires a '## Verification' section in log.md"
    fi

    rows+="$(printf '%-28s %-10s %s' "$name" "${status:-?}" "${title:-?}")"$'\n'
  done
fi

if [ "$mode" = "--board" ]; then
  printf '%-28s %-10s %s\n' "WORK ITEM" "STATUS" "TITLE"
  printf '%s' "$rows"
fi

if [ "$errors" -gt 0 ]; then
  echo "check-work: $errors problem(s)" >&2
  exit 1
fi
[ "$mode" = "--board" ] || echo "check-work: ok"
