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
