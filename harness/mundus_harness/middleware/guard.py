"""Guards World API tool calls: SQL check before sending, bounded retries, no-retry messages, claim events."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import sqlglot
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from sqlglot import exp

from mundus_harness import events, runctx

NO_RETRY_CODES = {"not_found", "not_ingested", "unauthorized", "sql_rejected", "invalid_argument"}
MAX_ROWS = 200


def check_sql(sql: str) -> tuple[str | None, str | None]:
    """Returns (sql with a LIMIT, None) or (None, reason). Single SELECT only."""
    try:
        stmts = [s for s in sqlglot.parse(sql or "", read="sqlite") if s is not None]
    except sqlglot.errors.ParseError as e:
        return None, f"SQL did not parse: {str(e)[:120]}"
    if len(stmts) != 1:
        return None, "exactly one statement is allowed"
    st = stmts[0]
    if not isinstance(st, (exp.Select, exp.Union)) and not (isinstance(st, exp.Subquery)):
        return None, "only SELECT statements are allowed"
    if any(isinstance(n, (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command, exp.Pragma))
           for n in st.walk()):
        return None, "only SELECT statements are allowed"
    if isinstance(st, exp.Select) and st.args.get("limit") is None:
        st = st.limit(MAX_ROWS)
    return st.sql(dialect="sqlite"), None


def _text(result: Any) -> str:
    c = getattr(result, "content", "")
    if isinstance(c, str):
        return c
    return " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")


class WorldGuardMiddleware(AgentMiddleware):
    def __init__(self, agent: str, world_tools: set[str]):
        super().__init__()
        self.agent, self.world_tools = agent, world_tools

    def _pre(self, request) -> tuple[Any, ToolMessage | None]:
        call = request.tool_call
        if call.get("name") == "query_market":
            sql, reason = check_sql((call.get("args") or {}).get("sql", ""))
            if reason:
                return request, ToolMessage(content=f"Rejected before sending: {reason}. Rewrite as one SELECT.",
                                            tool_call_id=call.get("id", ""), name="query_market", status="error")
            request = request.override(tool_call={**call, "args": {**(call.get("args") or {}), "sql": sql}})
        if call.get("name") == "put_claim" and not (call.get("args") or {}).get("created_by"):
            request = request.override(tool_call={**call, "args": {**(call.get("args") or {}), "created_by": self.agent}})
        return request, None

    def _post(self, request, result: Any) -> Any:
        name = request.tool_call.get("name")
        if name not in self.world_tools or not isinstance(result, ToolMessage):
            return result
        text = _text(result)
        try:
            data = json.loads(text)
        except ValueError:
            return result
        if isinstance(data, dict) and "error" in data:
            err = data["error"]
            if err.get("code") in NO_RETRY_CODES:
                msg = f"Unavailable: {err.get('message')}. Do not retry. Record this as a gap."
                if err.get("code") in ("sql_rejected", "invalid_argument"):
                    msg = f"Rejected: {err.get('message')} {json.dumps(err.get('details') or {})}. Fix the call; do not repeat it unchanged."
                return ToolMessage(content=msg, tool_call_id=result.tool_call_id, name=name, status="error")
            return result
        if name == "put_claim" and isinstance(data, dict) and data.get("claim"):
            c = data["claim"]
            rec = runctx.record(runctx.run_id_from_config())
            with runctx.lock():
                rec["claims_written"] += 1
                rec.setdefault("claims_by_agent", {}).setdefault(self.agent, []).append(
                    {"claim_id": c["id"], "statement": c["statement"]})
            events.emit("claim", agent=self.agent, claim_id=c["id"], subject_id=c["subject_id"], place_id=c.get("place_id"),
                        predicate=c["predicate"], statement=c["statement"], evidence_ids=c["evidence_ids"],
                        confidence=c["confidence"], outcome=data.get("outcome"))
            if data.get("outcome") not in ("created", "merged"):
                events.emit("conflict", agent=self.agent, subject_id=c["subject_id"], predicate=c["predicate"],
                            kept_claim_id=c["id"] if data.get("outcome") == "superseded_old" else (data.get("conflicts") or [None])[0],
                            other_claim_id=(data.get("conflicts") or [None])[0] if data.get("outcome") == "superseded_old" else c["id"],
                            outcome=data.get("outcome"))
        return result

    def wrap_tool_call(self, request, handler):
        request, early = self._pre(request)
        if early:
            return early
        last: Exception | None = None
        for delay in (0, 1, 3):
            if delay:
                time.sleep(delay)
            try:
                return self._post(request, handler(request))
            except Exception as e:  # noqa: BLE001 - network failures from the World API
                if request.tool_call.get("name") not in self.world_tools:
                    raise
                last = e
        return ToolMessage(content=f"Unavailable: {type(last).__name__}. Do not retry. Record this as a gap.",
                           tool_call_id=request.tool_call.get("id", ""), name=request.tool_call.get("name"), status="error")

    async def awrap_tool_call(self, request, handler):
        request, early = self._pre(request)
        if early:
            return early
        last: Exception | None = None
        for delay in (0, 1, 3):
            if delay:
                await asyncio.sleep(delay)
            try:
                return self._post(request, await handler(request))
            except Exception as e:  # noqa: BLE001
                if request.tool_call.get("name") not in self.world_tools:
                    raise
                last = e
        return ToolMessage(content=f"Unavailable: {type(last).__name__}. Do not retry. Record this as a gap.",
                           tool_call_id=request.tool_call.get("id", ""), name=request.tool_call.get("name"), status="error")
