#!/usr/bin/env bash
# A branch may change at most one work item. Two branches that never share
# a work item cannot conflict inside work/.
#   scripts/check-pr-scope.sh <base-ref>     e.g. origin/main
set -euo pipefail

base="${1:-origin/main}"
items="$(git diff --name-only "$base"...HEAD -- work/ | awk -F/ 'NF > 2 && $2 !~ /^_/ { print $2 }' | sort -u)"
count="$(printf '%s' "$items" | grep -c . || true)"

if [ "$count" -gt 1 ]; then
  echo "check-pr-scope: this branch changes $count work items; the limit is one:" >&2
  printf '%s\n' "$items" | sed 's/^/  /' >&2
  exit 1
fi
echo "check-pr-scope: ok"
