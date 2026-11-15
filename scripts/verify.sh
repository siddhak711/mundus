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
# Census scripts: the site's venv when it exists (the daylight tests need numpy and scipy and skip without them)
site_py="$ROOT/.venv/bin/python"; [ -x "$site_py" ] || site_py=python3
(cd "$ROOT" && run "pipeline tests" "$site_py" -m unittest -q pipeline.test_conversion pipeline.test_daylight)
echo "verify: ok"
