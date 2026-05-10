from typing import Any

from ragstudio.db.models import Chunk
from ragstudio.schemas.graph import GraphOut
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


class GraphService:
    def __init__(
        self,
        session: AsyncSession | None = None,
        settings=None,
        runtime_factory=None,
        health_service=None,
    ):
        self.session = session
        self.settings = settings
        self.runtime_factory = runtime_factory or RAGAnythingRuntimeFactory(settings)
        self.health_service = health_service

    async def get_graph(self) -> GraphOut:
        graph = await self._graph()
        return GraphOut(
            nodes=list(graph.get("nodes") or []),
            edges=list(graph.get("edges") or []),
            detail=graph.get("detail"),
        )

    async def _graph(self) -> dict:
        if self.session is None or self.settings is None:
            return await self._relationship_metadata_graph()
        try:
            profile = await RuntimeProfileService(self.session, self.settings).get_active_profile()
        except RuntimeProfileNotConfiguredError:
            return await self._relationship_metadata_graph()
        if profile.runtime_mode == "fallback":
            return await self._relationship_metadata_graph()
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
            raise RuntimeGraphUnavailableError(f"Runtime graph is unavailable: {exc}") from exc

    async def _relationship_metadata_graph(
        self, *, limit: int = 2_000
    ) -> dict[str, list[dict[str, Any]] | str | None]:
        if self.session is None:
            return {
                "nodes": [],
                "edges": [],
                "detail": "No database session is available for relationship metadata graph.",
            }
        result = await self.session.execute(
            select(Chunk)
            .where(Chunk.metadata_json["relationship_metadata"].as_string().is_not(None))
            .order_by(Chunk.created_at.desc())
            .limit(limit)
        )
        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[str, dict[str, Any]] = {}
        for chunk in result.scalars().all():
            metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
            source_location = (
                chunk.source_location if isinstance(chunk.source_location, dict) else {}
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
                nodes.setdefault(
                    source,
                    {
                        "id": source,
                        "labels": ["RelationshipMetadata"],
                        "properties": {
                            "label": relationship.get("source_label", source),
                            "document_id": chunk.document_id,
                            **source_location,
                        },
                    },
                )
                nodes.setdefault(
                    target,
                    {
                        "id": target,
                        "labels": ["RelationshipMetadata"],
                        "properties": {
                            "label": relationship.get("target_label", target),
                            "document_id": chunk.document_id,
                            **source_location,
                        },
                    },
                )
                edge_id = f"{source}-{target}-{rel_type}"
                edges.setdefault(
                    edge_id,
                    {
                        "id": edge_id,
                        "source": source,
                        "target": target,
                        "type": rel_type,
                        "properties": {
                            "document_id": chunk.document_id,
                            **source_location,
                        },
                    },
                )
        detail = None
        if not nodes and not edges:
            detail = "No runtime graph or relationship metadata is available."
        return {"nodes": list(nodes.values()), "edges": list(edges.values()), "detail": detail}
