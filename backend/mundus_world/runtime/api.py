"""FastAPI app: REST World API, admin routes, and the MCP server mounted at /mcp."""
from __future__ import annotations

import contextlib
import contextvars
import json
import time
from typing import Any
from urllib.parse import parse_qs

from fastapi import Body, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from mundus_world.config.settings import Settings
from mundus_world.runtime.container import Container, build
from mundus_world.runtime.tools import Ops
from mundus_world.types.errors import ApiError

RUN_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("run_id", default=None)
CALLER: contextvars.ContextVar[str | None] = contextvars.ContextVar("caller", default=None)


class AuthAndContext:
    """Pure ASGI middleware: bearer token check, admin token check, run id and caller from headers."""

    def __init__(self, app, settings: Settings):
        self.app, self.s = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        path = scope.get("path", "")
        RUN_ID.set(headers.get("x-run-id"))
        CALLER.set(headers.get("x-caller") or ("mcp" if path.startswith("/mcp") else "rest"))
        if scope.get("method") == "OPTIONS" or path in ("/healthz", "/docs", "/openapi.json"):
            return await self.app(scope, receive, send)
        token = None
        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        if token is None:
            token = (parse_qs(scope.get("query_string", b"").decode()).get("token") or [None])[0]
        if path.startswith("/v1/admin"):
            if not self.s.admin_token or token != self.s.admin_token:
                return await _deny(send, "Admin token required")
        elif self.s.api_token and token not in (self.s.api_token, self.s.admin_token or None):
            return await _deny(send, "Missing or wrong API token")
        return await self.app(scope, receive, send)


async def _deny(send, message: str) -> None:
    body = json.dumps({"error": {"code": "unauthorized", "message": message, "details": {}}}).encode()
    await send({"type": "http.response.start", "status": 401,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def create_app(container: Container | None = None) -> FastAPI:
    c = container or build()
    ops = Ops(c)
    from mundus_world.runtime.mcp_server import build_mcp

    mcp = build_mcp(c, ops, RUN_ID, CALLER)
    mcp_app = mcp.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True,
                                      host="0.0.0.0", transport_security=_no_rebind_check())

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="Mundus World API", version="1.0", lifespan=lifespan)
    app.state.container = c

    @app.exception_handler(ApiError)
    async def api_error(_req: Request, e: ApiError):
        return JSONResponse(e.body(), status_code=e.status)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        t0 = time.perf_counter()
        resp = await call_next(request)
        route = request.scope.get("route")
        op = getattr(route, "name", None)
        if op and op not in ("healthz", "stats") and not request.url.path.startswith("/mcp"):
            c.world.log(op, (time.perf_counter() - t0) * 1000, CALLER.get(), RUN_ID.get(), resp.status_code,
                        int(resp.headers.get("content-length") or 0))
        return resp

    # ---- health and stats -------------------------------------------------
    @app.get("/healthz", name="healthz")
    def healthz():
        return {"ok": True, "db": True, "deep_places": c.db.scalar("SELECT count(*) FROM place WHERE is_deep=1")}

    @app.get("/v1/stats", name="stats")
    def stats(run_id: str | None = None):
        return c.world.stats(run_id)

    # ---- places -------------------------------------------------------------
    @app.get("/v1/places/search", name="search_places")
    def search_places(q: str | None = None, lat: float | None = None, lon: float | None = None,
                      radius_m: float = 1000, type: str | None = None, has_interior: bool = False,
                      has_listing: bool = False, deep_only: bool = False, limit: int = 20, cursor: str | None = None):
        near = {"lat": lat, "lon": lon, "radius_m": radius_m} if lat is not None and lon is not None else None
        return ops.search_places(q, near, {"type": type, "has_interior": has_interior, "has_listing": has_listing,
                                           "deep_only": deep_only}, limit, cursor)

    @app.get("/v1/places/{place_id}", name="get_place")
    def get_place(place_id: str):
        return ops.get_place(place_id)

    @app.get("/v1/places/{place_id}/card", name="card", response_class=PlainTextResponse)
    def card(place_id: str):
        return ops.card(place_id)

    @app.get("/v1/places/{place_id}/claims", name="get_claims")
    def place_claims(place_id: str, status: str = "active", predicate_prefix: str | None = None):
        return ops.get_claims(place_id, predicate_prefix, status)

    @app.get("/v1/places/{place_id}/aerial", name="aerial_image")
    @app.get("/places/{place_id}/aerial", name="aerial_image", include_in_schema=False)
    def aerial_image(place_id: str, kind: str = "ortho", size_m: int | None = None):
        path, evid, sha = c.world.aerial_image(place_id, kind, size_m)
        return FileResponse(path, media_type="image/jpeg", headers=_img_headers(evid, sha))

    @app.get("/v1/aerial/{place_id}", name="get_aerial_facts")
    def aerial_facts(place_id: str):
        return ops.get_aerial_facts(place_id)

    @app.post("/v1/aerial/search", name="aerial_semantic_search")
    def aerial_search(body: dict = Body(...)):
        return ops.aerial_semantic_search(body.get("text", ""), body.get("near"), body.get("radius_m", 1000),
                                          body.get("limit", 10), body.get("lat"), body.get("lon"))

    # ---- spaces, rooms, panos -------------------------------------------------
    @app.get("/v1/spaces/{space_id}", name="get_space")
    def get_space(space_id: str):
        return ops.get_space(space_id)

    @app.get("/v1/spaces/{space_id}/preview", name="space_preview")
    def space_preview(space_id: str):
        return FileResponse(c.world.preview_image(space_id), media_type="image/jpeg")

    @app.get("/v1/rooms/{room_id}", name="get_room")
    def get_room(room_id: str):
        return ops.get_room(room_id)

    @app.get("/v1/panos/{pano_id}", name="get_pano")
    def get_pano(pano_id: str):
        return ops.get_pano(pano_id)

    @app.get("/v1/panos/{pano_id}/faces/{face}", name="pano_image")
    @app.get("/panos/{pano_id}/faces/{face}", name="pano_image", include_in_schema=False)
    def pano_face(pano_id: str, face: int, defurnished: int = 0, size: str = "2k"):
        path, evid, sha = c.world.pano_image(pano_id, face, bool(defurnished), size)
        return FileResponse(path, media_type="image/jpeg", headers=_img_headers(evid, sha))

    @app.get("/v1/panos/{pano_id}/image", name="pano_image")
    def pano_image(pano_id: str, face: int = 1, defurnished: bool = False, size: str = "2k"):
        path, evid, sha = c.world.pano_image(pano_id, face, defurnished, size)
        return FileResponse(path, media_type="image/jpeg", headers=_img_headers(evid, sha))

    @app.get("/v1/floorplans/{plan_id}/image", name="floorplan_image")
    def floorplan_image(plan_id: str):
        path, evid = c.world.floorplan_image(plan_id)
        return FileResponse(path, media_type="image/jpeg", headers={"X-Evidence-Id": evid})

    @app.post("/v1/interiors/search", name="search_interiors")
    def search_interiors(body: dict = Body(...)):
        return ops.search_interiors(body.get("text", ""), body.get("place_id"), body.get("near"), body.get("kinds"),
                                    body.get("limit", 10))

    # ---- market -------------------------------------------------------------
    @app.get("/v1/market/schema", name="describe_market")
    def market_schema(table: str | None = None, full: bool = False):
        from mundus_world.service import market
        return market.describe(c.db) if full else ops.describe_market(table)

    @app.post("/v1/market/query", name="query_market")
    def market_query(body: dict = Body(...)):
        return ops.query_market(body.get("sql", ""), body.get("limit", 50))

    @app.get("/v1/market/records/{node_id}", name="get_record")
    def market_record(node_id: str):
        return c.world.get_record(node_id)

    # ---- graph, claims, evidence ----------------------------------------------
    @app.get("/v1/graph/neighbors", name="get_neighbors")
    def neighbors(node_id: str, rel: str | None = None, depth: int = 1, limit: int = 50):
        return ops.get_neighbors(node_id, rel, depth, limit)

    @app.get("/v1/claims", name="get_claims")
    def claims(subject_id: str, predicate_prefix: str | None = None, status: str = "active"):
        return ops.get_claims(subject_id, predicate_prefix, status)

    @app.get("/v1/claims/places", name="claim_places")
    def claim_places():
        return {"places": c.claims.places_with_claims()}

    @app.get("/v1/claims/{claim_id}", name="get_claim")
    def claim_one(claim_id: str):
        return c.claims.one(claim_id)

    @app.post("/v1/claims", name="put_claim")
    def put_claim(body: dict = Body(...)):
        return _put(body, body.get("subject_id"))

    @app.post("/v1/places/{place_id}/claims", name="put_claim")
    def put_place_claim(place_id: str, body: dict = Body(...)):
        return _put(body, body.get("subject_id") or place_id)

    def _put(body: dict, subject: str | None) -> dict[str, Any]:
        for k in ("predicate", "statement"):
            if not body.get(k):
                raise ApiError("invalid_argument", f"{k} is required")
        if not subject:
            raise ApiError("invalid_argument", "subject_id is required")
        return ops.put_claim(subject, body["predicate"], body.get("value"), body["statement"], body.get("evidence_ids"),
                             body.get("confidence", 0.5), body.get("unit"), body.get("derived_from"),
                             body.get("created_by") or CALLER.get(), body.get("run_id") or RUN_ID.get())

    @app.post("/v1/claims/{claim_id}/invalidate", name="invalidate_claim")
    def invalidate_claim(claim_id: str, body: dict = Body(default={})):
        return ops.invalidate_claim(claim_id, body.get("reason", ""), body.get("superseded_by"))

    @app.get("/v1/evidence/{ev_id}", name="get_evidence")
    def evidence(ev_id: str):
        return ops.get_evidence(ev_id)

    # ---- map ------------------------------------------------------------------
    @app.get("/v1/map/spaces", name="map_spaces")
    def map_spaces(bbox: str | None = None, deep_only: bool = False):
        return c.world.map_spaces(bbox, deep_only)

    @app.get("/v1/map/places", name="map_places")
    def map_places(deep_only: bool = True):
        return c.world.map_places(deep_only)

    @app.get("/v1/map/basemap", name="basemap")
    def basemap():
        p = c.settings.data_dir / "basemap.json"
        if not p.exists():
            raise ApiError("not_ingested", "basemap.json was not downloaded")
        return FileResponse(p, media_type="application/json")

    # ---- admin ------------------------------------------------------------------
    @app.post("/v1/admin/claims/reset", name="claims_reset")
    def claims_reset(body: dict = Body(default={})):
        out = c.claims.reset(body.get("mode", "empty"), body.get("name"), bool(body.get("clear_caches")))
        c.world.invalidate()
        return out

    @app.post("/v1/admin/claims/snapshot", name="claims_snapshot")
    def claims_snapshot(body: dict = Body(...)):
        if not body.get("name"):
            raise ApiError("invalid_argument", "name is required")
        return c.claims.snapshot(body["name"])

    @app.get("/v1/admin/claims/snapshots", name="claims_snapshots")
    def claims_snapshots():
        return {"snapshots": c.claims.list_snapshots()}

    app.mount("/mcp", mcp_app)
    app.add_middleware(CORSMiddleware, allow_origins=list(c.settings.cors_origins), allow_methods=["*"],
                       allow_headers=["*"], expose_headers=["X-Evidence-Id", "X-Content-Hash"])
    app.add_middleware(AuthAndContext, settings=c.settings)
    return app


def _img_headers(evid: str, sha: str) -> dict[str, str]:
    return {"X-Evidence-Id": evid or "", "X-Content-Hash": sha or "", "Cache-Control": "public, max-age=86400"}


def _no_rebind_check():
    try:
        from mcp.server.transport_security import TransportSecuritySettings
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    except Exception:  # noqa: BLE001
        return None


def app_factory() -> FastAPI:
    return create_app()


def _unused(_: Query) -> None:  # keeps the import for OpenAPI parameter docs
    return None
