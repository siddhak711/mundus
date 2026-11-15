#!/bin/bash
# Starts the floor walkthrough on this Mac and opens it in the browser. Close this window to stop it.
cd "$(dirname "$0")"
PORT=8123
(sleep 1; open "http://localhost:$PORT") &
python3 -m http.server $PORT
