import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document
from ragstudio.services.arabic_text import arabic_tokens, normalize_arabic_text
from ragstudio.services.chunk_lexical_search_repository import ChunkLexicalSearchRepository


@pytest.mark.asyncio
async def test_repository_prefilters_arabic_token_with_postgres_columns(
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
        text = "وَحَنَانًا مِّن لَّدُنَّا وَزَكَاةً"
        session.add(document)
        session.add(
            Chunk(
                id="chunk-19-13",
                document_id="doc-quran",
                text=text,
                text_search_ar=normalize_arabic_text(text),
                tokens_ar=arabic_tokens(text),
                source_location={"page": 312},
                metadata_json={},
            )
        )
        await session.commit()

        chunks = await ChunkLexicalSearchRepository(session).arabic_prefilter(
            query="وحنانا",
            document_ids=["doc-quran"],
            limit=5,
        )

    assert [chunk.id for chunk in chunks] == ["chunk-19-13"]
