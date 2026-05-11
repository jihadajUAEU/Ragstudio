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
            IndexDocumentIn(
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


@pytest.mark.asyncio
async def test_persist_chunks_prefers_direct_adapter_fields(tmp_path, database_url):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        document = Document(
            id="doc-fields",
            filename="fields.pdf",
            content_type="application/pdf",
            sha256="fields-sha",
            artifact_path=str(tmp_path / "fields.pdf"),
            status="running",
        )
        session.add(document)
        await session.commit()

        chunks = await ChunkPersistenceService(session).persist(
            document,
            [
                AdapterChunk(
                    text="field chunk",
                    source_location={"page": 2},
                    metadata={
                        "parser_metadata": {"backend": "mineru"},
                        "runtime_source_id": "metadata-source",
                        "content_type": "metadata/content",
                        "preview_ref": "metadata-preview",
                    },
                    runtime_source_id="direct-source",
                    content_type="direct/content",
                    preview_ref="direct-preview",
                )
            ],
            IndexDocumentIn(parser_mode="mineru_strict"),
            commit=True,
            runtime_profile_id="profile\x00id",
        )

        persisted = await session.get(Chunk, chunks[0].id)

    await engine.dispose()

    assert persisted is not None
    assert persisted.runtime_profile_id == "profileid"
    assert persisted.runtime_source_id == "direct-source"
    assert persisted.content_type == "direct/content"
    assert persisted.preview_ref == "direct-preview"
    assert chunks[0].runtime_profile_id == "profileid"
    assert chunks[0].runtime_source_id == "direct-source"
    assert chunks[0].content_type == "direct/content"
    assert chunks[0].preview_ref == "direct-preview"


@pytest.mark.asyncio
async def test_persist_chunks_scrubs_nested_absolute_metadata_paths(
    tmp_path,
    database_url,
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        document = Document(
            id="doc-paths",
            filename="paths.pdf",
            content_type="application/pdf",
            sha256="paths-sha",
            artifact_path=str(tmp_path / "paths.pdf"),
            status="running",
        )
        session.add(document)
        await session.commit()

        chunks = await ChunkPersistenceService(session).persist(
            document,
            [
                AdapterChunk(
                    text="path chunk",
                    source_location={"page": 3},
                    metadata={
                        "parser_metadata": {
                            "backend": "mineru",
                            "artifact_ref": "/tmp/private/pages/1.md",
                            "chunk_index": 3,
                            "artifact_extract_dir": "/tmp/ragstudio/extract",
                            "nested": {
                                "keep": "value",
                                "image_path": "/tmp/ragstudio/page.png",
                            },
                        },
                        "reference_metadata": {
                            "references": ["1:1"],
                            "evidence_path": "/tmp/ragstudio/evidence.json",
                        },
                        "chunk_identity": "doc-paths|/tmp/private/page.md|leak|3",
                        "preview_ref": "/tmp/private/preview",
                    },
                    preview_ref="/tmp/private/direct-preview",
                )
            ],
            IndexDocumentIn(parser_mode="mineru_strict"),
            commit=True,
        )

        persisted = await session.get(Chunk, chunks[0].id)

    await engine.dispose()

    assert persisted is not None
    parser_metadata = persisted.metadata_json["parser_metadata"]
    assert parser_metadata["nested"] == {"keep": "value"}
    assert parser_metadata["chunk_index"] == 3
    assert "artifact_ref" not in parser_metadata
    assert "artifact_extract_dir" not in parser_metadata
    assert persisted.metadata_json["reference_metadata"] == {"references": ["1:1"]}
    assert "preview_ref" not in persisted.metadata_json
    assert persisted.preview_ref is None
    assert chunks[0].preview_ref is None
    assert "/tmp" not in persisted.metadata_json["chunk_identity"]
    assert "/private" not in persisted.metadata_json["chunk_identity"]
    assert "/tmp" not in chunks[0].metadata["chunk_identity"]
    assert "/private" not in chunks[0].metadata["chunk_identity"]
