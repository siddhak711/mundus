"""Builds the deep agent: one orchestrator, three specialist subagents, the /world mount and the middleware stack."""
from __future__ import annotations

from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from deepagents.middleware.filesystem import FilesystemPermission
from langchain.agents.middleware import ModelCallLimitMiddleware, TodoListMiddleware, ToolCallLimitMiddleware
from langchain.chat_models import init_chat_model
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from typing_extensions import TypedDict

from mundus_harness import prompts, runctx
from mundus_harness.config import HARNESS_DIR, Config, load_config
from mundus_harness.middleware.answer import AnswerMiddleware
from mundus_harness.middleware.guard import WorldGuardMiddleware
from mundus_harness.middleware.metrics import MetricsMiddleware
from mundus_harness.middleware.router import RouterMiddleware
from mundus_harness.tools_local import build_local_tools
from mundus_harness.world_backend import WorldBackend
from mundus_harness.world_client import WorldClient

WORLD_TOOLS = ["search_places", "get_place", "get_space", "get_room", "search_interiors", "get_aerial_facts",
               "aerial_semantic_search", "describe_market", "query_market", "get_neighbors", "get_claims", "put_claim",
               "get_evidence"]
SUBAGENT_TOOLS = {
    "market-analyst": ["get_place", "describe_market", "query_market", "get_neighbors", "get_claims", "put_claim", "set_focus"],
    "interior-inspector": ["get_space", "get_room", "search_interiors", "look_at_pano", "get_claims", "put_claim", "set_focus"],
    "aerial-analyst": ["get_aerial_facts", "look_at_aerial", "aerial_semantic_search", "get_neighbors", "get_claims",
                       "put_claim", "set_focus"],
}
ORCH_TOOLS = ["resolve_place", "get_neighbors", "get_claims", "put_claim", "set_focus"]


class Ctx(TypedDict, total=False):
    place_id: str


async def load_world_tools(cfg: Config) -> dict[str, Any]:
    """World API tools over MCP. Every call carries the run id and the calling agent as headers."""
    headers = {"X-Caller": "harness"}
    if cfg.world_token:
        headers["Authorization"] = f"Bearer {cfg.world_token}"

    async def tag_run(request: MCPToolCallRequest, handler):
        h = dict(request.headers or {})
        h["X-Run-Id"] = runctx.run_id_from_config()
        return await handler(request.override(headers=h))

    client = MultiServerMCPClient({"world": {"transport": "streamable_http", "url": cfg.world_mcp_url, "headers": headers}},
                                  tool_interceptors=[tag_run])
    tools = await client.get_tools()
    return {t.name: t for t in tools}


def build_backend(cfg: Config, client: WorldClient) -> CompositeBackend:
    (cfg.data_dir / "memory").mkdir(parents=True, exist_ok=True)
    mem = cfg.data_dir / "memory" / "AGENTS.md"
    if not mem.exists():
        mem.write_text("# Lessons learned by Mundus agents\n", encoding="utf-8")
    return CompositeBackend(default=StateBackend(), routes={
        "/world/": WorldBackend(client),
        "/skills/": FilesystemBackend(root_dir=HARNESS_DIR / "skills", virtual_mode=True),
        "/memory/": FilesystemBackend(root_dir=cfg.data_dir / "memory", virtual_mode=True),
    })


def build_agent(cfg: Config, world_tools: dict[str, Any], orch_model: Any = None, worker_model: Any = None,
                client: WorldClient | None = None, checkpointer: Any = None):
    client = client or WorldClient(cfg)
    local = build_local_tools(cfg, client)
    tools = {**world_tools, **local}
    missing = [t for t in WORLD_TOOLS if t not in world_tools]
    if missing:
        raise RuntimeError(f"World API is missing tools the harness needs: {missing}")
    orch = orch_model or init_chat_model(cfg.orch_model)
    worker = worker_model or init_chat_model(cfg.worker_model)
    world_names = set(WORLD_TOOLS)

    def stack(agent: str, is_root: bool) -> list[Any]:
        mw: list[Any] = [MetricsMiddleware(cfg, agent, is_root=is_root), WorldGuardMiddleware(agent, world_names),
                         ModelCallLimitMiddleware(run_limit=cfg.orch_model_calls if is_root else cfg.sub_model_calls),
                         ToolCallLimitMiddleware(run_limit=cfg.orch_tool_calls if is_root else cfg.sub_tool_calls)]
        return mw

    sys = {"market-analyst": prompts.MARKET, "interior-inspector": prompts.INTERIOR, "aerial-analyst": prompts.AERIAL}
    desc = {
        "market-analyst": "Market facts for one place from CoStar records: building basics, listings and rents, tenants and leases, sales.",
        "interior-inspector": "What the inside of a place is like: spaces, rooms, sizes, layout, appearance from photos and captions.",
        "aerial-analyst": "What a place looks like from above and what surrounds it: footprint, roof, parking, pool, neighbours.",
    }
    subagents = [{"name": n, "description": desc[n], "system_prompt": sys[n], "model": worker,
                  "tools": [tools[t] for t in SUBAGENT_TOOLS[n]], "middleware": stack(n, False),
                  "response_format": prompts.SubagentResult} for n in SUBAGENT_TOOLS]
    return create_deep_agent(
        model=orch,
        tools=[tools[t] for t in ORCH_TOOLS],
        system_prompt=prompts.ORCHESTRATOR,
        # order matters: metrics resets the run record first, then the router fills in the route
        middleware=[TodoListMiddleware(), MetricsMiddleware(cfg, "orchestrator", is_root=True),
                    RouterMiddleware(cfg, client, fast_model=worker), *stack("orchestrator", True)[1:],
                    AnswerMiddleware(client)],
        subagents=subagents,
        skills=["/skills/"],
        memory=["/memory/AGENTS.md"],
        permissions=[FilesystemPermission(operations=["write"], paths=["/world/**", "/skills/**"], mode="deny")],
        backend=build_backend(cfg, client),
        context_schema=Ctx,
        checkpointer=checkpointer,
        name="mundus",
    )


async def make_graph():
    """Entry point for LangGraph Server (langgraph.json)."""
    cfg = load_config()
    return build_agent(cfg, await load_world_tools(cfg))
