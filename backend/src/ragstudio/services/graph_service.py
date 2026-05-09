from ragstudio.schemas.graph import GraphOut
from ragstudio.services.adapter import RAGAnythingAdapter
from ragstudio.services.runtime_factory import RAGAnythingRuntimeFactory, RuntimeUnavailableError
from ragstudio.services.runtime_health_service import RuntimeHealthService
from ragstudio.services.runtime_profile_service import (
    RuntimeProfileNotConfiguredError,
    RuntimeProfileService,
)
from sqlalchemy.ext.asyncio import AsyncSession


class RuntimeGraphUnavailableError(RuntimeError):
    pass


class GraphService:
    def __init__(
        self,
        session: AsyncSession | None = None,
        settings=None,
        adapter: RAGAnythingAdapter | None = None,
        runtime_factory=None,
        health_service=None,
    ):
        self.session = session
        self.settings = settings
        self.adapter = adapter or RAGAnythingAdapter()
        self.runtime_factory = runtime_factory or RAGAnythingRuntimeFactory(settings)
        self.health_service = health_service

    async def get_graph(self) -> GraphOut:
        graph = await self._graph()
        return GraphOut(nodes=list(graph.get("nodes") or []), edges=list(graph.get("edges") or []))

    async def _graph(self) -> dict:
        if self.session is None or self.settings is None:
            return await self.adapter.graph()
        try:
            profile = await RuntimeProfileService(self.session, self.settings).get_active_profile()
        except RuntimeProfileNotConfiguredError:
            return await self.adapter.graph()
        if profile.runtime_mode == "fallback":
            return await self.adapter.graph()
        try:
            health_service = self.health_service or RuntimeHealthService(
                self.session,
                verify_storage=True,
            )
            checks = await health_service.check(profile)
            blocking = health_service.blocking_failures(checks)
            if blocking:
                details = "; ".join(item.detail for item in blocking)
                raise RuntimeGraphUnavailableError(
                    f"Runtime graph prerequisites are unavailable: {details}"
                )
            return await self.runtime_factory.build(profile).graph()
        except RuntimeGraphUnavailableError:
            raise
        except RuntimeUnavailableError as exc:
            raise RuntimeGraphUnavailableError(str(exc)) from exc
        except Exception as exc:
            raise RuntimeGraphUnavailableError(
                f"Runtime graph is unavailable: {exc}"
            ) from exc
