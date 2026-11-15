#!/usr/bin/env bash
# Vercel build step: the static site is web/ plus the CoStar index in data/ (built by pipeline/build_index.py).
# data/ is licensed and git-ignored, so it reaches Vercel only through `vercel deploy` from a machine that has it.
set -euo pipefail
if [ ! -f data/index/los-angeles.json ]; then
  echo "data/index is missing: run python pipeline/build_index.py, then deploy with scripts/deploy/vercel_deploy.sh" >&2
  exit 1
fi
rm -rf public && mkdir -p public/data
cp -r web/. public/
cp -r data/index public/data/index
cp -r data/property public/data/property
cp -r data/home public/data/home
[ -d data/conversion ] && cp -r data/conversion public/data/conversion
