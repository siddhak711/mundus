"""Vexcel API. The key goes in the X-API-KEY header only (never in a URL)."""
from __future__ import annotations

import math
from typing import Any

from mundus_world.config.settings import VEXCEL_BASE_URL, Settings
from mundus_world.providers.http import Http, UpstreamError

OBLIQUE_KINDS = ("oblique-n", "oblique-s", "oblique-e", "oblique-w")
_OBLIQUE_PRODUCT = {"oblique-n": "oblique-north", "oblique-s": "oblique-south",
                    "oblique-e": "oblique-east", "oblique-w": "oblique-west"}


def square_wkt(lat: float, lon: float, half_m: float) -> str:
    dlat = half_m / 111320.0
    dlon = half_m / (111320.0 * math.cos(math.radians(lat)))
    pts = [(lon - dlon, lat - dlat), (lon + dlon, lat - dlat), (lon + dlon, lat + dlat), (lon - dlon, lat + dlat),
           (lon - dlon, lat - dlat)]
    return "POLYGON((" + ",".join(f"{x:.7f} {y:.7f}" for x, y in pts) + "))"


class Vexcel:
    def __init__(self, settings: Settings, http: Http):
        self.s = settings
        self.http = http

    @property
    def _h(self) -> dict[str, str]:
        return {"X-API-KEY": self.s.vexcel_key}

    def property_at(self, wkt: str) -> dict[str, Any] | None:
        """Parcels (GeoJSON features) with their structures. None when Vexcel has no parcel there (HTTP 404)."""
        r = self.http.request("GET", f"{VEXCEL_BASE_URL}/property/extract", params={"wkt": wkt, "srid": 4326},
                              headers=self._h)
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise UpstreamError(r.status_code, r.text[:200])
        return r.json()

    def ortho(self, lat: float, lon: float, size_m: int) -> bytes:
        zoom = 21 if size_m <= 120 else 20 if size_m <= 300 else 19
        r = self.http.request("GET", f"{VEXCEL_BASE_URL}/ortho/extract", headers=self._h, params={
            "layer": "urban", "bbox-dimensions": f"{size_m},{size_m}", "zoom": zoom,
            "wkt": f"POINT({lon} {lat})", "srid": 4326})
        if r.status_code >= 400 or not r.headers.get("content-type", "").startswith("image"):
            raise UpstreamError(r.status_code, r.text[:200])
        return r.content

    def oblique(self, bbox_wkt: str, kind: str) -> bytes:
        r = self.http.request("GET", f"{VEXCEL_BASE_URL}/oriented/extract", headers=self._h, params={
            "layer": "urban", "buffer-meter": 28, "wkt": bbox_wkt, "product-type": _OBLIQUE_PRODUCT[kind],
            "crop": "bounding_box", "rotation": "natural", "srid": 4326})
        if r.status_code >= 400 or not r.headers.get("content-type", "").startswith("image"):
            raise UpstreamError(r.status_code, r.text[:200])
        return r.content

    def semantic_search(self, text: str, lat: float, lon: float, radius_m: int, limit: int) -> dict[str, Any]:
        r = self.http.request("GET", f"{VEXCEL_BASE_URL}/embedding/extract", headers=self._h, timeout=20, params={
            "search-text": text, "layer": "urban", "wkt": f"POINT({lon} {lat})", "buffer-meter": radius_m,
            "total-records": limit, "page-size": limit, "page": 1})
        if r.status_code >= 400:
            raise UpstreamError(r.status_code, r.text[:200])
        return r.json()
