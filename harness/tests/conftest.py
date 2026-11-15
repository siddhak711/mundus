"""Harness tests run against the real backend on a synthetic fixture database (no licensed data, no model calls)."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
PLACE = "place:costar:1001"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def world_url(tmp_path_factory) -> str:
    py = BACKEND / ".venv" / "bin" / "python"
    if not py.exists():
        pytest.skip("backend virtualenv not built: run scripts/verify.sh once")
    data = tmp_path_factory.mktemp("world")
    subprocess.run([str(py), "-c", f"import sys; sys.path.insert(0, 'tests'); from conftest import build_world; "
                                   f"from pathlib import Path; build_world(Path({str(data)!r}))"], cwd=BACKEND, check=True)
    port = _free_port()
    env = {**os.environ, "WORLD_DATA_DIR": str(data), "WORLD_API_TOKEN": "", "WORLD_ADMIN_TOKEN": "adm", "EMBED_PROVIDER": "none"}
    proc = subprocess.Popen([str(py), "-m", "mundus_world.runtime.cli", "serve", "--port", str(port)], cwd=BACKEND, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try:
            if httpx.get(url + "/healthz", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("backend did not start")
    yield url
    proc.terminate()


@pytest.fixture()
def cfg(world_url, tmp_path, monkeypatch):
    monkeypatch.setenv("WORLD_REST_URL", world_url)
    monkeypatch.setenv("WORLD_MCP_URL", world_url + "/mcp/")
    monkeypatch.setenv("WORLD_API_TOKEN", "")
    monkeypatch.setenv("HARNESS_DATA_DIR", str(tmp_path / "hdata"))
    from mundus_harness.config import load_config
    httpx.post(world_url + "/v1/admin/claims/reset", json={}, headers={"Authorization": "Bearer adm"})
    return load_config()


class ScriptedModel(BaseChatModel):
    """A fake chat model that plays back a list of AIMessages (or callables taking the message list)."""
    script: list = []
    calls: list = []
    model: str = "scripted"

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        step = self.script.pop(0) if self.script else AIMessage(content="done")
        msg = step(messages) if callable(step) else step
        if not msg.usage_metadata:
            msg.usage_metadata = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
        return ChatResult(generations=[ChatGeneration(message=msg)])


def tool_call(name: str, args: dict, call_id: str | None = None) -> dict:
    return {"name": name, "args": args, "id": call_id or f"call_{name}_{abs(hash(str(args))) % 10**6}", "type": "tool_call"}


sys.path.insert(0, str(Path(__file__).parent))
