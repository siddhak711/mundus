#!/usr/bin/env bash
# Checks a commit subject or pull request title.
#   type(scope): subject [work-item]
# scope and [work-item] are optional. feat and fix must name a work item.
set -euo pipefail

title="${1:-}"
types='feat|fix|docs|chore|refactor|test|perf|build|ci|revert'

# Git's own generated subjects are allowed as they are.
case "$title" in "Merge "* | "Revert "*) exit 0 ;; esac

if ! [[ "$title" =~ ^($types)(\([a-z0-9-]+\))?:\ .+$ ]]; then
  echo "check-title: '$title'" >&2
  echo "check-title: expected 'type(scope): subject [work-item]', type one of: ${types//|/, }" >&2
  exit 1
fi
if [ "${#title}" -gt 72 ]; then
  echo "check-title: subject is ${#title} characters, limit is 72" >&2
  exit 1
fi
if [[ "$title" =~ ^(feat|fix) ]] && ! [[ "$title" =~ \ \[[a-z0-9][a-z0-9-]*\]$ ]]; then
  echo "check-title: feat and fix must end with the work item, for example ' [my-spec]'" >&2
  exit 1
fi
