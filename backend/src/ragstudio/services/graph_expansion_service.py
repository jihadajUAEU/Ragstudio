from __future__ import annotations

import asyncio
from importlib import import_module
from typing import Any

from ragstudio.services.graph_workspace import workspace_label
from ragstudio.services.retrieval_evidence import EvidenceCandidate


class GraphExpansionService:
    def __init__(self, *, driver_factory: Any | None = None):
        self.driver_factory = driver_factory

    async def expand(
        self,
        query: str,
        *,
        seeds: list[EvidenceCandidate],
        profile: Any,
        document_ids: list[str],
        limit: int,
    ) -> tuple[list[EvidenceCandidate], list[dict[str, Any]]]:
        if not getattr(profile, "neo4j_uri", None):
            return [], [_skipped_trace("neo4j_uri_missing")]

        seed_ids = _seed_ids(seeds)
        if not seed_ids:
            return [], [_skipped_trace("no_seed_ids")]

        driver = self._driver(profile)
        if driver is None:
            return [], [_skipped_trace("driver_unavailable")]

        label = workspace_label(profile)
        try:
            rows = await asyncio.to_thread(
                self._run_query,
                driver,
                workspace_label=label,
                seed_ids=seed_ids,
                document_ids=document_ids,
                limit=limit,
            )
        finally:
            close = getattr(driver, "close", None)
            if close is not None:
                await asyncio.to_thread(close)
        candidates = [
            candidate
            for index, row in enumerate(rows, start=1)
            if (candidate := _candidate_from_row(index, row)).text.strip()
        ]
        return candidates, [
            {
                "stage": "graph_expansion",
                "status": "ok",
                "seed_count": len(seed_ids),
                "expanded_candidates": len(candidates),
                "workspace_label": label,
            }
        ]

    def _driver(self, profile: Any) -> Any:
        try:
            if self.driver_factory is not None:
                return self.driver_factory(profile.neo4j_uri, auth=_auth(profile))
            graph_database = import_module("neo4j").GraphDatabase
            return graph_database.driver(profile.neo4j_uri, auth=_auth(profile))
        except (ImportError, ModuleNotFoundError, RuntimeError, OSError):
            return None

    def _run_query(
        self,
        driver: Any,
        *,
        workspace_label: str,
        seed_ids: list[str],
        document_ids: list[str],
        limit: int,
    ) -> list[Any]:
        workspace_node = f"`{workspace_label}`"
        chunk_node = f"{workspace_node}:RagstudioChunk"
        reference_node = f"{workspace_node}:RagstudioReference"
        cypher = f"""
        CALL {{
            MATCH (seed:{workspace_node})-[relationship]-(neighbor:{chunk_node})
            WHERE coalesce(
                seed.chunk_id,
                seed.runtime_source_id,
                seed.id,
                seed.source_id
            ) IN $seed_ids
            AND seed.id <> neighbor.id
            AND (
                size($document_ids) = 0
                OR coalesce(
                    neighbor.document_id,
                    neighbor.full_doc_id,
                    neighbor.doc_id
                ) IN $document_ids
            )
            RETURN elementId(relationship) AS relationship_id,
                   type(relationship) AS relationship_type,
                   properties(relationship) AS relationship_properties,
                   properties(seed) AS seed_properties,
                   elementId(neighbor) AS neighbor_id,
                   labels(neighbor) AS neighbor_labels,
                   properties(neighbor) AS neighbor_properties,
                   [] AS bridge_relationship_types,
                   "direct_chunk" AS graph_path
            UNION
            MATCH (seed:{workspace_node})-[seed_relationship]-(reference:{reference_node})
            MATCH (reference)-[bridge_relationship*0..1]-(candidate_reference:{reference_node})
            MATCH (candidate_reference)-[relationship]-(neighbor:{chunk_node})
            WHERE coalesce(
                seed.chunk_id,
                seed.runtime_source_id,
                seed.id,
                seed.source_id
            ) IN $seed_ids
            AND seed.id <> neighbor.id
            AND (
                size($document_ids) = 0
                OR coalesce(
                    neighbor.document_id,
                    neighbor.full_doc_id,
                    neighbor.doc_id
                ) IN $document_ids
            )
            RETURN elementId(relationship) AS relationship_id,
                   type(relationship) AS relationship_type,
                   properties(relationship) AS relationship_properties,
                   properties(seed) AS seed_properties,
                   elementId(neighbor) AS neighbor_id,
                   labels(neighbor) AS neighbor_labels,
                   properties(neighbor) AS neighbor_properties,
                   [rel IN bridge_relationship | type(rel)] AS bridge_relationship_types,
                   "reference_hop" AS graph_path
        }}
        LIMIT $limit
        """
        with driver.session() as session:
            return list(
                session.run(
                    cypher,
                    seed_ids=seed_ids,
                    document_ids=document_ids,
                    limit=max(limit, 1),
                )
            )


def _skipped_trace(reason: str) -> dict[str, str]:
    return {
        "stage": "graph_expansion",
        "status": "skipped",
        "reason": reason,
    }


def _seed_ids(seeds: list[EvidenceCandidate]) -> list[str]:
    values: list[str] = []
    for seed in seeds:
        for value in (
            seed.chunk_id,
            seed.metadata.get("runtime_source_id"),
            seed.metadata.get("id"),
            seed.metadata.get("source_id"),
        ):
            if isinstance(value, str) and value and value not in values:
                values.append(value)
    return values


def _candidate_from_row(index: int, row: Any) -> EvidenceCandidate:
    properties = dict(_row_get(row, "neighbor_properties") or {})
    relationship = {
        "id": _row_get(row, "relationship_id"),
        "type": _row_get(row, "relationship_type"),
        "properties": dict(_row_get(row, "relationship_properties") or {}),
        "seed": dict(_row_get(row, "seed_properties") or {}),
        "bridge_relationship_types": list(_row_get(row, "bridge_relationship_types") or []),
        "path": _row_get(row, "graph_path"),
    }
    chunk_id = _first_str(properties, "chunk_id", "runtime_source_id", "id", "source_id")
    document_id = _first_str(properties, "document_id", "full_doc_id", "doc_id")
    text = (
        _first_str(properties, "text", "content", "text_preview", "description", "summary")
        or ""
    )
    source_location = {
        key: properties[key]
        for key in ("page", "section", "bbox", "start_index", "end_index")
        if key in properties
    }
    metadata = {
        **properties,
        "graph_relationship": relationship,
        "graph_labels": list(_row_get(row, "neighbor_labels") or []),
    }
    return EvidenceCandidate(
        candidate_id=f"graph:{_row_get(row, 'neighbor_id')}",
        text=text,
        document_id=document_id,
        chunk_id=chunk_id,
        source_location=source_location,
        metadata=metadata,
        tool="graph",
        tool_rank=index,
        base_score=max(1.0, 18.0 - index),
        boost_score=2.0,
        final_score=max(1.0, 20.0 - index),
        reasons=["graph_neighbor"],
    )


def _auth(profile: Any) -> tuple[str, str] | None:
    username = getattr(profile, "neo4j_username", None)
    password = getattr(profile, "neo4j_password", None)
    if username or password:
        return (username or "", password or "")
    return None


def _first_str(values: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = values.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _row_get(row: Any, key: str) -> Any:
    if hasattr(row, "get"):
        return row.get(key)
    return row[key]
