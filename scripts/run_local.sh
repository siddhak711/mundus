#!/usr/bin/env bash
# One command to run the Atlas site on this machine and open it in the browser.
#   bash scripts/run_local.sh          # http://localhost:5190
# Needs python3 and a .env in the repository root with VEXCEL_API_KEY, MATTERPORT_API_KEY,
# MATTERPORT_API_TOKEN, COSTAR_KIT_URL and COSTAR_ZIP_PASSWORD. Every step skips work already done.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${1:-5190}"

[ -f .env ] || { echo "No .env in $(pwd). Copy .env.example to .env and fill in the keys."; exit 1; }

if [ ! -x .venv/bin/python ]; then
  echo "== creating .venv"
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -q --disable-pip-version-check requests shapely pillow numpy scipy tifffile imagecodecs matplotlib

if [ ! -f raw/costar/data/commercial-property.jsonl ]; then
  echo "== downloading the CoStar kit"
  .venv/bin/python - <<'EOF'
import os, sys, zipfile
sys.path.insert(0, ".")
from pipeline import config  # loads .env into the environment
import requests

url, pw = os.environ.get("COSTAR_KIT_URL"), os.environ.get("COSTAR_ZIP_PASSWORD")
if not url or not pw:
    sys.exit("COSTAR_KIT_URL and COSTAR_ZIP_PASSWORD must be set in .env")
os.makedirs("raw", exist_ok=True)
zpath = "raw/kit.zip"
with requests.get(url, stream=True, timeout=120) as r:
    r.raise_for_status()
    with open(zpath, "wb") as fh:
        for chunk in r.iter_content(1 << 20):
            fh.write(chunk)
dest = os.path.realpath("raw/costar")
with zipfile.ZipFile(zpath) as z:
    for info in z.infolist():
        target = os.path.realpath(os.path.join(dest, info.filename))
        if not (target == dest or target.startswith(dest + os.sep)):
            sys.exit(f"unsafe path in kit zip: {info.filename}")
        z.extract(info, dest, pwd=pw.encode())
os.remove(zpath)
EOF
fi

if [ ! -f data/index/los-angeles.json ]; then
  echo "== building the property index"
  .venv/bin/python pipeline/build_index.py raw/costar
fi
if [ ! -f data/conversion/los-angeles.json ]; then
  echo "== screening LA offices for housing conversion"
  .venv/bin/python pipeline/conversion.py
fi
# apartment layout for the floor walkthrough, once its scan (web/walkthrough/data) is linked in
WD=web/walkthrough/data
if [ -f "$WD/scene.json" ] && [ -f "$WD/shell.json" ] && [ ! -f "$WD/layout.json" ]; then
  echo "== drawing the floor 16 apartment layout (about 2 minutes)"
  if .venv/bin/python scripts/apartment_study_v4.py --data "$WD" --out "$WD/studies/v4" > "$WD/studies-v4.log" 2>&1; then
    .venv/bin/python scripts/layout_for_viewer.py "$WD/studies/v4/layout-v4.json" "$WD/layout.json"
  else
    echo "WARNING: apartment layout failed, see $WD/studies-v4.log; the walkthrough works without it"
  fi
fi

URL="http://localhost:$PORT"
( sleep 2
  if command -v open >/dev/null; then open "$URL"
  elif command -v xdg-open >/dev/null; then xdg-open "$URL" >/dev/null 2>&1
  fi ) &
echo "== Atlas at $URL (Ctrl+C to stop)"
exec .venv/bin/python server.py "$PORT"
