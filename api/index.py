"""Vercel entry point: every /api/* request lands here (see vercel.json) and runs server.py's handler.

Static files (web/ and the CoStar index under data/) are served by Vercel's CDN from the build output, and
built site models go to Vercel Blob (pipeline/storage.py), so this function only answers the API routes.
"""
import os
import sys
from typing import ClassVar
from urllib.parse import parse_qs, urlencode, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import Handler


class handler(Handler):
    # Built models never change, so the CDN may keep them. /api/scan is left out: it carries signed photo
    # links that expire.
    cache_rules: ClassVar[dict] = {"/api/twin": "public, max-age=300, s-maxage=86400",
                   "/api/oblique": "public, max-age=3600, s-maxage=604800"}

    def parse_request(self):
        ok = super().parse_request()
        # vercel.json rewrites /api/<route> to /api/index?__route=<route>; put the original path back
        url = urlparse(self.path)
        query = parse_qs(url.query)
        route = query.pop("__route", [None])[0]
        if route is not None:
            rest = urlencode({k: v[0] for k, v in query.items()})
            self.path = f"/api/{route}" + (f"?{rest}" if rest else "")
        return ok
