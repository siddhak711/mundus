"""Local text embeddings (fastembed, ONNX on CPU). No API key and no network after the first model download.
Search falls back to keyword-only when this is switched off (EMBED_PROVIDER=none) or fastembed is not installed."""
from __future__ import annotations

import logging
import threading

import numpy as np

from mundus_world.config.settings import Settings

log = logging.getLogger("mundus.embed")


class Embedder:
    def __init__(self, settings: Settings):
        self.s = settings
        self._model = None
        self._failed = False
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.s.embed_provider == "local" and not self._failed

    def _load(self):
        if self._model is None and self.enabled:
            with self._lock:
                if self._model is None and not self._failed:
                    try:
                        from fastembed import TextEmbedding
                        cache = self.s.data_dir / "models"
                        cache.mkdir(parents=True, exist_ok=True)
                        self._model = TextEmbedding(model_name=self.s.embed_model, cache_dir=str(cache))
                    except Exception as e:  # noqa: BLE001 - not installed, or the model cannot be downloaded
                        self._failed = True
                        log.warning("local embeddings unavailable, search is keyword-only: %s: %s", type(e).__name__, e)
        return self._model

    def available(self) -> bool:
        return self._load() is not None

    @staticmethod
    def _unit(v) -> np.ndarray:
        a = np.asarray(v, dtype=np.float32)
        return a / (np.linalg.norm(a) or 1.0)

    def documents(self, texts: list[str]) -> list[np.ndarray]:
        m = self._load()
        if m is None:
            return []
        return [self._unit(v) for v in m.embed([t[:8000] for t in texts], batch_size=16)]

    def query(self, text: str) -> np.ndarray | None:
        m = self._load()
        if m is None:
            return None
        return self._unit(next(iter(m.query_embed(text))))
