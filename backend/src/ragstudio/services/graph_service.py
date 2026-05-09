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
                self._set_fallback_graph_node(
                    nodes,
                    node_id=source_id,
                    raw_id=source,
                    label=relationship.get("source_label", source),
                    document_id=document_id,
                    source_location=source_location,
                )
                self._set_fallback_graph_node(
                    nodes,
                    node_id=target_id,
                    raw_id=target,
                    label=relationship.get("target_label", target),
                    document_id=document_id,
                    source_location=source_location,
                )
                edge_id = self._fallback_graph_edge_id(
                    source_id,
                    target_id,
                    rel_type,
                    document_id,
                    source_global=self._is_fallback_graph_global_id(source),
                    target_global=self._is_fallback_graph_global_id(target),
                )
                edges.setdefault(
                    edge_id,
                    {
                        "id": edge_id,
                        "source": source_id,
                        "target": target_id,
                        "type": rel_type,
                        "properties": {
                            **source_location,
                            "document_id": document_id,
                        },
                    },
                )
        return {"nodes": list(nodes.values()), "edges": list(edges.values())}

    @staticmethod
    def _fallback_graph_node_id(raw_id: str, document_id: str) -> str:
        if GraphService._is_fallback_graph_global_id(raw_id):
            return raw_id
        return f"document:{document_id}:{raw_id}"

    @staticmethod
    def _fallback_graph_edge_id(
        source_id: str,
        target_id: str,
        rel_type: str,
        document_id: str,
        *,
        source_global: bool,
        target_global: bool,
    ) -> str:
        edge_id = f"{source_id}-{target_id}-{rel_type}"
        if source_global and target_global:
            return f"{edge_id}-document:{document_id}"
        return edge_id

    @staticmethod
    def _set_fallback_graph_node(
        nodes: dict[str, dict[str, Any]],
        *,
        node_id: str,
        raw_id: str,
        label: Any,
        document_id: str,
        source_location: dict[str, Any],
    ) -> None:
        if GraphService._is_fallback_graph_global_id(raw_id):
            node = nodes.setdefault(
                node_id,
                {
                    "id": node_id,
                    "labels": ["FallbackRelationship"],
                    "properties": {
                        "label": label,
                        "document_ids": [],
                        "locations": [],
                    },
                },
            )
            properties = node["properties"]
            if document_id not in properties["document_ids"]:
                properties["document_ids"].append(document_id)
            location = {**source_location, "document_id": document_id}
            if location not in properties["locations"]:
                properties["locations"].append(location)
            return

        nodes.setdefault(
            node_id,
            {
                "id": node_id,
                "labels": ["FallbackRelationship"],
                "properties": {
                    **source_location,
                    "label": label,
                    "document_id": document_id,
                },
            },
        )

    @staticmethod
    def _is_fallback_graph_global_id(raw_id: str) -> bool:
        return raw_id.startswith(GLOBAL_FALLBACK_GRAPH_ID_PREFIXES)
