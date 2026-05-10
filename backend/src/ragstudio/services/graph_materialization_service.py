from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from importlib import import_module
from typing import Any

from ragstudio.db.models import Chunk
from ragstudio.services.graph_workspace import (
    chunk_graph_id,
    graph_relationship_type,
    reference_graph_id,
    workspace_label,
)


@dataclass(frozen=True)
class GraphMaterializationResult:
    status: str
    node_count: int
    edge_count: int
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "reason": self.reason,
        }


class GraphMaterializationService:
    def __init__(self, *, driver_factory: Any | None = None):
        self.driver_factory = driver_factory

    @staticmethod
    def failure(reason: str) -> GraphMaterializationResult:
        return GraphMaterializationResult(
            status="failed",
            node_count=0,
            edge_count=0,
            reason=reason,
        )

    async def replace_document_graph(
        self,
        *,
        document_id: str,
        profile: Any,
        chunks: list[Chunk],
    ) -> GraphMaterializationResult:
        if not getattr(profile, "neo4j_uri", None):
            return GraphMaterializationResult(
                status="skipped",
                node_count=0,
                edge_count=0,
                reason="neo4j_uri_missing",
            )

        driver = self._driver(profile)
        if driver is None:
            return GraphMaterializationResult(
                status="skipped",
                node_count=0,
                edge_count=0,
                reason="driver_unavailable",
            )

        label = workspace_label(profile)
        chunk_nodes, reference_nodes, relationships = self._projection(document_id, chunks)
        try:
            await asyncio.to_thread(
                self._replace_graph,
                driver,
                workspace_label=label,
                document_id=document_id,
                chunk_nodes=chunk_nodes,
                reference_nodes=reference_nodes,
                relationships=relationships,
            )
        except Exception as exc:
            return GraphMaterializationResult(
                status="failed",
                node_count=0,
                edge_count=0,
                reason=str(exc),
            )
        finally:
            close = getattr(driver, "close", None)
            if close is not None:
                await asyncio.to_thread(close)

        return GraphMaterializationResult(
            status="succeeded",
            node_count=len(chunk_nodes) + len(reference_nodes),
            edge_count=len(relationships),
        )

    async def delete_document_graph(
        self,
        *,
        document_id: str,
        profile: Any,
    ) -> GraphMaterializationResult:
        if not getattr(profile, "neo4j_uri", None):
            return GraphMaterializationResult(
                status="skipped",
                node_count=0,
                edge_count=0,
                reason="neo4j_uri_missing",
            )

        driver = self._driver(profile)
        if driver is None:
            return GraphMaterializationResult(
                status="skipped",
                node_count=0,
                edge_count=0,
                reason="driver_unavailable",
            )

        try:
            node_count, edge_count = await asyncio.to_thread(
                self._delete_graph,
                driver,
                workspace_label=workspace_label(profile),
                document_id=document_id,
            )
        except Exception as exc:
            return self.failure(str(exc))
        finally:
            close = getattr(driver, "close", None)
            if close is not None:
                await asyncio.to_thread(close)

        return GraphMaterializationResult(
            status="succeeded",
            node_count=node_count,
            edge_count=edge_count,
        )

    def _driver(self, profile: Any) -> Any:
        try:
            neo4j_uri = getattr(profile, "neo4j_uri", None)
            if self.driver_factory is not None:
                return self.driver_factory(neo4j_uri, auth=_auth(profile))
            graph_database = import_module("neo4j").GraphDatabase
            return graph_database.driver(neo4j_uri, auth=_auth(profile))
        except (ImportError, ModuleNotFoundError, RuntimeError, OSError):
            return None

    def _projection(
        self,
        document_id: str,
        chunks: list[Chunk],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        chunk_nodes: list[dict[str, Any]] = []
        reference_nodes_by_id: dict[str, dict[str, Any]] = {}
        relationships: list[dict[str, Any]] = []
        legacy_to_chunk_id: dict[str, str] = {}

        for index, chunk in enumerate(chunks):
            node_id = chunk_graph_id(document_id=document_id, chunk_id=chunk.id)
            legacy_to_chunk_id[f"chunk:{index}"] = node_id
            metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
            references = _references(metadata)
            for reference in references:
                ref_id = reference_graph_id(document_id=document_id, reference=reference)
                reference_nodes_by_id.setdefault(
                    ref_id,
                    {
                        "id": ref_id,
                        "reference": reference,
                        "document_id": document_id,
                    },
                )
            chunk_nodes.append(
                {
                    "id": node_id,
                    "chunk_id": chunk.id,
                    "document_id": document_id,
                    "runtime_source_id": chunk.runtime_source_id,
                    "source_id": metadata.get("source_id"),
                    "text_preview": chunk.text[:500],
                    "content_type": chunk.content_type,
                    **_source_location_properties(chunk.source_location),
                    "references": references,
                }
            )

        allowed_relationships = _allowed_relationship_types(chunks)
        for chunk in chunks:
            metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
            relationship_metadata = metadata.get("relationship_metadata")
            if not isinstance(relationship_metadata, dict):
                continue
            for relationship in relationship_metadata.get("graph_relationships", []):
                if not isinstance(relationship, dict):
                    continue
                source = _graph_node_id(
                    str(relationship.get("source") or ""),
                    legacy_to_chunk_id,
                    document_id=document_id,
                )
                target = _graph_node_id(
                    str(relationship.get("target") or ""),
                    legacy_to_chunk_id,
                    document_id=document_id,
                )
                rel_type = graph_relationship_type(str(relationship.get("type") or "RELATED"))
                if allowed_relationships and rel_type not in allowed_relationships:
                    rel_type = "RELATED"
                if not source or not target:
                    continue
                if source.startswith("ref:"):
                    reference_nodes_by_id.setdefault(
                        source,
                        {
                            "id": source,
                            "reference": _reference_value_from_node_id(source, document_id),
                            "document_id": document_id,
                        },
                    )
                if target.startswith("ref:"):
                    reference_nodes_by_id.setdefault(
                        target,
                        {
                            "id": target,
                            "reference": _reference_value_from_node_id(target, document_id),
                            "document_id": document_id,
                        },
                    )
                relationships.append(
                    {
                        "source": source,
                        "target": target,
                        "type": rel_type,
                        "document_id": document_id,
                        "evidence": _neo4j_property(relationship.get("evidence")),
                        "evidence_json": _neo4j_json_property(relationship.get("evidence")),
                    }
                )

        return chunk_nodes, list(reference_nodes_by_id.values()), relationships

    def _replace_graph(
        self,
        driver: Any,
        *,
        workspace_label: str,
        document_id: str,
        chunk_nodes: list[dict[str, Any]],
        reference_nodes: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
    ) -> None:
        delete_query = f"""
        MATCH (n:`{workspace_label}`)
        WHERE n.document_id = $document_id
        DETACH DELETE n
        """
        upsert_nodes_query = f"""
        UNWIND $chunk_nodes AS node
        MERGE (chunk:`{workspace_label}` {{id: node.id}})
        SET chunk:Chunk:RagstudioChunk,
            chunk.chunk_id = node.chunk_id,
            chunk.document_id = node.document_id,
            chunk.runtime_source_id = node.runtime_source_id,
            chunk.source_id = node.source_id,
            chunk.text_preview = node.text_preview,
            chunk.content_type = node.content_type,
            chunk.page = node.page,
            chunk.section = node.section,
            chunk.start_index = node.start_index,
            chunk.end_index = node.end_index,
            chunk.source_location_json = node.source_location_json,
            chunk.references = node.references
        WITH 1 AS ignored
        UNWIND $reference_nodes AS node
        MERGE (ref:`{workspace_label}` {{id: node.id}})
        SET ref:Reference:RagstudioReference,
            ref.reference = node.reference,
            ref.document_id = node.document_id
        """

        def write_transaction(tx: Any) -> None:
            tx.run(delete_query, document_id=document_id)
            tx.run(
                upsert_nodes_query,
                chunk_nodes=chunk_nodes,
                reference_nodes=reference_nodes,
            )
            for rel_type in sorted({relationship["type"] for relationship in relationships}):
                typed_relationships = [
                    relationship
                    for relationship in relationships
                    if relationship["type"] == rel_type
                ]
                tx.run(
                    f"""
                    UNWIND $relationships AS rel
                    MATCH (source:`{workspace_label}` {{id: rel.source}})
                    WHERE source.document_id = rel.document_id
                    MATCH (target:`{workspace_label}` {{id: rel.target}})
                    WHERE target.document_id = rel.document_id
                    MERGE (source)-[relationship:`{rel_type}`]->(target)
                    SET relationship.document_id = rel.document_id,
                        relationship.evidence = rel.evidence,
                        relationship.evidence_json = rel.evidence_json
                    """,
                    relationships=typed_relationships,
                )

        with driver.session() as session:
            self._ensure_indexes(session)
            session.execute_write(write_transaction)

    def _delete_graph(
        self,
        driver: Any,
        *,
        workspace_label: str,
        document_id: str,
    ) -> tuple[int, int]:
        count_query = f"""
        MATCH (n:`{workspace_label}`)
        WHERE n.document_id = $document_id
        OPTIONAL MATCH (n)-[relationship]-()
        RETURN count(DISTINCT n) AS node_count,
               count(DISTINCT relationship) AS edge_count
        """
        delete_query = f"""
        MATCH (n:`{workspace_label}`)
        WHERE n.document_id = $document_id
        DETACH DELETE n
        """
        with driver.session() as session:
            count_row = _first_row(session.run(count_query, document_id=document_id))
            node_count = _int_from_row(count_row, "node_count")
            edge_count = _int_from_row(count_row, "edge_count")
            session.run(delete_query, document_id=document_id)
        return node_count, edge_count

    def _ensure_indexes(self, session: Any) -> None:
        session.run(
            """
            CREATE INDEX ragstudio_chunk_projection IF NOT EXISTS
            FOR (n:RagstudioChunk)
            ON (n.document_id, n.id)
            """
        )
        session.run(
            """
            CREATE INDEX ragstudio_reference_projection IF NOT EXISTS
            FOR (n:RagstudioReference)
            ON (n.document_id, n.id)
            """
        )


def _auth(profile: Any) -> tuple[str, str] | None:
    username = getattr(profile, "neo4j_username", None)
    password = getattr(profile, "neo4j_password", None)
    if username or password:
        return (username or "", password or "")
    return None


def _first_row(rows: Any) -> Any:
    for row in rows:
        return row
    return None


def _int_from_row(row: Any, key: str) -> int:
    if row is None:
        return 0
    try:
        value = row.get(key) if hasattr(row, "get") else row[key]
    except (KeyError, TypeError):
        return 0
    return int(value) if isinstance(value, (int, float)) else 0


def _references(metadata: dict[str, Any]) -> list[str]:
    relationship_metadata = metadata.get("relationship_metadata")
    if isinstance(relationship_metadata, dict):
        relationship_refs = relationship_metadata.get("references")
        if isinstance(relationship_refs, list):
            return [str(reference) for reference in relationship_refs if reference is not None]
    reference_metadata = metadata.get("reference_metadata")
    if not isinstance(reference_metadata, dict):
        return []
    references = reference_metadata.get("references")
    if not isinstance(references, list):
        return []
    return [str(reference) for reference in references if reference is not None]


def _source_location_properties(value: Any) -> dict[str, Any]:
    source_location = value if isinstance(value, dict) else {}
    return {
        "page": source_location.get("page"),
        "section": source_location.get("section"),
        "start_index": source_location.get("start_index"),
        "end_index": source_location.get("end_index"),
        "source_location_json": json.dumps(source_location, ensure_ascii=False)
        if source_location
        else None,
    }


def _neo4j_property(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list) and all(
        isinstance(item, (str, int, float, bool)) for item in value
    ):
        return value
    return None


def _neo4j_json_property(value: Any) -> str | None:
    if _neo4j_property(value) is not None or value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def _graph_node_id(
    value: str,
    legacy_to_chunk_id: dict[str, str],
    *,
    document_id: str,
) -> str:
    if not value:
        return ""
    if value in legacy_to_chunk_id:
        return legacy_to_chunk_id[value]
    if value.startswith("ref:"):
        return reference_graph_id(document_id=document_id, reference=value)
    if value.startswith("chunk:"):
        return value
    return reference_graph_id(document_id=document_id, reference=value)


def _reference_value_from_node_id(node_id: str, document_id: str) -> str:
    prefix = f"ref:{document_id}:"
    if node_id.startswith(prefix):
        return node_id.removeprefix(prefix)
    return node_id.removeprefix("ref:")


def _allowed_relationship_types(chunks: list[Chunk]) -> set[str]:
    values: set[str] = set()
    for chunk in chunks:
        metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
        relationship_metadata = metadata.get("relationship_metadata")
        if not isinstance(relationship_metadata, dict):
            continue
        graph_profile = relationship_metadata.get("graph_profile")
        if not isinstance(graph_profile, dict):
            continue
        edge_types = graph_profile.get("edge_types")
        if not isinstance(edge_types, list):
            continue
        values.update(
            graph_relationship_type(str(edge_type))
            for edge_type in edge_types
            if edge_type is not None
        )
    return values
