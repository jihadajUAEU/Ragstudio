import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document
from ragstudio.services.context_contracts import (
    ContextExpansionPolicy,
    context_policy_from_metadata,
)
from ragstudio.services.context_window_service import ContextWindowService
from ragstudio.services.retrieval_evidence import EvidenceCandidate


def test_context_policy_reads_verified_structural_links():
    policy = context_policy_from_metadata(
        {
            "context_contract": {
                "verified": True,
                "relationships": ["heading_path", "section_path", "reference_range"],
                "max_reference_distance": 2,
                "reference_unit_field": "item",
            }
        }
    )

    assert policy == ContextExpansionPolicy(
        relationships=frozenset({"heading_path", "section_path", "reference_range"}),
        max_reference_distance=2,
        reference_unit_field="item",
    )


def test_unverified_context_policy_uses_link_defaults():
    policy = context_policy_from_metadata(
        {"context_contract": {"verified": False, "relationships": ["heading_path"]}}
    )

    assert policy.relationships == frozenset({"reading_order", "parent", "sibling", "linked"})
    assert policy.max_reference_distance == 1


@pytest.mark.asyncio
async def test_context_window_service_returns_adjacent_reading_order_chunks(
    database_url, tmp_path
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        session.add(
            Document(
                id="doc-context-window",
                filename="context.pdf",
                content_type="application/pdf",
                sha256="context-sha",
                artifact_path=str(tmp_path / "context.pdf"),
            )
        )
        session.add_all(
            [
                Chunk(
                    id="prev",
                    document_id="doc-context-window",
                    text="Previous section defines the key term.",
                    source_location={"page": 1},
                    metadata_json={"reading_order": 1},
                ),
                Chunk(
                    id="seed",
                    document_id="doc-context-window",
                    text="Seed section answers the question.",
                    source_location={"page": 1},
                    metadata_json={"reading_order": 2},
                ),
                Chunk(
                    id="next",
                    document_id="doc-context-window",
                    text="Next section lists the exception.",
                    source_location={"page": 1},
                    metadata_json={"reading_order": 3},
                ),
            ]
        )
        await session.commit()
        seed = EvidenceCandidate(
            candidate_id="metadata:seed",
            text="Seed section answers the question.",
            document_id="doc-context-window",
            chunk_id="seed",
            source_location={"page": 1},
            metadata={"reading_order": 2},
            tool="metadata",
            tool_rank=1,
            base_score=10.0,
        )

        neighbors = await ContextWindowService(session).window_for(
            [seed],
            document_ids=["doc-context-window"],
            limit=4,
        )

    await engine.dispose()

    assert [candidate.chunk_id for candidate in neighbors] == ["prev", "next"]
    assert all("context_window" in candidate.reasons for candidate in neighbors)


@pytest.mark.asyncio
async def test_context_window_service_preserves_zero_based_reading_order(
    database_url, tmp_path
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        session.add(
            Document(
                id="doc-zero-context-window",
                filename="zero-context.pdf",
                content_type="application/pdf",
                sha256="zero-context-sha",
                artifact_path=str(tmp_path / "zero-context.pdf"),
            )
        )
        session.add_all(
            [
                Chunk(
                    id="zero-seed",
                    document_id="doc-zero-context-window",
                    text="First block answers the question.",
                    source_location={"page": 1},
                    metadata_json={"block_index": 0},
                ),
                Chunk(
                    id="zero-next",
                    document_id="doc-zero-context-window",
                    text="Second block adds context.",
                    source_location={"page": 1},
                    metadata_json={"block_index": 1},
                ),
            ]
        )
        await session.commit()
        seed = EvidenceCandidate(
            candidate_id="metadata:zero-seed",
            text="First block answers the question.",
            document_id="doc-zero-context-window",
            chunk_id="zero-seed",
            source_location={"page": 1},
            metadata={"block_index": 0},
            tool="metadata",
            tool_rank=1,
            base_score=10.0,
        )

        neighbors = await ContextWindowService(session).window_for(
            [seed],
            document_ids=["doc-zero-context-window"],
            limit=4,
        )

    await engine.dispose()

    assert [candidate.chunk_id for candidate in neighbors] == ["zero-next"]
    assert "reading_order_adjacent" in neighbors[0].reasons


@pytest.mark.asyncio
async def test_context_window_service_returns_parent_sibling_and_linked_context(
    database_url, tmp_path
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        session.add(
            Document(
                id="doc-linked-context-window",
                filename="linked-context.pdf",
                content_type="application/pdf",
                sha256="linked-context-sha",
                artifact_path=str(tmp_path / "linked-context.pdf"),
            )
        )
        session.add_all(
            [
                Chunk(
                    id="parent-context",
                    document_id="doc-linked-context-window",
                    text="Parent section heading.",
                    source_location={"page": 1},
                    metadata_json={},
                ),
                Chunk(
                    id="previous-context",
                    document_id="doc-linked-context-window",
                    text="Previous linked block.",
                    source_location={"page": 1},
                    metadata_json={},
                ),
                Chunk(
                    id="seed-linked-context",
                    document_id="doc-linked-context-window",
                    text="Seed child block.",
                    source_location={"page": 1},
                    metadata_json={"parent_chunk_id": "parent-context"},
                ),
                Chunk(
                    id="sibling-context",
                    document_id="doc-linked-context-window",
                    text="Sibling child block.",
                    source_location={"page": 1},
                    metadata_json={"parent_chunk_id": "parent-context"},
                ),
                Chunk(
                    id="next-context",
                    document_id="doc-linked-context-window",
                    text="Next linked block.",
                    source_location={"page": 1},
                    metadata_json={"previous_chunk_id": "seed-linked-context"},
                ),
            ]
        )
        await session.commit()
        seed = EvidenceCandidate(
            candidate_id="metadata:seed-linked-context",
            text="Seed child block.",
            document_id="doc-linked-context-window",
            chunk_id="seed-linked-context",
            source_location={"page": 1},
            metadata={
                "parent_chunk_id": "parent-context",
                "previous_chunk_id": "previous-context",
                "next_chunk_id": "next-context",
            },
            tool="metadata",
            tool_rank=1,
            base_score=10.0,
        )

        neighbors = await ContextWindowService(session).window_for(
            [seed],
            document_ids=["doc-linked-context-window"],
            limit=10,
        )

    await engine.dispose()

    by_id = {candidate.chunk_id: candidate for candidate in neighbors}
    assert set(by_id) == {
        "parent-context",
        "previous-context",
        "sibling-context",
        "next-context",
    }
    assert "parent_context" in by_id["parent-context"].reasons
    assert "linked_context" in by_id["previous-context"].reasons
    assert "sibling_context" in by_id["sibling-context"].reasons
    assert "linked_context" in by_id["next-context"].reasons


@pytest.mark.asyncio
async def test_context_window_service_returns_verified_structural_context(
    database_url, tmp_path
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        session.add(
            Document(
                id="doc-structural-context-window",
                filename="structural-context.pdf",
                content_type="application/pdf",
                sha256="structural-context-sha",
                artifact_path=str(tmp_path / "structural-context.pdf"),
            )
        )
        session.add_all(
            [
                Chunk(
                    id="seed-structural-context",
                    document_id="doc-structural-context-window",
                    text="Seed contract chunk.",
                    source_location={"page": 1},
                    metadata_json={
                        "heading_path": ["Part 1", "Section 2"],
                        "section_path": ["Part 1"],
                        "reference_identity_range": {
                            "item": {"start": 10, "end": 10},
                            "part": {"start": 1, "end": 1},
                        },
                        "context_contract": {
                            "verified": True,
                            "relationships": [
                                "heading_path",
                                "section_path",
                                "reference_range",
                            ],
                            "max_reference_distance": 2,
                            "reference_unit_field": "item",
                        },
                    },
                ),
                Chunk(
                    id="heading-context",
                    document_id="doc-structural-context-window",
                    text="Same heading context.",
                    source_location={"page": 2},
                    metadata_json={"heading_path": ["Part 1", "Section 2"]},
                ),
                Chunk(
                    id="section-context",
                    document_id="doc-structural-context-window",
                    text="Same section context.",
                    source_location={"page": 3},
                    metadata_json={"section_path": ["Part 1"]},
                ),
                Chunk(
                    id="reference-context",
                    document_id="doc-structural-context-window",
                    text="Nearby reference context.",
                    source_location={"page": 4},
                    metadata_json={
                        "reference_identity_range": {
                            "item": {"start": 12, "end": 12},
                            "part": {"start": 1, "end": 1},
                        }
                    },
                ),
                Chunk(
                    id="far-reference-context",
                    document_id="doc-structural-context-window",
                    text="Far reference should not be included.",
                    source_location={"page": 5},
                    metadata_json={
                        "reference_identity_range": {
                            "item": {"start": 20, "end": 20},
                            "part": {"start": 1, "end": 1},
                        }
                    },
                ),
                Chunk(
                    id="different-parent-reference-context",
                    document_id="doc-structural-context-window",
                    text="Same unit in a different parent should not be included.",
                    source_location={"page": 6},
                    metadata_json={
                        "reference_identity_range": {
                            "item": {"start": 10, "end": 10},
                            "part": {"start": 2, "end": 2},
                        }
                    },
                ),
            ]
        )
        await session.commit()
        seed = EvidenceCandidate(
            candidate_id="metadata:seed-structural-context",
            text="Seed contract chunk.",
            document_id="doc-structural-context-window",
            chunk_id="seed-structural-context",
            source_location={"page": 1},
            metadata={
                "heading_path": ["Part 1", "Section 2"],
                "section_path": ["Part 1"],
                "reference_identity_range": {
                    "item": {"start": 10, "end": 10},
                    "part": {"start": 1, "end": 1},
                },
                "context_contract": {
                    "verified": True,
                    "relationships": ["heading_path", "section_path", "reference_range"],
                    "max_reference_distance": 2,
                    "reference_unit_field": "item",
                },
            },
            tool="metadata",
            tool_rank=1,
            base_score=10.0,
        )

        neighbors = await ContextWindowService(session).window_for(
            [seed],
            document_ids=["doc-structural-context-window"],
            limit=10,
        )

    await engine.dispose()

    by_id = {candidate.chunk_id: candidate for candidate in neighbors}
    assert set(by_id) == {"heading-context", "section-context", "reference-context"}
    assert "heading_path_context" in by_id["heading-context"].reasons
    assert "section_path_context" in by_id["section-context"].reasons
    assert "reference_range_context" in by_id["reference-context"].reasons
