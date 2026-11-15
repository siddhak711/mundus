#!/usr/bin/env bash
# Run Atlas's server.py on the Mundus VM, behind Caddy at https://<vm-host>/atlas. The site on Vercel (and on GitHub
# Pages) gets its data, site models, walkthrough floors and agent from here. It sits next to the agent server because
# the apartment agent reads the floor files server.py prepares (data/conversion/<scan>/).
# Run from the repository root after vm_setup.sh:  bash scripts/deploy/vm_atlas.sh
# Optional: ATLAS_CORS_ORIGIN=https://<user>.github.io (default: the repository owner's Pages origin).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="$HOME/.local/bin:$PATH"
set -a; . ./.env; set +a
CORS_ORIGIN="${ATLAS_CORS_ORIGIN:-https://siddhak711.github.io}"

echo "== python environment"
UV_VENV_CLEAR=1 uv venv -q --python 3.12 .venv-atlas
uv pip install -q --python .venv-atlas/bin/python -r requirements.txt scipy opencv-python-headless

echo "== index (server.py reads data/property and data/home to build site models)"
KIT="${WORLD_DATA_DIR:-$ROOT/backend/data}/kit"
[ -f "$KIT/data/commercial-property.jsonl" ] || { echo "No CoStar kit at $KIT: run vm_setup.sh first" >&2; exit 1; }
.venv-atlas/bin/python pipeline/build_index.py "$KIT"
.venv-atlas/bin/python pipeline/conversion.py
mkdir -p raw && ln -sfn "$KIT" raw/costar   # the apartment agent's market summary reads the kit here

echo "== walkthrough floors (Matterport, licensed: baked here, never committed; resumable)"
for scan in $(.venv-atlas/bin/python -c "import json; print(' '.join(json.load(open('web/walkthrough/floors.json'))['floors']))"); do
  .venv-atlas/bin/python -m pipeline.bake "$scan" || echo "bake $scan failed: rerun this script to resume" >&2
done

echo "== service"
IP="$(curl -s -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip || curl -s ifconfig.me)"
HOST="$(echo "$IP" | tr . -).sslip.io"
sed -e "s|@ROOT@|$ROOT|g" -e "s|@USER@|$USER|g" -e "s|@CORS_ORIGIN@|$CORS_ORIGIN|g" scripts/deploy/mundus-atlas.service \
  | sudo tee /etc/systemd/system/mundus-atlas.service >/dev/null
sed -e "s|@HOST@|$HOST|g" -e "s|@AGENT_TOKEN@|$AGENT_TOKEN|g" scripts/deploy/Caddyfile | sudo tee /etc/caddy/Caddyfile >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now mundus-atlas
sudo systemctl restart mundus-atlas caddy
sleep 3
curl -fsS "https://$HOST/atlas/api/status" && echo
echo "Atlas API: https://$HOST/atlas  (Vercel rewrites to it; for GitHub Pages set the variable ATLAS_API to it)"
