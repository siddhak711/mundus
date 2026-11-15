"""Claude: pano captions (vision in, JSON out)."""
from __future__ import annotations

import base64
import json
import time
from typing import Any

import anthropic

from mundus_world.config.settings import Settings
from mundus_world.providers.http import UpstreamAuthError, UpstreamError

CAPTION_PROMPT_VERSION = "cap-v3"
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
- description: {wmin} to {wmax} words of continuous prose, never more than {wmax}. Start with the overall space and its apparent size and
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



_STR = {"type": "string"}
_LIST = {"type": "array", "items": _STR}
CAPTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "room_type": _STR, "summary": _STR, "description": _STR, "views": _LIST,
        "objects": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"name": _STR, "count": {"type": "integer"}}, "required": ["name", "count"]}},
        "surfaces": {"type": "object", "additionalProperties": False,
                     "properties": {"floor": _STR, "walls": _STR, "ceiling": _STR},
                     "required": ["floor", "walls", "ceiling"]},
        "light": _STR, "openings": _LIST, "sightlines": _LIST, "safety": _LIST, "visible_text": _LIST,
        "condition": _STR, "indoor_outdoor": _STR, "size_cues": _LIST, "notable": _LIST,
    },
}
CAPTION_SCHEMA["required"] = list(CAPTION_SCHEMA["properties"])


def _parse_json(text: str) -> Any:
    """Parse a JSON object from model text, tolerating a code fence or prose around it."""
    t = text.strip()
    try:
        return json.loads(t)
    except ValueError:
        a, b = t.find("{"), t.rfind("}")
        if a < 0 or b <= a:
            raise
        return json.loads(t[a:b + 1])


class Claude:
    """Caption provider. `caption` returns (caption dict, usage, model); usage keys: tokens_in, tokens_out, tokens_thought."""

    def __init__(self, settings: Settings):
        self.s = settings
        self.on_usage = None                  # callback(purpose, model, tokens_in, tokens_out, tokens_thought, estimated, ms)
        self._client: anthropic.Anthropic | None = None
        self._schema_ok = True                # set False if the API rejects the output schema
        self._thinking_off_ok: dict[str, bool] = {}

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            if not self.s.anthropic_key:
                raise UpstreamAuthError("no Anthropic key: set ANTHROPIC_API_KEY (or MUNDUS_ANTHROPIC_KEY)")
            # base_url is explicit so an ANTHROPIC_BASE_URL meant for another tool is never picked up
            self._client = anthropic.Anthropic(api_key=self.s.anthropic_key, base_url=self.s.anthropic_base_url,
                                               max_retries=4, timeout=180.0)
        return self._client

    def _generate(self, model: str, content: list[dict]) -> anthropic.types.Message:
        kw: dict[str, Any] = {"model": model, "max_tokens": 8000, "messages": [{"role": "user", "content": content}]}
        out_cfg: dict[str, Any] = {"effort": self.s.caption_effort}
        if self._schema_ok:
            out_cfg["format"] = {"type": "json_schema", "schema": CAPTION_SCHEMA}
        kw["output_config"] = out_cfg
        # Captioning is description, not reasoning: turn thinking off where the model allows it (Haiku does).
        thinking_off = "haiku" in model and self._thinking_off_ok.get(model, True)
        if thinking_off:
            kw["thinking"] = {"type": "disabled"}
        try:
            return self.client.messages.create(**kw)
        except anthropic.BadRequestError as e:
            msg = str(e).lower()
            if thinking_off and "thinking" in msg:
                self._thinking_off_ok[model] = False
                return self._generate(model, content)
            if self._schema_ok and ("schema" in msg or "output_config" in msg or "format" in msg):
                self._schema_ok = False
                return self._generate(model, content)
            raise

    def caption(self, images_jpeg: list[bytes], space_name: str, room_label: str, dims: str,
                model: str | None = None, detail: str = "deep") -> tuple[dict[str, Any], dict[str, int], str]:
        wmin, wmax = DETAIL_WORDS.get(detail, DETAIL_WORDS["deep"])
        prompt = CAPTION_PROMPT.format(n=len(images_jpeg), space_name=space_name or "unknown",
                                       room_label=room_label or "none", dims=dims or "unknown", wmin=wmin, wmax=wmax)
        content: list[dict] = []
        for i, b in enumerate(images_jpeg, 1):
            content.append({"type": "text", "text": f"View {i}:"})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                        "data": base64.standard_b64encode(b).decode()}})
        content.append({"type": "text", "text": prompt + "\nReturn only the JSON object."})
        last: Exception | None = None
        for m in dict.fromkeys([model or self.s.caption_model, *self.s.caption_fallback_models]):
            for _ in range(2):
                try:
                    t0 = time.perf_counter()
                    msg = self._generate(m, content)
                    u = msg.usage
                    det = getattr(u, "output_tokens_details", None)
                    usage = {"tokens_in": u.input_tokens or 0, "tokens_out": u.output_tokens or 0,
                             "tokens_thought": (getattr(det, "thinking_tokens", 0) or 0) if det else 0}
                    if self.on_usage:
                        self.on_usage("caption", m, usage["tokens_in"], usage["tokens_out"], usage["tokens_thought"], 0,
                                      (time.perf_counter() - t0) * 1000)
                    if msg.stop_reason in ("refusal", "max_tokens"):
                        raise ValueError(f"caption stopped: {msg.stop_reason}")
                    text = "".join(b.text for b in msg.content if b.type == "text")
                    cap = _parse_json(text)
                    if isinstance(cap, list) and cap:
                        cap = cap[0]
                    if not isinstance(cap, dict) or not str(cap.get("summary", "")).strip():
                        raise ValueError("caption missing summary")
                    return cap, usage, m
                except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
                    raise UpstreamAuthError(f"api.anthropic.com answered {e.status_code}: check the Anthropic key") from e
                except anthropic.APIStatusError as e:
                    last = UpstreamError(e.status_code, str(e)[:300])
                except (anthropic.APIConnectionError, ValueError) as e:
                    last = e
        raise last if last else UpstreamError(0, "caption failed")


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
