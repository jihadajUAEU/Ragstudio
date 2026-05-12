from typing import Any

from ragstudio.db.models import Chunk, GraphProjectionRecord
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
            projection_detail = await self._blocking_projection_detail(
                runtime_profile_id=profile.id
            )
            if projection_detail is not None:
                return await self._graph_projection_not_ready(projection_detail)
            projection_detail = await self._latest_projection_detail(
                runtime_profile_id=profile.id
            )
            graph = await self.runtime_factory.build(profile).graph()
            if graph.get("nodes") or graph.get("edges"):
                return graph
            fallback = await self._relationship_metadata_graph()
            if fallback.get("nodes") or fallback.get("edges"):
                fallback["detail"] = self._runtime_empty_detail(
                    projection_detail,
                    fallback_available=True,
                )
                return fallback
            return {
                "nodes": [],
                "edges": [],
                "detail": self._runtime_empty_detail(
                    projection_detail,
                    fallback_available=False,
                ),
            }
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
        nodes: dict[tuple[str, str], dict[str, Any]] = {}
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
                if (
                    not isinstance(source, str)
                    or not source
                    or not isinstance(target, str)
                    or not target
                    or not isinstance(rel_type, str)
                    or not rel_type
                ):
                    continue
                source_node_id = f"{chunk.document_id}:{source}"
                target_node_id = f"{chunk.document_id}:{target}"
                nodes.setdefault(
                    (chunk.document_id, source),
                    {
                        "id": source_node_id,
                        "labels": ["RelationshipMetadata"],
                        "properties": {
                            "label": relationship.get("source_label", source),
                            "document_id": chunk.document_id,
                            "relationship_id": source,
                            **source_location,
                        },
                    },
                )
                nodes.setdefault(
                    (chunk.document_id, target),
                    {
                        "id": target_node_id,
                        "labels": ["RelationshipMetadata"],
                        "properties": {
                            "label": relationship.get("target_label", target),
                            "document_id": chunk.document_id,
                            "relationship_id": target,
                            **source_location,
                        },
                    },
                )
                edge_id = f"{chunk.document_id}:{source}-{target}-{rel_type}"
                edges.setdefault(
                    edge_id,
                    {
                        "id": edge_id,
                        "source": source_node_id,
                        "target": target_node_id,
                        "type": rel_type,
                        "properties": {
                            "document_id": chunk.document_id,
                            "source_relationship_id": source,
                            "target_relationship_id": target,
                            **source_location,
                        },
                    },
                )
        detail = None
        if not nodes and not edges:
            detail = "No runtime graph or relationship metadata is available."
        else:
            detail = "Relationship metadata fallback graph."
        return {"nodes": list(nodes.values()), "edges": list(edges.values()), "detail": detail}

    async def _blocking_projection_detail(
        self,
        *,
        runtime_profile_id: str,
    ) -> str | None:
        if self.session is None:
            return None
        result = await self.session.execute(
            select(GraphProjectionRecord)
            .where(GraphProjectionRecord.runtime_profile_id == runtime_profile_id)
            .order_by(GraphProjectionRecord.created_at.asc(), GraphProjectionRecord.id.asc())
        )
        latest_by_document: dict[str, GraphProjectionRecord] = {}
        for record in result.scalars().all():
            latest_by_document[record.document_id] = record
        blocking = [
            record for record in latest_by_document.values() if record.status != "succeeded"
        ]
        if not blocking:
            return None
        latest_blocking = max(blocking, key=lambda record: record.created_at)
        return self._projection_detail(latest_blocking)

    async def _graph_projection_not_ready(
        self,
        projection_detail: str | None,
    ) -> dict[str, list[dict[str, Any]] | str | None]:
        fallback = await self._relationship_metadata_graph()
        detail = projection_detail or "Latest graph projection is not ready."
        if fallback.get("nodes") or fallback.get("edges"):
            fallback["detail"] = (
                "Graph projection is not ready; showing relationship metadata fallback graph. "
                f"{detail}"
            )
            return fallback
        return {
            "nodes": [],
            "edges": [],
            "detail": f"Graph projection is not ready. {detail}",
        }

    async def _latest_projection_detail(
        self,
        *,
        runtime_profile_id: str | None = None,
    ) -> str | None:
        record = await self._latest_projection_record(runtime_profile_id=runtime_profile_id)
        if record is None:
            return None
        return self._projection_detail(record)

    def _projection_detail(self, record: GraphProjectionRecord) -> str:
        if record.status == "succeeded":
            return (
                "Latest graph projection succeeded with "
                f"{record.node_count} nodes and {record.edge_count} edges."
            )
        reason = f": {record.error}" if record.error else "."
        if record.status in {"failed", "skipped", "stale"}:
            return f"Latest graph projection {record.status}{reason}"
        return f"Latest graph projection is {record.status}{reason}"

    async def _latest_projection_record(
        self,
        *,
        runtime_profile_id: str | None = None,
    ) -> GraphProjectionRecord | None:
        if self.session is None:
            return None
        statement = select(GraphProjectionRecord)
        if runtime_profile_id is not None:
            statement = statement.where(
                GraphProjectionRecord.runtime_profile_id == runtime_profile_id
            )
        record = await self.session.scalar(
            statement.order_by(GraphProjectionRecord.created_at.desc()).limit(1)
        )
        return record

    def _runtime_empty_detail(
        self,
        projection_detail: str | None,
        *,
        fallback_available: bool,
    ) -> str:
        base = (
            "Neo4j graph is empty; showing relationship metadata fallback graph."
            if fallback_available
            else "Neo4j graph is empty and no relationship metadata fallback graph is available."
        )
        if projection_detail:
            return f"{base} {projection_detail}"
        return base
