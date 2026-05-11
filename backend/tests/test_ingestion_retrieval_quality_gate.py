import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Document
from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_lexical_search_repository import ChunkLexicalSearchRepository
from ragstudio.services.chunk_persistence_service import ChunkPersistenceService


@pytest.mark.asyncio
async def test_early_persisted_quran_chunks_support_arabic_lexical_retrieval(
    database_url,
    tmp_path,
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        document = Document(
            id="doc-quran-quality",
            filename="quran_arabic_english.pdf",
            content_type="application/pdf",
            sha256="quran-quality-sha",
            artifact_path=str(tmp_path / "quran.pdf"),
            status="running",
        )
        session.add(document)
        await session.commit()

        await ChunkPersistenceService(session).persist(
            document,
            [
                AdapterChunk(
                    text="[19:13] وَحَنَانًا مِّن لَّدُنَّا وَزَكَاةً",
                    source_location={"page": 312, "reference": "19:13"},
                    metadata={
                        "preview_ref": "19:13",
                        "reference_metadata": {"references": ["19:13"]},
                        "parser_metadata": {
                            "backend": "mineru",
                            "artifact_ref": "pages/312.md",
                            "chunk_index": 12,
                        },
                    },
                )
            ],
            options=IndexDocumentIn(
                parser_mode="mineru_strict",
                domain_metadata=DomainMetadata(domain="quran_tafseer", language="arabic"),
            ),
            commit=True,
        )

        results = await ChunkLexicalSearchRepository(session).arabic_prefilter(
            query="hannan حنانا",
            document_ids=["doc-quran-quality"],
            limit=5,
        )

    await engine.dispose()

    assert len(results) == 1
    assert results[0].preview_ref == "19:13"
    assert results[0].metadata_json["reference_metadata"]["references"] == ["19:13"]
    assert results[0].metadata_json["parser_metadata"]["backend"] == "mineru"
    assert results[0].metadata_json["domain_metadata"]["domain"] == "quran_tafseer"


@pytest.mark.asyncio
async def test_early_persisted_bukhari_chunks_keep_source_metadata(
    database_url,
    tmp_path,
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        document = Document(
            id="doc-bukhari-quality",
            filename="hadith_bukhari.pdf",
            content_type="application/pdf",
            sha256="bukhari-quality-sha",
            artifact_path=str(tmp_path / "bukhari.pdf"),
            status="running",
        )
        session.add(document)
        await session.commit()

        chunks = await ChunkPersistenceService(session).persist(
            document,
            [
                AdapterChunk(
                    text="Sahih al-Bukhari contains 7277 hadith.",
                    source_location={"page": 1, "section": "introduction"},
                    metadata={
                        "preview_ref": "page 1",
                        "parser_metadata": {
                            "backend": "mineru",
                            "artifact_ref": "pages/1.md",
                            "chunk_index": 0,
                        },
                    },
                )
            ],
            options=IndexDocumentIn(
                parser_mode="mineru_strict",
                domain_metadata=DomainMetadata(domain="hadith", language="english"),
            ),
            commit=True,
        )

    await engine.dispose()

    assert chunks[0].source_location["page"] == 1
    assert chunks[0].source_location["section"] == "introduction"
    assert chunks[0].metadata["domain_metadata"]["domain"] == "hadith"
    assert chunks[0].metadata["parser_metadata"]["backend"] == "mineru"
    assert chunks[0].metadata["chunk_identity"].startswith("doc-bukhari-quality|pages/1.md")
