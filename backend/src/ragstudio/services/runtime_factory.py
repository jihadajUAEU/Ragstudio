from importlib import import_module

from ragstudio.config import AppSettings
from ragstudio.schemas.runtime import RuntimeProfile
from ragstudio.services.adapter import RAGAnythingAdapter
from ragstudio.services.native_raganything_adapter import NativeRAGAnythingAdapter
from ragstudio.services.runtime_types import RuntimeAdapter


class RuntimeUnavailableError(RuntimeError):
    pass


class RAGAnythingRuntimeFactory:
    def __init__(self, settings: AppSettings | None = None):
        self.settings = settings

    def build(self, profile: RuntimeProfile) -> RuntimeAdapter:
        if profile.runtime_mode == "fallback":
            return RAGAnythingAdapter()
        try:
            import_module("raganything")
            import_module("lightrag")
        except Exception as exc:
            raise RuntimeUnavailableError(
                "RAG-Anything runtime dependencies are not importable."
            ) from exc
        return NativeRAGAnythingAdapter(profile, self.settings)
