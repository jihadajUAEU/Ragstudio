import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document
from ragstudio.services.context_window_service import ContextWindowService
from ragstudio.services.retrieval_evidence import EvidenceCandidate


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
