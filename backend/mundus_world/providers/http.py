"""Rate-limited HTTP with retries. The only module that talks to the network."""
from __future__ import annotations

import json
import logging
import random
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

log = logging.getLogger("mundus.http")


class UpstreamAuthError(RuntimeError):
    """401/403 from an upstream: the key is wrong or lacks access. Stops the step."""


class UpstreamError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


class TokenBucket:
    def __init__(self, rate_per_s: float, burst: float | None = None):
        self.rate = rate_per_s
        self.capacity = burst or max(1.0, rate_per_s)
        self.tokens = self.capacity
        self.t = time.monotonic()
        self.lock = threading.Lock()

    def take(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.t) * self.rate)
                self.t = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            time.sleep(wait)


def _redact(url: str) -> str:
    """Never log query strings: signed links and GET-style keys live there."""
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}{p.path}"


class Http:
    RETRY_STATUS = {429, 500, 502, 503, 504}

    def __init__(self, limits: dict[str, float] | None = None, sleep=time.sleep, max_attempts: int = 5,
                 transport: httpx.BaseTransport | None = None):
        self.client = httpx.Client(timeout=httpx.Timeout(60.0, connect=20.0), follow_redirects=True, transport=transport)
        self.buckets: dict[str, TokenBucket] = {h: TokenBucket(r, r) for h, r in (limits or {}).items()}
        self.sleep = sleep
        self.max_attempts = max_attempts
        self.calls = 0

    def request(self, method: str, url: str, *, headers: dict | None = None, json_body: Any = None,
                params: dict | None = None, auth: tuple[str, str] | None = None, auth_fatal: bool = True,
                timeout: float | None = None) -> httpx.Response:
        host = urlsplit(url).netloc
        last: Exception | None = None
        for attempt in range(self.max_attempts):
            b = self.buckets.get(host)
            if b:
                b.take()
            self.calls += 1
            try:
                r = self.client.request(method, url, headers=headers, json=json_body, params=params, auth=auth,
                                        timeout=timeout)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last = e
                log.warning("network error %s %s (attempt %d): %s", method, _redact(url), attempt + 1, type(e).__name__)
            else:
                if r.status_code in (401, 403) and auth_fatal:
                    raise UpstreamAuthError(f"{host} answered {r.status_code}: check the key for this host")
                if r.status_code not in self.RETRY_STATUS:
                    return r
                last = UpstreamError(r.status_code, r.text[:200])
                log.warning("HTTP %d %s %s (attempt %d)", r.status_code, method, _redact(url), attempt + 1)
            if attempt < self.max_attempts - 1:
                self.sleep(min(16, 2 ** attempt) + random.random() * 0.5)
        raise last if last else UpstreamError(0, "request failed")

    def get_json(self, url: str, **kw) -> Any:
        r = self.request("GET", url, **kw)
        if r.status_code >= 400:
            raise UpstreamError(r.status_code, r.text[:300])
        return r.json()

    def get_bytes(self, url: str, **kw) -> bytes:
        r = self.request("GET", url, **kw)
        if r.status_code >= 400:
            raise UpstreamError(r.status_code, r.text[:200])
        return r.content


def save_raw(raw_dir: Path, source: str, key: str, payload: Any) -> Path:
    p = raw_dir / source / f"{key.replace('/', '_').replace(':', '_')}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def default_http() -> Http:
    return Http(limits={
        "api.matterport.com": 4.0,
        "api.vexcelgroup.com": 2.0,
        "generativelanguage.googleapis.com": 30.0,
        "cdn-2.matterport.com": 16.0,
    })
