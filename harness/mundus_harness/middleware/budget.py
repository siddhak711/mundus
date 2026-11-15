"""Keeps a subagent's work from being lost when it runs out of model calls.

Two halves:
- In a subagent: on its last allowed model call it is told to stop calling tools and return what it has.
- In the orchestrator: every `task` result is followed by the claims that subagent wrote in this run, whether it
  finished or not, so the orchestrator always has claim ids to cite.
"""
from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage, ToolMessage

from mundus_harness import runctx

LAST_CALL_NOTE = (
    "\n\nBUDGET note: this is your LAST model call. Do not call any more data tools. Return the result schema now: "
    "list the claims you have already written as findings, and list everything you could not finish under gaps.")


def claims_written(run_id: str, agent: str) -> list[dict[str, Any]]:
    rec = runctx.record(run_id)
    with runctx.lock():
        return list((rec.get("claims_by_agent") or {}).get(agent, []))


def claims_block(agent: str, claims: list[dict[str, Any]]) -> str:
    if not claims:
        return (f"\n\n[{agent} wrote no claims in this run. Do not cite evidence ids directly: if you state a fact, "
                "first write it with put_claim and cite the claim id it returns.]")
    lines = [f"- [{c['claim_id']}] {c['statement']}" for c in claims[-40:]]
    return f"\n\n[Claims written by {agent} in this run. Cite these ids:]\n" + "\n".join(lines)


class BudgetMiddleware(AgentMiddleware):
    def __init__(self, agent: str, model_call_limit: int, is_root: bool):
        super().__init__()
        self.agent, self.limit, self.is_root = agent, model_call_limit, is_root

    # ---- every agent: one result per tool call ------------------------------
    @staticmethod
    def _dedupe(request) -> Any:
        """The model API rejects a conversation that holds two results for one tool call. It happened in 3 of 90 runs
        and stopped them with no answer; keep the first result for each call id."""
        msgs = getattr(request, "messages", None)
        if not msgs:
            return request
        seen: set[str] = set()
        out = []
        for m in msgs:
            if isinstance(m, ToolMessage):
                if m.tool_call_id in seen:
                    continue
                seen.add(m.tool_call_id)
            out.append(m)
        return request if len(out) == len(msgs) else request.override(messages=out)

    # ---- subagent: warn on the last call -----------------------------------
    def _last_call(self, request) -> Any:
        request = self._dedupe(request)
        if self.is_root:
            return request
        state = getattr(request, "state", None) or {}
        if state.get("run_model_call_count", 0) < self.limit - 1:
            return request
        sm = request.system_message
        if sm is None:
            content: Any = LAST_CALL_NOTE
        elif isinstance(sm.content, str):
            content = sm.content + LAST_CALL_NOTE
        else:
            content = [*sm.content, {"type": "text", "text": LAST_CALL_NOTE}]
        return request.override(system_message=SystemMessage(content=content))

    def wrap_model_call(self, request, handler):
        return handler(self._last_call(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._last_call(request))

    # ---- orchestrator: attach the subagent's claims to its result -----------
    def _attach(self, request, result: Any) -> Any:
        call = request.tool_call
        if not self.is_root or call.get("name") != "task" or not isinstance(result, ToolMessage):
            return result
        sub = (call.get("args") or {}).get("subagent_type") or ""
        block = claims_block(sub, claims_written(runctx.run_id_from_config(), sub))
        content = result.content
        if isinstance(content, str):
            content = content + block
        else:
            content = [*content, {"type": "text", "text": block}]
        return ToolMessage(content=content, tool_call_id=result.tool_call_id, name=result.name, status=result.status)

    def wrap_tool_call(self, request, handler):
        return self._attach(request, handler(request))

    async def awrap_tool_call(self, request, handler):
        return self._attach(request, await handler(request))
