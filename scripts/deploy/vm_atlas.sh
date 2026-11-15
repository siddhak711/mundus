#!/usr/bin/env bash
# Run the Atlas site API (server.py) on the Mundus VM, behind Caddy at https://<vm-host>/atlas, for the copy of the
# site on GitHub Pages. Run from the repository root after vm_setup.sh:  bash scripts/deploy/vm_atlas.sh
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
echo "Set the repository variable ATLAS_API to https://$HOST/atlas, then rerun the Pages workflow."
