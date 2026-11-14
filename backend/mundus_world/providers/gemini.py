"""Gemini: pano captions (vision, JSON out) and text embeddings."""
from __future__ import annotations

import base64
import json
import time
from typing import Any

from mundus_world.config.settings import GEMINI_BASE_URL, Settings
from mundus_world.providers.http import Http, UpstreamError

CAPTION_PROMPT_VERSION = "cap-v2"
# Word targets for the free-text description. "deep" is the default; the others exist for length experiments.
DETAIL_WORDS = {"brief": (40, 70), "standard": (120, 180), "deep": (280, 400), "max": (500, 700)}
CAPTION_PROMPT = """You are documenting one camera position inside or around a building for a factual spatial database.
Other agents will answer questions about this place using only your text, without seeing the photos.
The {n} images are the horizontal views from one 360-degree camera position, in rotation order (view 1 to view {n}).
Space name: {space_name}. Room label from the scanner: {room_label}. Room size: {dims}.

Write for someone who must reason about the space physically: what it is, how big it feels, what is where,
what it is made of, how you get in and out, and what is unusual. Be concrete and specific. Count things.
Name materials, colours, fixtures, equipment, furniture types, signage wording, ceiling type, lighting type,
window size and what is seen through windows, floor level changes, and anything connecting to another space.
Describe only what is visible. No marketing language. No guesses about things out of view; if something is
partly visible or uncertain, say so in those words.

Return one JSON object with exactly these keys:
- room_type: short label, e.g. lobby, gym, open office, kitchen, corridor, pool deck, warehouse bay
- summary: 2 plain factual sentences
- description: {wmin} to {wmax} words of continuous prose. Start with the overall space and its apparent size and
  shape, then go view by view ("View 1: ...") saying what is in the foreground, middle and background of each,
  then finish with how the space connects to others.
- views: list of {n} strings, one sentence each, what dominates that view
- objects: list of {{name, count}} for every distinct object type you can identify
- surfaces: {{floor, walls, ceiling}} with material and colour
- light: natural, artificial or mixed, with window and fixture description
- openings: list of doors, doorways, stairs, elevators, ramps and exits visible, each with which view it is in
- sightlines: list of other rooms or outdoor areas visible from here and through what
- safety: list of fire extinguishers, sprinkler heads, exit signs, alarms, railings, hazards visible
- visible_text: list of readable signage or text, verbatim
- condition: new | good | worn | damaged | under construction, with one phrase of evidence
- indoor_outdoor: indoor | outdoor | mixed
- size_cues: list of things that indicate scale (ceiling height estimate, number of bays, row counts)
- notable: up to 8 distinctive details"""


class Gemini:
    def __init__(self, settings: Settings, http: Http):
        self.s = settings
        self.http = http
        self._thinking_ok: dict[str, bool] = {}
        self.on_usage = None                  # callback(purpose, model, tokens_in, tokens_out, tokens_thought, estimated, ms)
        self.exhausted: set[str] = set()      # models whose daily quota is spent in this process
        # generation calls: few retries, because a spent daily quota never recovers within a run
        self._gen_http = Http(limits={"generativelanguage.googleapis.com": 30.0}, max_attempts=2)

    @property
    def _h(self) -> dict[str, str]:
        return {"x-goog-api-key": self.s.gemini_key, "Content-Type": "application/json"}

    def _generate(self, model: str, parts: list[dict], want_json: bool = True) -> dict[str, Any]:
        gen: dict[str, Any] = {"temperature": 0}
        if want_json:
            gen["responseMimeType"] = "application/json"
        use_thinking = self._thinking_ok.get(model, True)
        if use_thinking:
            gen["thinkingConfig"] = {"thinkingLevel": "low"}
        url = f"{GEMINI_BASE_URL}/models/{model}:generateContent"
        try:
            r = self._gen_http.request("POST", url, headers=self._h, timeout=180,
                                       json_body={"contents": [{"parts": parts}], "generationConfig": gen})
        except UpstreamError as e:
            if e.status == 429:
                self.exhausted.add(model)
            raise
        if r.status_code == 400 and use_thinking:
            # The model does not accept this thinking setting: remember and retry without it.
            self._thinking_ok[model] = False
            return self._generate(model, parts, want_json)
        if r.status_code >= 400:
            raise UpstreamError(r.status_code, r.text[:300])
        return r.json()

    def caption(self, images_jpeg: list[bytes], space_name: str, room_label: str, dims: str,
                model: str | None = None, detail: str = "deep") -> tuple[dict[str, Any], dict[str, Any], str]:
        """Returns (caption dict, usage metadata, model used)."""
        wmin, wmax = DETAIL_WORDS.get(detail, DETAIL_WORDS["deep"])
        prompt = CAPTION_PROMPT.format(n=len(images_jpeg), space_name=space_name or "unknown",
                                       room_label=room_label or "none", dims=dims or "unknown", wmin=wmin, wmax=wmax)
        parts: list[dict] = [{"text": prompt}]
        for b in images_jpeg:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(b).decode()}})
        last: Exception | None = None
        models = [model or self.s.caption_model, *self.s.caption_fallback_models]
        for m in dict.fromkeys(models):
            for _ in range(2):
                if m in self.exhausted:
                    break
                try:
                    t0 = time.perf_counter()
                    body = self._generate(m, parts)
                    um = body.get("usageMetadata") or {}
                    if self.on_usage:
                        self.on_usage("caption", m, um.get("promptTokenCount", 0), um.get("candidatesTokenCount", 0),
                                      um.get("thoughtsTokenCount", 0), 0, (time.perf_counter() - t0) * 1000)
                    text = body["candidates"][0]["content"]["parts"][0]["text"]
                    cap = json.loads(text)
                    if isinstance(cap, list) and cap:
                        cap = cap[0]
                    if not isinstance(cap, dict) or not str(cap.get("summary", "")).strip():
                        raise ValueError("caption missing summary")
                    return cap, body.get("usageMetadata") or {}, m
                except (UpstreamError, KeyError, IndexError, ValueError) as e:
                    last = e
        if last is None:
            raise UpstreamError(429, "every caption model has spent its quota: " + ", ".join(sorted(self.exhausted)))
        raise last

    def embed(self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT", timeout: float = 60) -> list[list[float]]:
        model = self.s.embed_model
        out: list[list[float]] = []
        for i in range(0, len(texts), 50):
            reqs = [{"model": f"models/{model}", "content": {"parts": [{"text": t[:8000]}]}, "taskType": task_type,
                     "outputDimensionality": self.s.embed_dim} for t in texts[i:i + 50]]
            t0 = time.perf_counter()
            r = self.http.request("POST", f"{GEMINI_BASE_URL}/models/{model}:batchEmbedContents", headers=self._h,
                                  json_body={"requests": reqs}, timeout=timeout)
            if r.status_code >= 400:
                raise UpstreamError(r.status_code, r.text[:300])
            out.extend(e["values"] for e in r.json()["embeddings"])
            if self.on_usage:  # the embedding API reports no usage: estimate 1 token per 4 characters
                est = sum(len(t[:8000]) for t in texts[i:i + 50]) // 4
                self.on_usage("embed_query" if task_type == "RETRIEVAL_QUERY" else "embed_document", model, est, 0, 0, 1,
                              (time.perf_counter() - t0) * 1000)
        return out


def caption_to_text(cap: dict[str, Any]) -> str:
    """Deterministic flattening of a caption into one text block for search, cards and agents."""
    bits: list[str] = []
    if cap.get("room_type"):
        bits.append(f"{str(cap['room_type']).strip().capitalize()}.")
    if cap.get("summary"):
        bits.append(str(cap["summary"]).strip())
    if cap.get("description"):
        bits.append(str(cap["description"]).strip())
    objs = [f"{o.get('count', 1)} {o.get('name')}" for o in (cap.get("objects") or [])
            if isinstance(o, dict) and o.get("name")]
    if objs:
        bits.append("Objects: " + ", ".join(objs[:40]) + ".")
    surf = cap.get("surfaces") or {}
    if isinstance(surf, dict):
        sv = [f"{k}: {v}" for k, v in surf.items() if v]
        if sv:
            bits.append("Surfaces: " + "; ".join(sv) + ".")
    for key, label in (("light", "Light"), ("condition", "Condition"), ("indoor_outdoor", "Setting")):
        if cap.get(key):
            bits.append(f"{label}: {cap[key]}.")
    for key, label in (("openings", "Openings"), ("access", "Access"), ("sightlines", "Sightlines"),
                       ("safety", "Safety"), ("visible_text", "Visible text"), ("size_cues", "Size cues"),
                       ("notable", "Notable")):
        v = [str(x) for x in (cap.get(key) or []) if x] if isinstance(cap.get(key), list) else []
        if v:
            bits.append(f"{label}: " + "; ".join(v[:12]) + ".")
    return " ".join(bits)


def caption_short(cap: dict[str, Any]) -> str:
    rt = str(cap.get("room_type") or "").strip().capitalize()
    return (f"{rt}. " if rt else "") + str(cap.get("summary") or "").strip()
