"""The conversion agent: an orchestrator and three subagents (layout, compliance, cost) on deepagents.

Memory: /memories/ is a folder on disk shared by all runs. Every agent reads all of it and writes only its own
subfolder (the orchestrator also owns INDEX.md). Skills are read-only.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from deepagents.middleware.filesystem import FilesystemPermission
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain.chat_models import init_chat_model

from mundus_harness.config import HARNESS_DIR, load_config
from mundus_harness.conversion import prompts
from mundus_harness.conversion.tools import build_tools

SKILLS_DIR = HARNESS_DIR / "skills_conversion"
AGENTS = ("layout", "compliance", "cost")
SUB_TOOLS = {"layout": ["read_floor", "draft_layout", "check_layout"],
             "compliance": ["read_floor", "check_layout", "web_search"],
             "cost": ["read_market", "estimate_returns"]}
ORCH_TOOLS = ["read_floor", "check_layout", "write_layout"]


def memory_dir(data_dir: Path) -> Path:
    d = Path(os.environ.get("CONVERSION_MEMORY_DIR", "").strip() or (data_dir / "conversion_memory"))
    for sub in ("orchestrator", *AGENTS):
        (d / sub).mkdir(parents=True, exist_ok=True)
    if not (d / "INDEX.md").exists():
        (d / "INDEX.md").write_text(prompts.INDEX_SEED, encoding="utf-8")
    seeds = {"layout/lessons.md": "# Layout lessons\n", "compliance/la.md": "# Los Angeles rules: confirmed or corrected\n",
             "cost/assumptions.md": "# Rent sources and cost assumptions\n", "orchestrator/data_quirks.md": "# Data problems found\n"}
    for rel, text in seeds.items():
        if not (d / rel).exists():
            (d / rel).write_text(text, encoding="utf-8")
    return d


def build_backend(mem: Path) -> CompositeBackend:
    return CompositeBackend(default=StateBackend(), routes={
        "/memories/": FilesystemBackend(root_dir=mem, virtual_mode=True),
        "/skills/": FilesystemBackend(root_dir=SKILLS_DIR, virtual_mode=True),
    })


def write_rules(owner: str) -> list[FilesystemPermission]:
    """First match wins: the owner's own memory folder is writable, the rest of /memories/ and all skills are not."""
    own = [f"/memories/{owner}/**"] + (["/memories/INDEX.md"] if owner == "orchestrator" else [])
    return [FilesystemPermission(operations=["write"], paths=own, mode="allow"),
            FilesystemPermission(operations=["write"], paths=["/memories/**", "/skills/**"], mode="deny")]


def build_agent(orch_model: Any = None, worker_models: dict[str, Any] | None = None, data_root: Path | None = None,
                checkpointer: Any = None):
    cfg = load_config()
    tools = build_tools(data_root)
    orch = orch_model or init_chat_model(os.environ.get("CONVERSION_ORCH_MODEL", "anthropic:claude-sonnet-5-5"))
    worker_models = worker_models or {}
    default_worker = {"layout": os.environ.get("CONVERSION_LAYOUT_MODEL", "anthropic:claude-sonnet-5-5"),
                      "compliance": os.environ.get("CONVERSION_WORKER_MODEL", "anthropic:claude-haiku-5-5"),
                      "cost": os.environ.get("CONVERSION_WORKER_MODEL", "anthropic:claude-haiku-5-5")}
    system = {"layout": prompts.LAYOUT, "compliance": prompts.COMPLIANCE, "cost": prompts.COST}
    subagents = []
    for name in AGENTS:
        model = worker_models.get(name) or init_chat_model(default_worker[name])
        subagents.append({
            "name": name, "description": prompts.DESCRIPTIONS[name], "system_prompt": system[name], "model": model,
            "tools": [tools[t] for t in SUB_TOOLS[name]], "permissions": write_rules(name),
            "middleware": [ModelCallLimitMiddleware(run_limit=24), ToolCallLimitMiddleware(run_limit=40)],
        })
    mem = memory_dir(cfg.data_dir)
    return create_deep_agent(
        model=orch,
        tools=[tools[t] for t in ORCH_TOOLS],
        system_prompt=prompts.ORCHESTRATOR,
        middleware=[ModelCallLimitMiddleware(run_limit=30), ToolCallLimitMiddleware(run_limit=60)],
        subagents=subagents,
        skills=["/skills/"],
        memory=["/memories/INDEX.md"],
        permissions=write_rules("orchestrator"),
        backend=build_backend(mem),
        checkpointer=checkpointer,
        name="conversion",
    )


async def make_graph():
    """Entry point for LangGraph Server (langgraph.json)."""
    import asyncio
    return await asyncio.to_thread(build_agent)
