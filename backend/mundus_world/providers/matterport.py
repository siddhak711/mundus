"""Matterport Model API (GraphQL, basic auth). Signed URLs are returned to the caller and never stored."""
from __future__ import annotations

from typing import Any

from mundus_world.config.settings import MATTERPORT_GRAPH_URL, Settings
from mundus_world.providers.http import Http, UpstreamError

Q_BASICS = """query Basics($id: ID!) { model(id: $id) {
  id name description created visibility
  address { address locality administrativeArea postalCode }
  geolocation { lat long }
  generatedDescription { summary }
  propertyClassifications { classification type }
  floors { id label } rooms { id } panoLocations { id }
  image { url }
  view(type: "matterport.model.defurnished") { id } } }"""

Q_ROOMS = """query Rooms($id: ID!) { model(id: $id) {
  floors { id label vertices { id position { x y } } edges { id type thickness vertices { id } } }
  rooms { id floor { id } classifications { label confidence } boundary { edges { id } }
    dimensions(units: metric) { areaFloor width depth height } }
  assets { floorplans(provider: "matterport") { format flags url width height resolution origin { x y } } }
  panoLocations { id label position { x y z } } } }"""

Q_PANOS = """query Panos($id: ID!) { model(id: $id) {
  panoLocations { id label position { x y z } skybox(resolution: "2k") { status children } } } }"""


class NotFound(Exception):
    pass


class Matterport:
    def __init__(self, settings: Settings, http: Http):
        self.s = settings
        self.http = http

    def _gql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        r = self.http.request("POST", MATTERPORT_GRAPH_URL, json_body={"query": query, "variables": variables},
                              auth=(self.s.matterport_key, self.s.matterport_token))
        if r.status_code >= 400:
            raise UpstreamError(r.status_code, r.text[:300])
        body = r.json()
        errs = body.get("errors") or []
        data = body.get("data") or {}
        if errs and not data.get("model"):
            codes = [((e.get("extensions") or {}).get("code") or "") for e in errs]
            if any("not.found" in c for c in codes):
                raise NotFound(str(variables))
            raise UpstreamError(200, f"graphql error: {errs[0].get('message', '')[:200]}")
        return data.get("model") or {}

    def basics(self, sid: str) -> dict[str, Any]:
        return self._gql(Q_BASICS, {"id": sid})

    def rooms(self, sid: str) -> dict[str, Any]:
        return self._gql(Q_ROOMS, {"id": sid})

    def panos(self, model_or_view_id: str) -> dict[str, Any]:
        return self._gql(Q_PANOS, {"id": model_or_view_id})

    def download(self, signed_url: str) -> bytes:
        return self.http.get_bytes(signed_url, auth_fatal=False)
