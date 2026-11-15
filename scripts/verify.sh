#!/usr/bin/env bash
# The single gate: lint and tests for every component. Must stay under 60 seconds.
set -euo pipefail
export LANGSMITH_TRACING=false   # tests use fake models: keep them out of LangSmith
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
run() { echo "== $1"; shift; "$@"; }
for comp in backend harness eval; do
  dir="$ROOT/$comp"
  [ -f "$dir/pyproject.toml" ] || continue
  py="$dir/.venv/bin/python"
  if [ ! -x "$py" ]; then (cd "$dir" && uv venv -q .venv && uv pip install -q -e ".[dev]"); fi
  (cd "$dir" && run "$comp lint" "$py" -m ruff check . && run "$comp tests" "$py" -m pytest -q)
done
echo "verify: ok"
