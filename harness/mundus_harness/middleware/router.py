"""Read-card-first, enforced in code: decides once per user turn which facets need work."""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, SystemMessage

from mundus_harness import events, runctx
from mundus_harness.config import Config
from mundus_harness.tools_local import resolve_candidates
from mundus_harness.world_client import WorldClient, WorldError

FACETS = ("market", "interior", "aerial", "surroundings")
KEYWORDS = {
    "market": r"rent|lease|tenant|sale|sold|price|listing|vacan|owner|occup|asking|comp|market|landlord|unit[s]? available|bedroom|bath",
    "interior": r"room|inside|interior|layout|fit|look[s]? like|floor area|ceiling|kitchen|lobby|gym|furnish|equipment|amenit|light|seat|desk|space",
    "aerial": r"roof|parking|outside|parcel|footprint|solar|pool|aerial|above|loading|exterior|tree",
    "surroundings": r"near|around|neighbo|surround|next to|block|street|walk|adjacent building",
}
VISUAL = r"look[s]? like|colou?r|what is in|equipment|condition|furnish|see |visible|appearance|style"


def classify(text: str) -> dict[str, Any]:
    low = text.lower()
    facets = [f for f in FACETS if re.search(KEYWORDS[f], low)]
    return {"facets": facets or list(FACETS), "needs_visual_detail": bool(re.search(VISUAL, low))}


def parse_coverage(card: str) -> dict[str, tuple[str, int]]:
    out: dict[str, tuple[str, int]] = {}
    m = re.search(r"^coverage:(.*)$", card, flags=re.M)
    if m:
        for f, state, n in re.findall(r"(\w+)=(\w+)(?:\((\d+)\))?", m.group(1)):
            out[f] = (state, int(n or 0))
    return out


class RouterMiddleware(AgentMiddleware):
    def __init__(self, cfg: Config, client: WorldClient, fast_model: Any = None):
        super().__init__()
        self.cfg, self.client, self.fast_model = cfg, client, fast_model

    def _last_user_text(self, state) -> str:
        for m in reversed(state.get("messages") or []):
            if isinstance(m, HumanMessage) or getattr(m, "type", "") == "human":
                c = m.content
                return c if isinstance(c, str) else " ".join(b.get("text", "") for b in c if isinstance(b, dict))
        return ""

    def _classify(self, text: str) -> dict[str, Any]:
        if self.cfg.router_use_model and self.fast_model is not None:
            try:
                out = self.fast_model.invoke(
                    'Classify the question. Reply with JSON only: {"facets": [subset of "market","interior","aerial",'
                    f'"surroundings"], "needs_visual_detail": true|false}}.\nQuestion: {text}')
                data = json.loads(re.search(r"\{.*\}", out.content if isinstance(out.content, str) else str(out.content), re.S).group(0))
                facets = [f for f in data.get("facets", []) if f in FACETS]
                if facets:
                    return {"facets": facets, "needs_visual_detail": bool(data.get("needs_visual_detail"))}
            except Exception:  # noqa: BLE001 - fall back to keyword rules
                pass
        return classify(text)

    def before_agent(self, state, runtime):
        rid = runctx.run_id_from_config()
        rec = runctx.record(rid)
        text = self._last_user_text(state)
        ctx = getattr(runtime, "context", None) or {}
        place_id = ctx.get("place_id") if isinstance(ctx, dict) else getattr(ctx, "place_id", None)
        candidates: list[dict] = []
        if not place_id and text:
            try:
                candidates = resolve_candidates(self.client, text)
            except WorldError:
                candidates = []
            if candidates and candidates[0]["match_score"] >= 0.7:
                place_id = candidates[0]["place_id"]
        need = self._classify(text)
        covered: list[str] = []
        cov: dict[str, tuple[str, int]] = {}
        if place_id:
            try:
                cov = parse_coverage(self.client.get_text(f"/v1/places/{place_id}/card"))
            except WorldError:
                place_id = None
        for f in need["facets"]:
            state_, n = cov.get(f, ("none", 0))
            if state_ == "fresh" and n >= self.cfg.coverage_min_claims:
                covered.append(f)
        missing = [f for f in need["facets"] if f not in covered]
        if place_id and not missing and not need["needs_visual_detail"]:
            route = "card_hit"
        elif covered:
            route = "partial"
        else:
            route = "cold"
        info = {"route": route, "place_id": place_id, "facets_needed": need["facets"], "facets_covered": covered,
                "facets_missing": missing, "needs_visual_detail": need["needs_visual_detail"], "candidates": candidates}
        with runctx.lock():
            rec["route"] = info
        events.emit("route", **{k: v for k, v in info.items() if k != "candidates"})
        return None

    # LangGraph Server runs graphs in an event loop and refuses blocking calls there: do the HTTP and file work in a thread
    async def abefore_agent(self, state, runtime):
        return await asyncio.to_thread(self.before_agent, state, runtime)

    def _note(self) -> str:
        info = runctx.record(runctx.run_id_from_config()).get("route") or {}
        rid = runctx.run_id_from_config()
        base = f"\n\nROUTE note (run_id {rid}): "
        if not info.get("place_id"):
            return base + "no place was resolved from the question. Call resolve_place. If nothing matches, say it was not found and write no claims."
        pid = info["place_id"]
        if info["route"] == "card_hit":
            return base + (f"place_id {pid}. The card /world/places/{pid}/card.md already covers every facet this question "
                           "needs. Answer from the card. Do not delegate.")
        if info["route"] == "partial":
            return base + (f"place_id {pid}. Card covers: {', '.join(info['facets_covered'])}. Missing: "
                           f"{', '.join(info['facets_missing'])}. Delegate the missing facets only.")
        return base + (f"place_id {pid}. Nothing needed is covered yet. Facets needed: {', '.join(info['facets_needed'])}. "
                       "Delegate each to its subagent in one turn.")

    def _override(self, request):
        info = runctx.record(runctx.run_id_from_config()).get("route") or {}
        sm = request.system_message
        note = self._note()
        if sm is None:
            content: Any = note
        elif isinstance(sm.content, str):
            content = sm.content + note
        else:                                   # block form: keep every block and append the note as one more
            content = [*sm.content, {"type": "text", "text": note}]
        kw: dict[str, Any] = {"system_message": SystemMessage(content=content)}
        if info.get("route") == "card_hit" and self.fast_model is not None:
            kw["model"] = self.fast_model            # a card hit needs no frontier model
        return request.override(**kw)

    def wrap_model_call(self, request, handler):
        return handler(self._override(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._override(request))
