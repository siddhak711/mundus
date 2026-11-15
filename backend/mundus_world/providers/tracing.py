"""LangSmith tracing: on by default whenever a LangSmith key is present.

Kept identical to harness/mundus_harness/tracing.py (the two packages share no library).
Switch it off with LANGSMITH_TRACING=false. Raw image bytes are left out of traces unless
LANGSMITH_TRACE_IMAGES=1: one caption call carries several photos, and ingestion makes about 1,300 of them.
"""
from __future__ import annotations

import os
from typing import Any

_TRACING_VARS = ("LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING", "LANGCHAIN_TRACING")


def _key() -> str:
    return (os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY") or "").strip()


def enable_tracing(project: str = "mundus") -> bool:
    """Turns tracing on when a key exists and nobody set a tracing variable. An explicit value is respected.
    Returns whether tracing is on."""
    if _key() and not any(os.environ.get(v, "").strip() for v in _TRACING_VARS):
        os.environ["LANGSMITH_TRACING"] = "true"
    if not (os.environ.get("LANGSMITH_PROJECT") or os.environ.get("LANGCHAIN_PROJECT")):
        os.environ["LANGSMITH_PROJECT"] = project
    try:  # langsmith caches environment lookups: clear them so the values above take effect
        from langsmith import utils as ls_utils

        ls_utils.get_env_var.cache_clear()
        ls_utils.get_tracer_project.cache_clear()
        return ls_utils.tracing_is_enabled() is True
    except Exception:  # noqa: BLE001 - tracing must never stop the program
        return False


def _strip_images(obj: Any) -> Any:
    if isinstance(obj, dict):
        src = obj.get("source")
        if obj.get("type") == "image" and isinstance(src, dict) and isinstance(src.get("data"), str):
            return {**obj, "source": {**src, "data": f"<{len(src['data']) * 3 // 4} bytes omitted>"}}
        return {k: _strip_images(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_strip_images(v) for v in obj]
    return obj


def wrap_anthropic(client: Any, name: str = "anthropic") -> Any:
    """Returns the Anthropic client wrapped so every messages call is a LangSmith LLM run. Unchanged if tracing
    is off or langsmith is missing."""
    if not enable_tracing():
        return client
    try:
        from langsmith import Client
        from langsmith.wrappers import wrap_anthropic as _wrap
    except ImportError:
        return client
    keep = os.environ.get("LANGSMITH_TRACE_IMAGES", "0") == "1"
    ls = Client() if keep else Client(hide_inputs=_strip_images)
    return _wrap(client, tracing_extra={"client": ls, "tags": [name]}, chat_name=name)


def traceable_llm(fn: Any, name: str) -> Any:
    """Wraps a function that makes one model call (for calls wrap_anthropic does not patch, such as
    client.beta.messages.stream) as a LangSmith LLM run, with images stripped the same way."""
    if not enable_tracing():
        return fn
    try:
        from langsmith import traceable
    except ImportError:
        return fn
    keep = os.environ.get("LANGSMITH_TRACE_IMAGES", "0") == "1"
    return traceable(run_type="llm", name=name, tags=[name],
                     process_inputs=None if keep else _strip_images)(fn)
