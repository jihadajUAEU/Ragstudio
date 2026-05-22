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


@pytest.mark.asyncio
async def test_vector_candidate_repository_attaches_evidence_context(database_url, tmp_path):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        doc = Document(
            id="doc-context",
            filename="context.txt",
            content_type="text/plain",
            sha256="context-sha",
            artifact_path=str(tmp_path / "context.txt"),
        )
        session.add(doc)
        chunk = Chunk(
            id="chunk-context",
            document_id=doc.id,
            text="alpha contextual answer",
            source_location={"page": 1},
            content_type="text",
            metadata_json={
                "document_metadata": {"title": "Synthetic Tafseer"},
                "reference_metadata": {"references": ["1:5"]},
            },
        )
        session.add(chunk)
        await session.commit()

        rows = await VectorCandidateRepository(session).candidate_rows(
            query="alpha",
            document_ids=[doc.id],
            limit=10,
        )

    await engine.dispose()

    assert rows[0]["metadata"]["evidence_context"] == {
        "breadcrumb": "Synthetic Tafseer > 1:5",
        "layout_summary": "text; page=1",
        "page": 1,
        "reference": "1:5",
    }
