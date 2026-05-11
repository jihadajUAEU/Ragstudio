import pytest
import pytest_asyncio
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document
from ragstudio.schemas.chunks import ChunkSearchIn
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_service import ChunkService


@pytest_asyncio.fixture
async def session(database_url):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)
    async with factory() as session:
        yield session


class ArabicDocumentParser:
    async def parse(self, *_args, **_kwargs):
        return [
            AdapterChunk(
                text="وَحَنَانًا مِّن لَّدُنَّا وَزَكَاةً",
                source_location={"page": 312},
                metadata={
                    "backend": "mineru",
                    "extraction_quality": {"validated": True},
                },
            )
        ]

    async def validate_strict_mineru_sidecar(self, _options):
        return None


@pytest.mark.asyncio
async def test_chunk_persistence_materializes_arabic_search_fields(database_url, tmp_path):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        document = Document(
            id="doc-quran",
            filename="quran.pdf",
            content_type="application/pdf",
            sha256="sha",
            artifact_path=str(tmp_path / "quran.pdf"),
            status="ready",
        )
        session.add(document)
        await session.commit()

        chunks = await ChunkService(
            session,
            tmp_path,
            document_parser=ArabicDocumentParser(),
        ).index_document("doc-quran")

    assert chunks is not None
    assert chunks[0].metadata["document_id"] == "doc-quran"

    async with factory() as session:
        chunk = await session.get(Chunk, chunks[0].id)

    assert chunk is not None
    assert chunk.text_search_ar == "وحنانا من لدنا وزكاة"
    assert "وحنانا" in chunk.tokens_ar
    assert "حنانا" in chunk.tokens_ar
    assert chunk.extraction_quality == {"validated": True}


@pytest.mark.asyncio
async def test_chunk_search_matches_direct_legacy_chunk_with_generated_arabic_material(
    database_url,
    tmp_path,
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        document = Document(
            id="doc-quran",
            filename="quran.pdf",
            content_type="application/pdf",
            sha256="sha",
            artifact_path=str(tmp_path / "quran.pdf"),
            status="ready",
        )
        session.add(document)
        session.add(
            Chunk(
                id="chunk-19-13",
                document_id="doc-quran",
                text="وَحَنَانًا مِّن لَّدُنَّا وَزَكَاةً وَكَانَ تَقِيًّا",
                source_location={"page": 312},
                metadata_json={
                    "parser_metadata": {
                        "backend": "mineru",
                        "parser_mode": "mineru_strict",
                    }
                },
            )
        )
        await session.commit()

        result = await ChunkService(session, tmp_path).search(
            ChunkSearchIn(query="وحنانا", document_ids=["doc-quran"], limit=5)
        )

    assert result.total == 1
    assert result.items[0].id == "chunk-19-13"
    assert result.items[0].metadata["text_search_ar"] == "وحنانا من لدنا وزكاة وكان تقيا"
    assert "حنانا" in result.items[0].metadata["tokens_ar"]


@pytest.mark.asyncio
async def test_chunk_service_uses_shared_persistence_shape(session, tmp_path):
    document = Document(
        id="doc-shared-persistence",
        filename="quran.pdf",
        content_type="application/pdf",
        sha256="shared-persistence-sha",
        artifact_path=str(tmp_path / "quran.pdf"),
        status="ready",
    )
    session.add(document)
    await session.commit()

    class FakeParser:
        async def parse(self, document, options, *, on_mineru_status=None):
            return [
                AdapterChunk(
                    text="وَحَنَانًا مِّن لَّدُنَّا",
                    source_location={"page": 10},
                    metadata={"parser_metadata": {"backend": "mineru"}},
                )
            ]

    chunks = await ChunkService(
        session,
        tmp_path,
        document_parser=FakeParser(),
    ).index_document(
        "doc-shared-persistence",
        options=IndexDocumentIn(parser_mode="mineru_strict"),
    )

    assert chunks is not None
    assert chunks[0].metadata["document_id"] == "doc-shared-persistence"
    assert chunks[0].metadata["parser_metadata"]["parser_mode"] == "mineru_strict"
    assert "وحنانا" in chunks[0].metadata["tokens_ar"]
