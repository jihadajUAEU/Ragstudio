import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document
from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_persistence_service import ChunkPersistenceService


@pytest.mark.asyncio
async def test_persist_chunks_materializes_search_fields(tmp_path, database_url):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        document = Document(
            id="doc-quran",
            filename="quran.pdf",
            content_type="application/pdf",
            sha256="quran-sha",
            artifact_path=str(tmp_path / "quran.pdf"),
            status="running",
        )
        session.add(document)
        await session.commit()

        chunks = await ChunkPersistenceService(session).persist(
            document,
            [
                AdapterChunk(
                    text="[19:13] وَحَنَانًا مِّن لَّدُنَّا وَزَكَاةً",
                    source_location={"page": 10, "reference": "19:13"},
                    metadata={
                        "parser_metadata": {
                            "backend": "mineru",
                            "parser_mode": "mineru_strict",
                        },
                        "reference_metadata": {"references": ["19:13"]},
                        "preview_ref": "19:13",
                    },
                )
            ],
            options=IndexDocumentIn(
                parser_mode="mineru_strict",
                domain_metadata=DomainMetadata(domain="quran_tafseer", language="arabic"),
            ),
            commit=True,
        )

        persisted = await session.get(Chunk, chunks[0].id)

    await engine.dispose()

    assert persisted is not None
    assert persisted.document_id == "doc-quran"
    assert persisted.preview_ref == "19:13"
    assert persisted.text_search_ar == "[19:13] وحنانا من لدنا وزكاة"
    assert "وحنانا" in persisted.tokens_ar
    assert persisted.metadata_json["domain_metadata"]["domain"] == "quran_tafseer"
    assert persisted.metadata_json["parser_metadata"]["backend"] == "mineru"
    assert persisted.metadata_json["chunk_identity"].startswith("doc-quran|")


@pytest.mark.asyncio
async def test_persist_chunks_replaces_existing_chunks(tmp_path, database_url):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        document = Document(
            id="doc-bukhari",
            filename="hadith_bukhari.pdf",
            content_type="application/pdf",
            sha256="bukhari-sha",
            artifact_path=str(tmp_path / "bukhari.pdf"),
            status="running",
        )
        session.add(document)
        session.add(
            Chunk(
                document_id="doc-bukhari",
                text="old chunk",
                source_location={},
                metadata_json={"old": True},
            )
        )
        await session.commit()

        chunks = await ChunkPersistenceService(session).persist(
            document,
            [
                AdapterChunk(
                    text="new chunk",
                    source_location={"page": 1},
                    metadata={"parser_metadata": {"backend": "mineru"}},
                )
            ],
            options=IndexDocumentIn(parser_mode="mineru_strict"),
            commit=True,
        )

        rows = (
            await session.execute(
                Chunk.__table__.select().where(Chunk.document_id == "doc-bukhari")
            )
        ).all()

    await engine.dispose()

    assert len(chunks) == 1
    assert len(rows) == 1
    assert rows[0]._mapping["text"] == "new chunk"
    assert rows[0]._mapping["metadata_json"]["chunk_identity"].startswith("doc-bukhari|")
