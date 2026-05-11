import pytest
import pytest_asyncio
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document
from ragstudio.schemas.chunks import ChunkSearchIn
from ragstudio.services.arabic_text import arabic_tokens, normalize_arabic_text
from ragstudio.services.chunk_service import ChunkService
from sqlalchemy import select


@pytest_asyncio.fixture
async def session(database_url):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)
    async with factory() as session:
        yield session


@pytest.mark.asyncio
async def test_indexed_quran_hanana_chunk_is_searchable(session, tmp_path):
    document = Document(
        id="quran-doc",
        filename="quran_arabic_english.pdf",
        content_type="application/pdf",
        sha256="quran-sha",
        artifact_path=str(tmp_path / "quran_arabic_english.pdf"),
        status="succeeded",
    )
    text = "[19:13]\n\nوَحَنَانًا مِّن لَّدُنَّا وَزَكَاةً\n\nAnd affection from Us and purity."  # noqa: RUF001
    session.add(document)
    session.add(
        Chunk(
            id="quran-19-13",
            document_id=document.id,
            text=text,
            source_location={"page": 312, "reference": "19:13"},
            metadata_json={
                "reference_metadata": {"references": ["19:13"]},
                "parser_metadata": {"backend": "mineru"},
            },
            text_search_ar=normalize_arabic_text(text),
            tokens_ar=arabic_tokens(text),
        )
    )
    await session.commit()

    stored = await session.scalar(select(Chunk).where(Chunk.id == "quran-19-13"))
    assert stored is not None
    assert "حنانا" in stored.tokens_ar

    result = await ChunkService(session, tmp_path).search(
        ChunkSearchIn(
            query="حنانا",
            document_ids=[document.id],
            limit=5,
            explain=True,
            include_neighbors=True,
        )
    )

    assert result.total == 1
    assert result.items[0].id == "quran-19-13"
    assert result.items[0].source_location["reference"] == "19:13"
