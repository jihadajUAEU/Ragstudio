from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.domain_metadata_service import DomainMetadataService
from ragstudio.services.mineru_relationship_builder import MinerURelationshipBuilder


def quran_metadata(
    *,
    edge_types: list[str] | None = None,
    materialize_from: list[str] | None = None,
) -> DomainMetadata:
    return DomainMetadata(
        domain="quran_tafseer",
        document_type="commentary",
        citation_style="surah_ayah",
        expected_structure="surah_ayah_sections",
        tags=["quran", "religious_text"],
        custom_json={
            "reference_schema": {
                "type": "chapter_verse",
                "display": "{chapter}:{verse}",
                "fields": {"chapter": "surah_number", "verse": "ayah_number"},
            },
            "chunking": {"unit": "verse", "include_neighbors": 1},
            "graph": {
                "node_types": ["surah", "ayah", "chunk"],
                "edge_types": edge_types
                or ["contains", "previous_reference", "next_reference", "references"],
                "materialize_from": materialize_from
                or ["mineru_structure", "reference_metadata"],
                "confidence_policy": "evidence_required",
            },
        },
    )


def hadith_metadata() -> DomainMetadata:
    return DomainMetadata(
        domain="hadith",
        document_type="collection",
        citation_style="book_hadith",
        expected_structure="book_chapter_hadith",
        tags=["hadith", "religious_text"],
        custom_json={
            "reference_schema": {
                "type": "book_hadith",
                "display": "Book {book}, Hadith {hadith}",
                "fields": {"book": "book_number", "hadith": "hadith_number"},
            },
            "chunking": {"unit": "hadith", "include_neighbors": 1},
            "graph": {
                "node_types": ["book", "hadith", "chunk"],
                "edge_types": ["references", "next_reference", "previous_reference"],
                "materialize_from": ["reference_metadata"],
                "confidence_policy": "evidence_required",
            },
        },
    )


def test_mineru_relationship_builder_adds_reference_and_neighbor_edges():
    chunks = [
        AdapterChunk(
            text="[113:1] Say, I seek refuge in the Lord of daybreak.",
            source_location={"page": 1},
            metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
        ),
        AdapterChunk(
            text="[113:2] From the evil of that which He created.",
            source_location={"page": 1},
            metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 1}},
        ),
    ]

    annotated = MinerURelationshipBuilder().annotate(chunks, quran_metadata())

    first_relationships = annotated[0].metadata["relationship_metadata"]
    second_relationships = annotated[1].metadata["relationship_metadata"]
    assert first_relationships["references"] == ["113:1"]
    assert first_relationships["graph_relationships"] == [
        {
            "type": "references",
            "source": "chunk:0",
            "target": "ref:113:1",
            "evidence": "reference_metadata",
        },
        {
            "type": "next_reference",
            "source": "ref:113:1",
            "target": "ref:113:2",
            "evidence": "reference_metadata",
        },
    ]
    assert second_relationships["references"] == ["113:2"]
    assert second_relationships["graph_relationships"][1] == {
        "type": "previous_reference",
        "source": "ref:113:2",
        "target": "ref:113:1",
        "evidence": "reference_metadata",
    }


def test_mineru_relationship_builder_uses_generic_reference_neighbor_edges():
    chunks = [
        AdapterChunk(
            text="[113:1] First unit.",
            source_location={"page": 1},
            metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
        ),
        AdapterChunk(
            text="[113:2] Second unit.",
            source_location={"page": 1},
            metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 1}},
        ),
    ]

    annotated = MinerURelationshipBuilder().annotate(
        chunks,
        quran_metadata(edge_types=["references", "previous_reference", "next_reference"]),
    )

    relationships = annotated[0].metadata["relationship_metadata"]["graph_relationships"]
    assert {
        "type": "next_reference",
        "source": "ref:113:1",
        "target": "ref:113:2",
        "evidence": "reference_metadata",
    } in relationships
    assert all(item["type"] != "next_ayah" for item in relationships)


def test_mineru_relationship_builder_does_not_emit_unobserved_neighbor_edges():
    chunk = AdapterChunk(
        text="[113:2] From the evil of that which He created.",
        source_location={"page": 1},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
    )

    annotated = MinerURelationshipBuilder().annotate([chunk], quran_metadata())

    relationships = annotated[0].metadata["relationship_metadata"]["graph_relationships"]
    assert relationships == [
        {
            "type": "references",
            "source": "chunk:0",
            "target": "ref:113:2",
            "evidence": "reference_metadata",
        }
    ]


def test_mineru_relationship_builder_adds_hadith_reference_edges():
    chunks = [
        AdapterChunk(
            text="Book 1, Hadith 1 narrated text.",
            source_location={"page": 1},
            metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
        ),
        AdapterChunk(
            text="Book 1, Hadith 2 narrated text.",
            source_location={"page": 1},
            metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 1}},
        ),
    ]

    annotated = MinerURelationshipBuilder().annotate(chunks, hadith_metadata())

    relationships = annotated[0].metadata["relationship_metadata"]
    assert relationships["references"] == ["book:1:hadith:1"]
    assert {
        "type": "next_reference",
        "source": "ref:book:1:hadith:1",
        "target": "ref:book:1:hadith:2",
        "evidence": "reference_metadata",
    } in relationships["graph_relationships"]


def test_mineru_relationship_builder_uses_builtin_quran_profile(tmp_path):
    profile = DomainMetadataService(tmp_path).get_profile("quran_tafseer")
    chunk = AdapterChunk(
        text="[113:1] Say, I seek refuge in the Lord of daybreak.",
        source_location={"page": 1},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
    )

    assert profile is not None
    annotated = MinerURelationshipBuilder().annotate([chunk], profile.metadata)

    assert annotated[0].metadata["relationship_metadata"]["graph_relationships"] == [
        {
            "type": "references",
            "source": "chunk:0",
            "target": "ref:113:1",
            "evidence": "reference_metadata",
        }
    ]


def test_mineru_relationship_builder_uses_builtin_hadith_profile(tmp_path):
    profile = DomainMetadataService(tmp_path).get_profile("hadith")
    chunk = AdapterChunk(
        text="Book 1, Hadith 1 narrated text.",
        source_location={"page": 1},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
    )

    assert profile is not None
    annotated = MinerURelationshipBuilder().annotate([chunk], profile.metadata)

    assert annotated[0].metadata["relationship_metadata"]["graph_relationships"] == [
        {
            "type": "references",
            "source": "chunk:0",
            "target": "ref:book:1:hadith:1",
            "evidence": "reference_metadata",
        }
    ]


def test_mineru_relationship_builder_adds_unique_order_edges_when_policy_allows():
    chunks = [
        AdapterChunk(
            text="[113:1] Say, I seek refuge in the Lord of daybreak.",
            source_location={"page": 1},
            metadata={
                "parser_metadata": {
                    "backend": "mineru",
                    "chunk_index": 0,
                    "split_index": 0,
                }
            },
        ),
        AdapterChunk(
            text="[113:1] continued.",
            source_location={"page": 1},
            metadata={
                "parser_metadata": {
                    "backend": "mineru",
                    "chunk_index": 0,
                    "split_index": 1,
                }
            },
        ),
    ]

    annotated = MinerURelationshipBuilder().annotate(
        chunks,
        quran_metadata(edge_types=["references", "next_chunk"]),
    )

    relationships = annotated[0].metadata["relationship_metadata"]["graph_relationships"]
    assert {
        "type": "next_chunk",
        "source": "chunk:0",
        "target": "chunk:1",
        "evidence": "mineru_order",
    } in relationships


def test_mineru_relationship_builder_skips_unsupported_reference_edges():
    chunk = AdapterChunk(
        text="[113:1] Say, I seek refuge in the Lord of daybreak.",
        source_location={"page": 1},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
    )

    annotated = MinerURelationshipBuilder().annotate(
        [chunk],
        quran_metadata(edge_types=["contains"]),
    )

    assert annotated[0].metadata["relationship_metadata"]["references"] == ["113:1"]
    assert annotated[0].metadata["relationship_metadata"]["graph_relationships"] == []


def test_mineru_relationship_builder_respects_reference_only_materialization():
    chunks = [
        AdapterChunk(
            text="[113:1] Say, I seek refuge in the Lord of daybreak.",
            source_location={"page": 1},
            metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
        ),
        AdapterChunk(
            text="[113:2] From the evil of that which He created.",
            source_location={"page": 1},
            metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 1}},
        ),
    ]

    annotated = MinerURelationshipBuilder().annotate(
        chunks,
        quran_metadata(
            edge_types=["references", "next_reference", "next_chunk"],
            materialize_from=["reference_metadata"],
        ),
    )

    relationships = annotated[0].metadata["relationship_metadata"]["graph_relationships"]
    assert {
        "type": "next_reference",
        "source": "ref:113:1",
        "target": "ref:113:2",
        "evidence": "reference_metadata",
    } in relationships
    assert all(relationship["evidence"] != "mineru_order" for relationship in relationships)


def test_mineru_relationship_builder_does_not_emit_mineru_order_for_fallback_chunks():
    chunks = [
        AdapterChunk(
            text="[113:1] Say, I seek refuge in the Lord of daybreak.",
            source_location={"page": 1},
            metadata={"parser_metadata": {"backend": "fallback", "chunk_index": 0}},
        ),
        AdapterChunk(
            text="[113:2] From the evil of that which He created.",
            source_location={"page": 1},
            metadata={"parser_metadata": {"backend": "fallback", "chunk_index": 1}},
        ),
    ]

    annotated = MinerURelationshipBuilder().annotate(
        chunks,
        quran_metadata(edge_types=["references", "next_reference", "next_chunk"]),
    )

    relationships = annotated[0].metadata["relationship_metadata"]["graph_relationships"]
    assert {
        "type": "references",
        "source": "chunk:0",
        "target": "ref:113:1",
        "evidence": "reference_metadata",
    } in relationships
    assert all(relationship["evidence"] != "mineru_order" for relationship in relationships)


def test_mineru_relationship_builder_merges_existing_relationship_metadata():
    chunk = AdapterChunk(
        text="[113:1] Say, I seek refuge in the Lord of daybreak.",
        source_location={"page": 1},
        metadata={
            "parser_metadata": {"backend": "mineru", "chunk_index": 0},
            "relationship_metadata": {
                "references": ["existing:1"],
                "graph_relationships": [
                    {
                        "type": "custom",
                        "source": "chunk:legacy",
                        "target": "ref:existing:1",
                        "evidence": "existing",
                    }
                ],
                "note": "keep me",
            },
        },
    )

    annotated = MinerURelationshipBuilder().annotate(
        [chunk],
        quran_metadata(edge_types=["references"]),
    )

    metadata = annotated[0].metadata["relationship_metadata"]
    assert metadata["references"] == ["existing:1", "113:1"]
    assert metadata["note"] == "keep me"
    assert {
        "type": "custom",
        "source": "chunk:legacy",
        "target": "ref:existing:1",
        "evidence": "existing",
    } in metadata["graph_relationships"]
    assert {
        "type": "references",
        "source": "chunk:0",
        "target": "ref:113:1",
        "evidence": "reference_metadata",
    } in metadata["graph_relationships"]


def test_mineru_relationship_builder_leaves_chunks_without_graph_profile_unchanged():
    chunk = AdapterChunk(
        text="[1:1] In the name of Allah.",
        source_location={"page": 1},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
    )

    annotated = MinerURelationshipBuilder().annotate([chunk], DomainMetadata())

    assert annotated == [chunk]


def test_mineru_relationship_builder_requires_evidence_policy():
    metadata = quran_metadata()
    custom_json = dict(metadata.custom_json)
    graph = dict(custom_json["graph"])
    graph.pop("confidence_policy")
    custom_json["graph"] = graph
    unsafe_metadata = metadata.model_copy(update={"custom_json": custom_json})
    chunk = AdapterChunk(
        text="[1:1] In the name of Allah.",
        source_location={"page": 1},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
    )

    annotated = MinerURelationshipBuilder().annotate([chunk], unsafe_metadata)

    assert annotated == [chunk]
