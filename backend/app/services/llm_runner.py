from __future__ import annotations

import threading
from dataclasses import dataclass

from llama_cpp import Llama

from app.db.models import Model


@dataclass
class _LoadedModel:
    model_id: int
    path: str
    llama: Llama


class LlmRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._models: dict[int, _LoadedModel] = {}

    def get_llama(self, model: Model) -> Llama:
        if not model.local_path:
            raise RuntimeError("Model is not downloaded yet")

        with self._lock:
            loaded = self._models.get(model.id)
            if loaded and loaded.path == model.local_path:
                return loaded.llama

            llama = Llama(
                model_path=model.local_path,
                n_ctx=2048,
                n_threads=0,  # 0 = auto
            )
            self._models[model.id] = _LoadedModel(model_id=model.id, path=model.local_path, llama=llama)
            return llama

    def list_loaded(self) -> list[int]:
        """Return list of model_ids currently in memory."""
        with self._lock:
            return list(self._models.keys())

    def unload(self, model_id: int) -> bool:
        """Remove model from memory. Returns True if it was loaded."""
        with self._lock:
            if model_id in self._models:
                del self._models[model_id]
                return True
            return False

    def load(self, model: Model) -> None:
        """Preload model into memory."""
        self.get_llama(model)


llm_runner = LlmRunner()

