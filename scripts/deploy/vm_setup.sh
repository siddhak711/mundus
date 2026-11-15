#!/usr/bin/env bash
# One-time setup of the Mundus VM (Ubuntu 24.04). Run from the repository root:  bash scripts/deploy/vm_setup.sh
# It asks for the keys once, writes .env (never committed), installs everything, ingests the 15 places,
# and starts the World API, the agent server and the Atlas site behind HTTPS.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

ask() { # ask VAR "prompt" [default]
  local var="$1" prompt="$2" def="${3:-}" val=""
  if grep -q "^${var}=." .env 2>/dev/null; then return; fi
  read -r -s -p "$prompt: " val; echo
  val="${val:-$def}"
  sed -i "/^${var}=/d" .env 2>/dev/null || true
  printf "%s='%s'\n" "$var" "$val" >> .env
}

touch .env && chmod 600 .env
# .env is sourced as shell further down, so values must be quoted: a signed download URL contains "&".
sed -i -E "s/^([A-Za-z_]+)=([^'\"].*)\$/\\1='\\2'/" .env
echo "Enter the keys (input is hidden). Press Enter to skip an optional one."
ask MATTERPORT_API_KEY   "Matterport API key"
ask MATTERPORT_API_TOKEN "Matterport API token"
ask VEXCEL_API_KEY       "Vexcel API key"
ask COSTAR_KIT_URL       "CoStar kit download URL"
ask COSTAR_ZIP_PASSWORD  "CoStar kit zip password"
ask ANTHROPIC_API_KEY    "Anthropic API key"
ask LANGSMITH_API_KEY    "LangSmith API key (optional)"
grep -q '^WORLD_API_TOKEN=.'   .env || echo "WORLD_API_TOKEN=$(openssl rand -hex 16)"   >> .env
grep -q '^WORLD_ADMIN_TOKEN=.' .env || echo "WORLD_ADMIN_TOKEN=$(openssl rand -hex 16)" >> .env
grep -q '^AGENT_TOKEN=.'       .env || echo "AGENT_TOKEN=$(openssl rand -hex 16)"       >> .env
grep -q '^WORLD_DATA_DIR='     .env || echo "WORLD_DATA_DIR=$ROOT/backend/data" >> .env
grep -q '^WORLD_REST_URL='     .env || echo "WORLD_REST_URL=http://127.0.0.1:8000" >> .env
grep -q '^CORS_ORIGINS='       .env || echo "CORS_ORIGINS=*" >> .env
if grep -q '^LANGSMITH_API_KEY=.' .env; then   # traces for the agent server, captions and eval go to LangSmith
  grep -q '^LANGSMITH_TRACING=' .env || echo "LANGSMITH_TRACING=true" >> .env
  grep -q '^LANGSMITH_PROJECT=' .env || echo "LANGSMITH_PROJECT=mundus" >> .env
fi

echo "== system packages"
sudo apt-get update -qq
sudo apt-get install -y -qq curl ca-certificates zstd debian-keyring debian-archive-keyring apt-transport-https
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -qq && sudo apt-get install -y -qq caddy
fi

echo "== python environments"
export UV_VENV_CLEAR=1   # a rerun replaces the environments instead of stopping on the existing ones
(cd backend && uv venv -q --python 3.12 .venv && uv pip install -q -e ".[embed]")
(cd harness && uv venv -q --python 3.12 .venv && uv pip install -q -e ".[serve]")
(cd eval    && uv venv -q --python 3.12 .venv && uv pip install -q -e .)
# the Atlas site (server.py, pipeline/) has no pyproject: its packages are listed in the README
uv venv -q --python 3.12 .venv && uv pip install -q -p .venv requests shapely pillow numpy tifffile imagecodecs

echo "== ingestion (15 places; resumable: rerun this script if it stops)"
set -a; . ./.env; set +a
backend/.venv/bin/mundus ingest all --workers 16

echo "== site index (every property in the kit, for the Atlas site)"
# ingestion has already downloaded and unzipped the CoStar kit; the site reads the same files
KIT="$WORLD_DATA_DIR/kit"
if [ -f "$KIT/schemas/enums.json" ] && .venv/bin/python pipeline/build_index.py "$KIT"; then
  echo "site index built"
else
  echo "WARNING: site index not built from $KIT. The site will show no properties until"
  echo "         .venv/bin/python pipeline/build_index.py <kit folder>  succeeds."
fi

echo "== services"
IP="$(curl -s -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip || curl -s ifconfig.me)"
HOST="$(echo "$IP" | tr . -).sslip.io"
sed -e "s|@ROOT@|$ROOT|g" -e "s|@USER@|$USER|g" scripts/deploy/mundus-world.service   | sudo tee /etc/systemd/system/mundus-world.service >/dev/null
sed -e "s|@ROOT@|$ROOT|g" -e "s|@USER@|$USER|g" scripts/deploy/mundus-harness.service | sudo tee /etc/systemd/system/mundus-harness.service >/dev/null
sed -e "s|@ROOT@|$ROOT|g" -e "s|@USER@|$USER|g" scripts/deploy/mundus-site.service    | sudo tee /etc/systemd/system/mundus-site.service >/dev/null
sed -e "s|@HOST@|$HOST|g" -e "s|@AGENT_TOKEN@|$AGENT_TOKEN|g" scripts/deploy/Caddyfile | sudo tee /etc/caddy/Caddyfile >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now mundus-world mundus-harness mundus-site
sudo systemctl restart mundus-world mundus-harness mundus-site   # pick up new code on a rerun
sudo systemctl restart caddy
sleep 5
curl -fsS "http://127.0.0.1:8000/healthz" && echo
curl -fsS "http://127.0.0.1:5190/api/status" && echo

cat <<MSG

Mundus is up.
  Atlas site:        https://$HOST/           public, no login (Ask Atlas uses the agent server from inside the VM)
  World API (REST):  https://$HOST/v1        header  Authorization: Bearer <WORLD_API_TOKEN>
  World API (MCP):   https://$HOST/mcp/
  Agent server:      https://$HOST/agent     header  X-Agent-Token: <AGENT_TOKEN>
  Tokens are in $ROOT/.env (WORLD_API_TOKEN, WORLD_ADMIN_TOKEN, AGENT_TOKEN). Give the first and third to the frontend.
  Snapshot for a laptop fallback:   backend/.venv/bin/mundus snapshot --out world.tar.zst
MSG
