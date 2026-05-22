import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document
from ragstudio.services.layout_neighbor_service import LayoutNeighborService


@pytest.mark.asyncio
async def test_layout_neighbor_service_returns_same_reference_and_page_neighbors(
    database_url, tmp_path
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        session.add(
            Document(
                id="doc-layout-neighbor",
                filename="layout.pdf",
                content_type="application/pdf",
                sha256="layout-sha",
                artifact_path=str(tmp_path / "layout.pdf"),
            )
        )
        session.add_all(
            [
                Chunk(
                    id="seed",
                    document_id="doc-layout-neighbor",
                    text="Caption for figure.",
                    source_location={"page": 4, "reference": "1:5"},
                    metadata_json={"reference_metadata": {"references": ["1:5"]}},
                ),
                Chunk(
                    id="same-ref",
                    document_id="doc-layout-neighbor",
                    text="Body explains the figure.",
                    source_location={"page": 4, "reference": "1:5"},
                    metadata_json={
                        "reference_metadata": {"references": ["1:5"]},
                        "provenance": {"blocks": [{"role": "body"}]},
                    },
                ),
                Chunk(
                    id="blocked",
                    document_id="doc-layout-neighbor",
                    text="Blocked neighbor.",
                    source_location={"page": 4, "reference": "1:5"},
                    metadata_json={"quality_action_policy": {"action": "block"}},
                ),
                Chunk(
                    id="other-page",
                    document_id="doc-layout-neighbor",
                    text="Far evidence.",
                    source_location={"page": 8, "reference": "9:9"},
                    metadata_json={},
                ),
            ]
        )
        await session.commit()

        neighbors = await LayoutNeighborService(session).neighbors_for(
            seed_chunk_ids=["seed"],
            document_ids=["doc-layout-neighbor"],
            limit=5,
        )

    await engine.dispose()

    assert [candidate.chunk_id for candidate in neighbors] == ["same-ref"]
    assert neighbors[0].retrieval_pass == "layout_neighbor"
    assert "layout_neighbor" in neighbors[0].reasons
    assert neighbors[0].metadata["evidence_context"]["layout_summary"] == (
        "text; page=4; role=body"
    )


@pytest.mark.asyncio
async def test_layout_neighbor_service_uses_seed_documents_when_scope_is_empty(
    database_url, tmp_path
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        session.add_all(
            [
                Document(
                    id="doc-seed",
                    filename="seed.pdf",
                    content_type="application/pdf",
                    sha256="seed-sha",
                    artifact_path=str(tmp_path / "seed.pdf"),
                ),
                Document(
                    id="doc-other",
                    filename="other.pdf",
                    content_type="application/pdf",
                    sha256="other-sha",
                    artifact_path=str(tmp_path / "other.pdf"),
                ),
            ]
        )
        session.add_all(
            [
                Chunk(
                    id="seed-empty-scope",
                    document_id="doc-seed",
                    text="Seed evidence.",
                    source_location={"page": 1, "reference": "1:5"},
                    metadata_json={"reference_metadata": {"references": ["1:5"]}},
                ),
                Chunk(
                    id="same-doc-neighbor",
                    document_id="doc-seed",
                    text="Same document neighbor.",
                    source_location={"page": 1, "reference": "1:5"},
                    metadata_json={"reference_metadata": {"references": ["1:5"]}},
                ),
                Chunk(
                    id="cross-doc-neighbor",
                    document_id="doc-other",
                    text="Cross document neighbor.",
                    source_location={"page": 1, "reference": "1:5"},
                    metadata_json={"reference_metadata": {"references": ["1:5"]}},
                ),
            ]
        )
        await session.commit()

        neighbors = await LayoutNeighborService(session).neighbors_for(
            seed_chunk_ids=["seed-empty-scope"],
            document_ids=[],
            limit=5,
        )

    await engine.dispose()

    assert [candidate.chunk_id for candidate in neighbors] == ["same-doc-neighbor"]


@pytest.mark.asyncio
async def test_layout_neighbor_service_returns_same_layout_group_caption(
    database_url, tmp_path
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        session.add(
            Document(
                id="doc-layout-group",
                filename="layout-group.pdf",
                content_type="application/pdf",
                sha256="layout-group-sha",
                artifact_path=str(tmp_path / "layout-group.pdf"),
            )
        )
        session.add_all(
            [
                Chunk(
                    id="seed-cell",
                    document_id="doc-layout-group",
                    text="Net revenue was 120.",
                    source_location={"page": 3, "bbox": [100, 200, 220, 240]},
                    metadata_json={
                        "layout_group_id": "table-7",
                        "layout_role": "table_cell",
                    },
                ),
                Chunk(
                    id="caption",
                    document_id="doc-layout-group",
                    text="Table 7. Consolidated revenue.",
                    source_location={"page": 8, "bbox": [90, 160, 300, 185]},
                    metadata_json={
                        "layout_group_id": "table-7",
                        "layout_role": "caption",
                    },
                ),
            ]
        )
        await session.commit()

        neighbors = await LayoutNeighborService(session).neighbors_for(
            seed_chunk_ids=["seed-cell"],
            document_ids=["doc-layout-group"],
            limit=5,
        )

    await engine.dispose()

    assert [candidate.chunk_id for candidate in neighbors] == ["caption"]
    assert "layout_group" in neighbors[0].reasons


@pytest.mark.asyncio
async def test_layout_neighbor_service_returns_reading_order_neighbors(
    database_url, tmp_path
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        session.add(
            Document(
                id="doc-reading-order",
                filename="reading-order.pdf",
                content_type="application/pdf",
                sha256="reading-order-sha",
                artifact_path=str(tmp_path / "reading-order.pdf"),
            )
        )
        session.add_all(
            [
                Chunk(
                    id="seed-reading-order",
                    document_id="doc-reading-order",
                    text="Seed table cell.",
                    source_location={"page": 3},
                    metadata_json={"reading_order": 5},
                ),
                Chunk(
                    id="prev-reading-order",
                    document_id="doc-reading-order",
                    text="Previous visual block.",
                    source_location={"page": 9},
                    metadata_json={"reading_order": 4},
                ),
                Chunk(
                    id="next-reading-order",
                    document_id="doc-reading-order",
                    text="Next visual block.",
                    source_location={"page": 10},
                    metadata_json={"reading_order": 6},
                ),
                Chunk(
                    id="far-reading-order",
                    document_id="doc-reading-order",
                    text="Far visual block.",
                    source_location={"page": 11},
                    metadata_json={"reading_order": 8},
                ),
            ]
        )
        await session.commit()

        neighbors = await LayoutNeighborService(session).neighbors_for(
            seed_chunk_ids=["seed-reading-order"],
            document_ids=["doc-reading-order"],
            limit=5,
        )

    await engine.dispose()

    assert {candidate.chunk_id for candidate in neighbors} == {
        "prev-reading-order",
        "next-reading-order",
    }
    assert all("reading_order_neighbor" in candidate.reasons for candidate in neighbors)
