"""After the run: checks every [claim:...] marker in the answer, drops the ones that do not resolve, emits `answer`."""
from __future__ import annotations

import re
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage

from mundus_harness import events, runctx
from mundus_harness.world_client import WorldClient, WorldError

MARKER = re.compile(r"\[(claim:[0-9a-f]{6,32})\]")


def _text(m: Any) -> str:
    c = m.content
    return c if isinstance(c, str) else "".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")


def resolve_markers(client: WorldClient, text: str) -> tuple[str, list[dict[str, Any]], list[str]]:
    cites: dict[str, dict[str, Any]] = {}
    dropped: list[str] = []
    for cid in dict.fromkeys(MARKER.findall(text)):
        try:
            c = client.get_json(f"/v1/claims/{cid}")
            if c.get("evidence_ids") or c.get("derived_from"):
                cites[cid] = {"claim_id": cid, "evidence_ids": c.get("evidence_ids") or [], "place_id": c.get("place_id"),
                              "status": c.get("status")}
            else:
                dropped.append(cid)
        except WorldError:
            dropped.append(cid)
    for cid in dropped:
        text = text.replace(f"[{cid}]", "")
    return re.sub(r"[ \t]+([.,;])", r"\1", text), list(cites.values()), dropped


class AnswerMiddleware(AgentMiddleware):
    def __init__(self, client: WorldClient):
        super().__init__()
        self.client = client

    def after_agent(self, state, runtime):
        msgs = state.get("messages") or []
        last = next((m for m in reversed(msgs) if isinstance(m, AIMessage) and _text(m).strip()), None)
        if last is None:
            return None
        text, cites, dropped = resolve_markers(self.client, _text(last))
        rec = runctx.record(runctx.run_id_from_config())
        places = sorted({c["place_id"] for c in cites if c.get("place_id")} | ({(rec.get("route") or {}).get("place_id")} - {None}))
        events.emit("answer", text=text, citations=[{"claim_id": c["claim_id"], "evidence_ids": c["evidence_ids"]} for c in cites],
                    place_ids=places, dropped_markers=dropped)
        with runctx.lock():
            rec["answer"] = {"text": text, "citations": cites, "dropped": dropped}
        if dropped:
            return {"messages": [AIMessage(content=text, id=last.id)]}
        return None
