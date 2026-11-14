"""Typed configuration loaded from environment variables (and an optional .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = Path(__file__).resolve().parents[2]

INDEX_URL = "https://static.matterport.com/hackathon/26.15.39-main-39-gef8d668/assets/quickstart/models_index.csv"
BASEMAP_URL = "https://static.matterport.com/hackathon/26.15.39-main-39-gef8d668/assets/quickstart/basemap.json"
MATTERPORT_GRAPH_URL = "https://api.matterport.com/api/models/graph"
VEXCEL_BASE_URL = "https://api.vexcelgroup.com/v2"
ANTHROPIC_BASE_URL = "https://api.anthropic.com"
LA_MARKET_ID = 20


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    matterport_key: str = field(repr=False, default="")
    matterport_token: str = field(repr=False, default="")
    vexcel_key: str = field(repr=False, default="")
    kit_url: str = field(repr=False, default="")
    kit_password: str = field(repr=False, default="")
    anthropic_key: str = field(repr=False, default="")
    anthropic_base_url: str = ANTHROPIC_BASE_URL
    api_token: str = field(repr=False, default="")
    admin_token: str = field(repr=False, default="")
    caption_model: str = "claude-haiku-5-5"
    caption_fallback_models: tuple[str, ...] = ("claude-sonnet-5-5",)
    caption_effort: str = "low"
    embed_provider: str = "local"          # "local" (fastembed on CPU) or "none" (keyword search only)
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_dim: int = 384
    max_panos_per_space: int = 20
    caption_detail: str = "deep"
    cors_origins: tuple[str, ...] = ("*",)
    selection_path: Path = BACKEND_ROOT / "config" / "selection.json"
    predicates_path: Path = REPO_ROOT / "shared" / "predicates.yaml"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "world.db"

    @property
    def img_dir(self) -> Path:
        return self.data_dir / "img"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def kit_dir(self) -> Path:
        return self.data_dir / "kit"


def load_settings(data_dir: str | os.PathLike | None = None) -> Settings:
    load_dotenv(REPO_ROOT / ".env", override=False)
    load_dotenv(BACKEND_ROOT / ".env", override=False)
    dd = Path(data_dir or _env("WORLD_DATA_DIR") or (BACKEND_ROOT / "data")).resolve()
    return Settings(
        data_dir=dd,
        matterport_key=_env("MATTERPORT_API_KEY"),
        matterport_token=_env("MATTERPORT_API_TOKEN"),
        vexcel_key=_env("VEXCEL_API_KEY"),
        kit_url=_env("COSTAR_KIT_URL"),
        kit_password=_env("COSTAR_ZIP_PASSWORD"),
        # MUNDUS_ANTHROPIC_KEY wins: some hosted shells reserve ANTHROPIC_API_KEY and ANTHROPIC_BASE_URL for themselves
        anthropic_key=_env("MUNDUS_ANTHROPIC_KEY") or _env("ANTHROPIC_API_KEY"),
        anthropic_base_url=_env("MUNDUS_ANTHROPIC_BASE_URL", ANTHROPIC_BASE_URL),
        api_token=_env("WORLD_API_TOKEN"),
        admin_token=_env("WORLD_ADMIN_TOKEN"),
        caption_model=_env("CAPTION_MODEL", "claude-haiku-5-5"),
        caption_fallback_models=tuple(x.strip() for x in _env(
            "CAPTION_FALLBACK_MODELS", "claude-sonnet-5-5").split(",") if x.strip()),
        caption_effort=_env("CAPTION_EFFORT", "low"),
        embed_provider=_env("EMBED_PROVIDER", "local").lower(),
        embed_model=_env("EMBED_MODEL", "BAAI/bge-small-en-v1.5"),
        embed_dim=int(_env("EMBED_DIM", "384")),
        max_panos_per_space=int(_env("MAX_PANOS_PER_SPACE", "20")),
        caption_detail=_env("CAPTION_DETAIL", "deep"),
        cors_origins=tuple(x.strip() for x in _env("CORS_ORIGINS", "*").split(",") if x.strip()),
        selection_path=Path(_env("WORLD_SELECTION") or (BACKEND_ROOT / "config" / "selection.json")),
    )
