import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document
from ragstudio.services.arabic_text import arabic_tokens, normalize_arabic_text
from ragstudio.services.chunk_lexical_search_repository import ChunkLexicalSearchRepository
from sqlalchemy import text


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


@pytest.mark.asyncio
async def test_repository_reference_prefilter_uses_document_reference_contract(
    database_url,
    tmp_path,
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        document = Document(
            id="doc-archive",
            filename="archive.pdf",
            content_type="application/pdf",
            sha256="archive-sha",
            artifact_path=str(tmp_path / "archive.pdf"),
            status="ready",
            index_contract={
                "reference_contract": {
                    "verified": True,
                    "canonical_ref_template": "article:{article}:clause:{clause}",
                    "anchors": [
                        {
                            "kind": "primary_anchor",
                            "regex": r"Article\s+(?P<article>\d+)\.(?P<clause>\d+)",
                        }
                    ],
                }
            },
        )
        session.add(document)
        session.add(
            Chunk(
                id="chunk-article-12-7",
                document_id="doc-archive",
                text="Article 12.7 The procedure starts here.",
                source_location={"page": 4},
                metadata_json={"reference_metadata": {"references": ["article:12:clause:7"]}},
                preview_ref="article:12:clause:7",
            )
        )
        await session.commit()

        chunks = await ChunkLexicalSearchRepository(session).reference_prefilter(
            query="show Article 12.7",
            document_ids=["doc-archive"],
            limit=5,
        )

    assert [chunk.id for chunk in chunks] == ["chunk-article-12-7"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_init_db_creates_english_text_trigram_index(database_url):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        indexdef = await session.scalar(
            text(
                """
                SELECT indexdef
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND tablename = 'chunks'
                  AND indexname = 'ix_chunks_text_trgm'
                """
            )
        )

    assert indexdef is not None
    assert "USING gin" in indexdef
    assert "text gin_trgm_ops" in indexdef
    await engine.dispose()
