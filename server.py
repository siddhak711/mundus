"""Local server: static files, the on-demand site-model API, and the agent.

    python server.py            # http://localhost:5190
"""
import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from pipeline import config, matterport, twin, vexcel

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5190
STATIC_ROOTS = {"/data/": config.DATA, "/cache/": config.CACHE}


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        clean = urlparse(path).path
        for prefix, root in STATIC_ROOTS.items():
            if clean.startswith(prefix):
                target = (root / clean[len(prefix):]).resolve()
                return str(target if root.resolve() in target.parents else root)
        target = (config.WEB / clean.lstrip("/")).resolve()
        return str(target if target == config.WEB.resolve() or config.WEB.resolve() in target.parents else config.WEB)

    def end_headers(self):
        if self.path.startswith(("/cache/", "/data/")):
            self.send_header("Cache-Control", "max-age=3600")
        else:
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_oblique(self, kind, item_id, direction):
        """Angled aerial photo of the property, cached on disk. 404 when that direction was not flown."""
        if direction not in ("north", "east", "south", "west"):
            return self.send_json({"error": "Unknown direction"}, 400)
        path = config.CACHE / "twin" / f"{kind}-{item_id}" / f"oblique-{direction}.jpg"
        if not path.exists():
            detail = twin.load_detail(kind, item_id)
            half = 45 if kind == "home" else 70
            image = vexcel.oblique(vexcel.square(detail["lat"], detail["lon"], half), direction, buffer_m=0)
            if not image:
                return self.send_json({"error": "No view from this direction"}, 404)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(image)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/api/twin":
                return self.send_json(twin.get(query.get("kind", "commercial"), int(query["id"])))
            if url.path == "/api/scan":
                return self.send_json(matterport.assets(query["id"]))
            if url.path == "/api/oblique":
                return self.send_oblique(query.get("kind", "commercial"), int(query["id"]), query.get("direction", "north"))
            if url.path == "/api/status":
                return self.send_json({"agent": bool(config.ANTHROPIC_API_KEY)})
        except FileNotFoundError as error:
            return self.send_json({"error": str(error)}, 404)
        except Exception as error:  # surface upstream API failures to the page instead of a blank 500
            return self.send_json({"error": str(error)}, 502)
        return super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/api/agent":
            return self.send_json({"error": "Not found"}, 404)
        from pipeline import agent  # imported late so the site works without the Anthropic SDK
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            for event in agent.run(body.get("messages", []), body.get("context", {})):
                self.wfile.write(f"data: {json.dumps(event)}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


if __name__ == "__main__":
    print(f"Serving on http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
