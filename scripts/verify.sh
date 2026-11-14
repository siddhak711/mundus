#!/usr/bin/env bash
# The single gate. Runs before every commit and in CI. Keep it under 60 seconds.
# Stack-specific gates (lint, typecheck, tests, layer import check) go in
# scripts/verify.d/*.sh and run in name order.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

scripts/check-work.sh --check

if [ -d scripts/verify.d ]; then
  for gate in scripts/verify.d/*.sh; do
    [ -f "$gate" ] || continue
    echo "verify: $gate"
    bash "$gate"
  done
fi

echo "verify: ok"
