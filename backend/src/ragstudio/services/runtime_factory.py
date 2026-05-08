from importlib import import_module

from ragstudio.schemas.runtime import RuntimeProfile
from ragstudio.services.adapter import RAGAnythingAdapter
from ragstudio.services.runtime_types import RuntimeAdapter


class RuntimeUnavailableError(RuntimeError):
    pass


class RAGAnythingRuntimeFactory:
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
        raise RuntimeUnavailableError(
            "Native RAG-Anything runtime adapter is not implemented yet; "
            "set runtime_mode='fallback' for local fallback behavior."
        )
