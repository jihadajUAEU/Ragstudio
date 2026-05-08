import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document
from ragstudio.schemas.chunks import ChunkSearchIn
from ragstudio.services.chunk_service import ChunkService


@pytest.mark.asyncio
async def test_arabic_phrase_search_matches_indexed_chunk(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'studio.sqlite3'}")
    session_factory = make_session_factory(engine)
    await init_db(engine)

    async with session_factory() as session:
        document = Document(
            filename="quran_arabic_english.pdf",
            content_type="application/pdf",
            sha256="arabic-search-sha",
            artifact_path=str(tmp_path / "quran.pdf"),
            status="succeeded",
        )
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                document_id=document.id,
                text="الذين يؤمنون بما أنزل إليك وما أنزل من قبلك",
                source_location={"page": 2},
                metadata_json={
                    "domain_metadata": {"domain": "religious_text"},
                    "parser_metadata": {"backend": "mineru", "parser_mode": "mineru_strict"},
                },
            )
        )
        await session.commit()

        result = await ChunkService(session, tmp_path).search(
            ChunkSearchIn(
                query="الذين يؤمنون بما أنزل",
                document_ids=[document.id],
                limit=5,
            )
        )

    await engine.dispose()

    assert result.total == 1
    assert "بما أنزل" in result.items[0].text
    assert result.items[0].metadata["parser_metadata"]["backend"] == "mineru"
