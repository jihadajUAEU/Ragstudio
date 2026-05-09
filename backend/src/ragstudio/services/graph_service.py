from typing import Any

from ragstudio.db.models import Chunk
from ragstudio.schemas.graph import GraphOut
from ragstudio.services.adapter import RAGAnythingAdapter
from ragstudio.services.runtime_factory import RAGAnythingRuntimeFactory, RuntimeUnavailableError
from ragstudio.services.runtime_health_service import RuntimeHealthService
from ragstudio.services.runtime_profile_service import (
    RuntimeProfileNotConfiguredError,
    RuntimeProfileService,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class RuntimeGraphUnavailableError(RuntimeError):
    pass


GLOBAL_FALLBACK_GRAPH_ID_PREFIXES = ("ref:", "reference:", "topic:")


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
            fallback_graph = await self._relationship_metadata_graph()
            if fallback_graph["nodes"] or fallback_graph["edges"]:
                return fallback_graph
            return await self.adapter.graph()
        if profile.runtime_mode == "fallback":
            fallback_graph = await self._relationship_metadata_graph()
            if fallback_graph["nodes"] or fallback_graph["edges"]:
                return fallback_graph
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

    async def _relationship_metadata_graph(self) -> dict[str, list[dict[str, Any]]]:
        if self.session is None:
            return {"nodes": [], "edges": []}
        result = await self.session.execute(
            select(Chunk.id, Chunk.document_id, Chunk.source_location, Chunk.metadata_json)
        )
        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[str, dict[str, Any]] = {}
        for _chunk_id, document_id, source_location_raw, metadata_raw in result.all():
            metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
            source_location = (
                source_location_raw if isinstance(source_location_raw, dict) else {}
            )
            relationship_metadata = metadata.get("relationship_metadata", {})
            if not isinstance(relationship_metadata, dict):
                continue
            relationships = relationship_metadata.get("graph_relationships", [])
            if not isinstance(relationships, list):
                continue
            for relationship in relationships:
                if not isinstance(relationship, dict):
                    continue
                source = relationship.get("source")
                target = relationship.get("target")
                rel_type = relationship.get("type")
                if not all(
                    isinstance(value, str) and value for value in [source, target, rel_type]
                ):
                    continue
                source_id = self._fallback_graph_node_id(source, document_id)
                target_id = self._fallback_graph_node_id(target, document_id)
                nodes.setdefault(
                    source_id,
                    {
                        "id": source_id,
                        "labels": ["FallbackRelationship"],
                        "properties": {
                            "label": relationship.get("source_label", source),
                            "document_id": document_id,
                            **source_location,
                        },
                    },
                )
                nodes.setdefault(
                    target_id,
                    {
                        "id": target_id,
                        "labels": ["FallbackRelationship"],
                        "properties": {
                            "label": relationship.get("target_label", target),
                            "document_id": document_id,
                            **source_location,
                        },
                    },
                )
                edge_id = f"{source_id}-{target_id}-{rel_type}"
                edges.setdefault(
                    edge_id,
                    {
                        "id": edge_id,
                        "source": source_id,
                        "target": target_id,
                        "type": rel_type,
                        "properties": {
                            "document_id": document_id,
                            **source_location,
                        },
                    },
                )
        return {"nodes": list(nodes.values()), "edges": list(edges.values())}

    @staticmethod
    def _fallback_graph_node_id(raw_id: str, document_id: str) -> str:
        if raw_id.startswith(GLOBAL_FALLBACK_GRAPH_ID_PREFIXES):
            return raw_id
        return f"document:{document_id}:{raw_id}"
