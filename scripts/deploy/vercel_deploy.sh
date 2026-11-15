#!/usr/bin/env bash
# Deploy the Atlas site to Vercel. Run from the repository root:
#   bash scripts/deploy/vercel_deploy.sh            # production
#   bash scripts/deploy/vercel_deploy.sh --preview  # preview URL only
# Only web/ is uploaded (about 50 files). The CoStar index, site models, baked walkthrough floors and every API call
# come from server.py on the VM through the rewrites in vercel.json, so set that up first: scripts/deploy/vm_atlas.sh.
set -euo pipefail
cd "$(dirname "$0")/../.."
prod="--prod"; [ "${1:-}" = "--preview" ] && prod=""
vercel deploy $prod --yes
