#!/usr/bin/env bash
# Deploy the Atlas site to Vercel from a machine that has the CoStar kit. Run from the repository root:
#   bash scripts/deploy/vercel_deploy.sh            # production
#   bash scripts/deploy/vercel_deploy.sh --preview  # preview URL only
# The index (data/, about 5,200 files) is licensed and git-ignored, so it goes up with the CLI, never through git.
# --archive=tgz sends one file: the Hobby plan allows 5,000 uploaded files per 24 hours.
set -euo pipefail
cd "$(dirname "$0")/../.."
[ -f data/index/los-angeles.json ] || python3 pipeline/build_index.py
prod="--prod"; [ "${1:-}" = "--preview" ] && prod=""
vercel deploy $prod --yes --archive=tgz
