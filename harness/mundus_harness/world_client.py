"""REST client for the World API. All calls share one semaphore (16) and a 20 s timeout."""
from __future__ import annotations

import threading
from typing import Any

import httpx

from mundus_harness.config import Config
from mundus_harness.runctx import run_id_from_config

_SEM = threading.Semaphore(16)


class WorldError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.status, self.code, self.message = status, code, message


class WorldClient:
    def __init__(self, cfg: Config, transport: httpx.BaseTransport | None = None):
        self.cfg = cfg
        headers = {"X-Caller": "harness"}
        if cfg.world_token:
            headers["Authorization"] = f"Bearer {cfg.world_token}"
        self.http = httpx.Client(base_url=cfg.world_rest_url, headers=headers, timeout=20.0, transport=transport)

    def _headers(self, agent: str | None = None) -> dict[str, str]:
        h = {"X-Run-Id": run_id_from_config()}
        if self.cfg.claim_scope_run:
            h["X-Claim-Scope"] = "run"
        if agent:
            h["X-Caller"] = agent
        return h

    def request(self, method: str, path: str, **kw) -> httpx.Response:
        with _SEM:
            r = self.http.request(method, path, headers=self._headers(kw.pop("agent", None)), **kw)
        if r.status_code >= 400:
            try:
                e = r.json()["error"]
                raise WorldError(r.status_code, e.get("code", "error"), e.get("message", ""))
            except (ValueError, KeyError):
                raise WorldError(r.status_code, "error", r.text[:200]) from None
        return r

    def get_json(self, path: str, **params) -> Any:
        return self.request("GET", path, params={k: v for k, v in params.items() if v is not None}).json()

    def get_text(self, path: str) -> str:
        return self.request("GET", path).text

    def post_json(self, path: str, body: dict) -> Any:
        return self.request("POST", path, json=body).json()

    def image(self, path: str, **params) -> tuple[bytes, str, str]:
        r = self.request("GET", path, params=params)
        return r.content, r.headers.get("x-evidence-id", ""), r.headers.get("x-content-hash", "")
