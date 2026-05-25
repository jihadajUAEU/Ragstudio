from __future__ import annotations

from typing import Any

from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.reference_metadata import ReferenceSemantics


class MinerURelationshipBuilder:
    def annotate(
        self,
        chunks: list[AdapterChunk],
        domain_metadata: DomainMetadata,
    ) -> list[AdapterChunk]:
        graph = self._graph(domain_metadata)
        if graph is None:
            return chunks

        semantics = ReferenceSemantics.from_metadata(domain_metadata)
        node_refs = [self._chunk_node_ref(chunk, index) for index, chunk in enumerate(chunks)]
        policy = self._graph_policy(graph)
        observed_refs = self._observed_references(chunks, semantics)
        annotated: list[AdapterChunk] = []

        for index, chunk in enumerate(chunks):
            reference_metadata = self._reference_metadata(chunk, semantics)
            references = self._references(reference_metadata, chunk, semantics)
            relationships = self._relationships(
                references=references,
                reference_metadata=reference_metadata,
                source=node_refs[index],
                next_chunk=node_refs[index + 1] if index + 1 < len(chunks) else None,
                has_mineru_structure=self._has_mineru_structure(chunk),
                observed_refs=observed_refs,
                policy=policy,
            )

            if not references and not relationships:
                annotated.append(chunk)
                continue

            metadata = dict(chunk.metadata)
            metadata["relationship_metadata"] = self._merged_relationship_metadata(
                metadata.get("relationship_metadata"),
                references=references,
                relationships=relationships,
                graph=graph,
            )
            annotated.append(
                AdapterChunk(
                    text=chunk.text,
                    source_location=chunk.source_location,
                    metadata=metadata,
                    runtime_source_id=chunk.runtime_source_id,
                    content_type=chunk.content_type,
                    preview_ref=chunk.preview_ref,
                )
            )

        return annotated

    def _relationships(
        self,
        *,
        references: list[str],
        reference_metadata: dict[str, Any],
        source: str,
        next_chunk: str | None,
        has_mineru_structure: bool,
        observed_refs: set[str],
        policy: dict[str, Any],
    ) -> list[dict[str, str]]:
        relationships: list[dict[str, str]] = []
        materialize_reference = policy["materialize_reference"]
        materialize_structure = policy["materialize_structure"]
        edge_types = policy["edge_types"]

        if materialize_reference and "references" in edge_types:
            for reference in references:
                relationships.append(
                    {
                        "type": "references",
                        "source": source,
                        "target": f"ref:{reference}",
                        "evidence": "reference_metadata",
                    }
                )

        previous_ref = reference_metadata.get("previous_ref")
        previous_edge = self._reference_neighbor_edge_type("previous", edge_types)
        if (
            materialize_reference
            and previous_edge is not None
            and isinstance(previous_ref, str)
            and previous_ref in observed_refs
            and references
        ):
            relationships.append(
                {
                    "type": previous_edge,
                    "source": f"ref:{references[0]}",
                    "target": f"ref:{previous_ref}",
                    "evidence": "reference_metadata",
                }
            )

        next_ref = reference_metadata.get("next_ref")
        next_edge = self._reference_neighbor_edge_type("next", edge_types)
        if (
            materialize_reference
            and next_edge is not None
            and isinstance(next_ref, str)
            and next_ref in observed_refs
            and references
        ):
            relationships.append(
                {
                    "type": next_edge,
                    "source": f"ref:{references[-1]}",
                    "target": f"ref:{next_ref}",
                    "evidence": "reference_metadata",
                }
            )

        if (
            materialize_structure
            and has_mineru_structure
            and next_chunk is not None
            and "next_chunk" in edge_types
        ):
            relationships.append(
                {
                    "type": "next_chunk",
                    "source": source,
                    "target": next_chunk,
                    "evidence": "mineru_order",
                }
            )

        return relationships

    def _observed_references(
        self,
        chunks: list[AdapterChunk],
        semantics: ReferenceSemantics,
    ) -> set[str]:
        observed: set[str] = set()
        for chunk in chunks:
            reference_metadata = self._reference_metadata(chunk, semantics)
            observed.update(self._references(reference_metadata, chunk, semantics))
        return observed

    def _merged_relationship_metadata(
        self,
        existing: Any,
        *,
        references: list[str],
        relationships: list[dict[str, str]],
        graph: dict[str, Any],
    ) -> dict[str, Any]:
        if isinstance(existing, dict):
            merged = dict(existing)
        else:
            merged = {}

        existing_references = merged.get("references")
        if isinstance(existing_references, list):
            merged["references"] = self._unique_strings(existing_references + references)
        else:
            merged["references"] = references

        existing_relationships = merged.get("graph_relationships")
        if isinstance(existing_relationships, list):
            merged["graph_relationships"] = self._unique_relationships(
                existing_relationships + relationships
            )
        else:
            merged["graph_relationships"] = relationships

        merged.setdefault("graph_profile", graph)
        return merged

    def _unique_strings(self, values: list[Any]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for value in values:
            if value is None:
                continue
            item = str(value)
            if item in seen:
                continue
            seen.add(item)
            unique.append(item)
        return unique

    def _unique_relationships(self, relationships: list[Any]) -> list[Any]:
        unique: list[Any] = []
        seen: set[tuple[tuple[str, str], ...]] = set()
        for relationship in relationships:
            if not isinstance(relationship, dict):
                unique.append(relationship)
                continue
            key = tuple(
                sorted(
                    (str(item_key), str(item_value))
                    for item_key, item_value in relationship.items()
                )
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(relationship)
        return unique

    def _reference_metadata(
        self,
        chunk: AdapterChunk,
        semantics: ReferenceSemantics,
    ) -> dict[str, Any]:
        metadata = chunk.metadata.get("reference_metadata")
        if isinstance(metadata, dict):
            return metadata
        return semantics.derive_reference_metadata(chunk.text, chunk.source_location)

    def _references(
        self,
        reference_metadata: dict[str, Any],
        chunk: AdapterChunk,
        semantics: ReferenceSemantics,
    ) -> list[str]:
        references = reference_metadata.get("references")
        if isinstance(references, list):
            return [str(reference) for reference in references if reference is not None]
        return [str(ref["ref"]) for ref in semantics.extract_chunk_references(chunk.text)]

    def _graph(self, domain_metadata: DomainMetadata) -> dict[str, Any] | None:
        custom_json = domain_metadata.custom_json
        if not isinstance(custom_json, dict):
            return None

        graph = custom_json.get("graph")
        if not isinstance(graph, dict):
            return None
        if graph.get("confidence_policy") != "evidence_required":
            return None

        materialize_from = graph.get("materialize_from")
        if isinstance(materialize_from, list) and not (
            "mineru_structure" in materialize_from
            or "reference_metadata" in materialize_from
        ):
            return None

        return graph

    def _graph_policy(self, graph: dict[str, Any]) -> dict[str, Any]:
        edge_types = graph.get("edge_types")
        if not isinstance(edge_types, list):
            edge_types = []

        materialize_from = graph.get("materialize_from")
        if isinstance(materialize_from, list):
            materialize_reference = "reference_metadata" in materialize_from
            materialize_structure = "mineru_structure" in materialize_from
        else:
            materialize_reference = True
            materialize_structure = True

        return {
            "edge_types": {str(edge_type) for edge_type in edge_types},
            "materialize_reference": materialize_reference,
            "materialize_structure": materialize_structure,
        }

    def _reference_neighbor_edge_type(
        self,
        direction: str,
        edge_types: set[str],
    ) -> str | None:
        candidates = (
            f"{direction}_reference",
            f"{direction}_ref",
            direction,
        )
        for candidate in candidates:
            if candidate in edge_types:
                return candidate
        return None

    def _has_mineru_structure(self, chunk: AdapterChunk) -> bool:
        parser_metadata = chunk.metadata.get("parser_metadata")
        if not isinstance(parser_metadata, dict):
            return False
        return parser_metadata.get("backend") == "mineru"

    def _chunk_node_ref(self, _chunk: AdapterChunk, index: int) -> str:
        return f"chunk:{index}"
