#!/usr/bin/env bash
# Run the Census site's server.py on the VM, behind Caddy at https://<vm-host>/census. The site on Vercel (and on GitHub
# Pages) gets its data, site models, walkthrough floors and agent from here. It sits next to the agent server because
# the apartment agent reads the floor files server.py prepares (data/conversion/<scan>/).
# Run from the repository root after vm_setup.sh:  bash scripts/deploy/vm_census.sh
# Optional: CENSUS_CORS_ORIGIN=https://<user>.github.io (default: the repository owner's Pages origin).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="$HOME/.local/bin:$PATH"
set -a; . ./.env; set +a
CORS_ORIGIN="${CENSUS_CORS_ORIGIN:-https://siddhak711.github.io}"

echo "== python environment"
UV_VENV_CLEAR=1 uv venv -q --python 3.12 .venv-census
uv pip install -q --python .venv-census/bin/python -r requirements.txt scipy opencv-python-headless

echo "== index (server.py reads data/property and data/home to build site models)"
KIT="${WORLD_DATA_DIR:-$ROOT/backend/data}/kit"
[ -f "$KIT/data/commercial-property.jsonl" ] || { echo "No CoStar kit at $KIT: run vm_setup.sh first" >&2; exit 1; }
.venv-census/bin/python pipeline/build_index.py "$KIT"
.venv-census/bin/python pipeline/conversion.py
mkdir -p raw && ln -sfn "$KIT" raw/costar   # the apartment agent's market summary reads the kit here

echo "== walkthrough floors (Matterport, licensed: baked here, never committed; resumable)"
for scan in $(.venv-census/bin/python -c "import json; print(' '.join(json.load(open('web/walkthrough/floors.json'))['floors']))"); do
  .venv-census/bin/python -m pipeline.bake "$scan" || echo "bake $scan failed: rerun this script to resume" >&2
done

echo "== service"
IP="$(curl -s -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip || curl -s ifconfig.me)"
HOST="$(echo "$IP" | tr . -).sslip.io"
sed -e "s|@ROOT@|$ROOT|g" -e "s|@USER@|$USER|g" -e "s|@CORS_ORIGIN@|$CORS_ORIGIN|g" scripts/deploy/mundus-census.service \
  | sudo tee /etc/systemd/system/mundus-census.service >/dev/null
sed -e "s|@HOST@|$HOST|g" -e "s|@AGENT_TOKEN@|$AGENT_TOKEN|g" scripts/deploy/Caddyfile | sudo tee /etc/caddy/Caddyfile >/dev/null
sudo systemctl disable --now mundus-atlas 2>/dev/null || true   # the unit's former name, same port
sudo rm -f /etc/systemd/system/mundus-atlas.service
sudo systemctl daemon-reload
sudo systemctl enable --now mundus-census
sudo systemctl restart mundus-census caddy
sleep 3
curl -fsS "https://$HOST/census/api/status" && echo
echo "Census API: https://$HOST/census  (Vercel rewrites to it; for GitHub Pages set the variable CENSUS_API to it)"
