import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document
from ragstudio.services.vector_candidate_repository import VectorCandidateRepository


@pytest.mark.asyncio
async def test_vector_candidate_repository_filters_quality_blocked_chunks(database_url, tmp_path):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        doc = Document(
            id="doc-vector",
            filename="vector.txt",
            content_type="text/plain",
            sha256="vector-sha",
            artifact_path=str(tmp_path / "vector.txt"),
        )
        session.add(doc)
        session.add_all(
            [
                Chunk(
                    id="chunk-allowed",
                    document_id=doc.id,
                    text="alpha allowed answer",
                    metadata_json={"quality_action_policy": {"index_vector": True}},
                ),
                Chunk(
                    id="chunk-blocked",
                    document_id=doc.id,
                    text="alpha blocked answer",
                    metadata_json={"quality_action_policy": {"index_vector": False}},
                ),
            ]
        )
        await session.commit()

        rows = await VectorCandidateRepository(session).candidate_rows(
            query="alpha",
            document_ids=[doc.id],
            limit=10,
        )

    await engine.dispose()

    assert [row["chunk_id"] for row in rows] == ["chunk-allowed"]
    assert rows[0]["metadata"]["quality_action_policy"]["index_vector"] is True
