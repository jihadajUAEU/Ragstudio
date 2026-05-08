from importlib.util import find_spec

from ragstudio.schemas.runtime import RuntimeProfile
from ragstudio.services.adapter import RAGAnythingAdapter
from ragstudio.services.runtime_types import RuntimeAdapter


class RuntimeUnavailableError(RuntimeError):
    pass


class RAGAnythingRuntimeFactory:
    def build(self, profile: RuntimeProfile) -> RuntimeAdapter:
        if profile.runtime_mode == "fallback":
            return RAGAnythingAdapter()
        if find_spec("raganything") is None:
            raise RuntimeUnavailableError("raganything package is not installed.")
        return RAGAnythingAdapter()
