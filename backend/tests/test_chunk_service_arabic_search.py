import json

import pytest
import pytest_asyncio
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document
from ragstudio.schemas.chunks import ChunkSearchIn
from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_service import ChunkService

ARABIC_SAMPLE = (
    "\u0648\u064e\u062d\u064e\u0646\u064e\u0627\u0646\u064b\u0627 "
    "\u0645\u0651\u0650\u0646 \u0644\u0651\u064e\u062f\u064f\u0646\u0651\u064e\u0627 "
    "\u0648\u064e\u0632\u064e\u0643\u064e\u0627\u0629\u064b\u0627"
)
ARABIC_SAMPLE_LONG = (
    f"{ARABIC_SAMPLE} "
    "\u0648\u064e\u0643\u064e\u0627\u0646\u064e \u062a\u064e\u0642\u0650\u064a\u0651\u064b\u0627"
)


@pytest_asyncio.fixture
async def session(database_url):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)
    async with factory() as session:
        yield session
    await engine.dispose()


class ArabicDocumentParser:
    async def parse(self, *_args, **_kwargs):
        return [
            AdapterChunk(
                text=ARABIC_SAMPLE,
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

    await engine.dispose()

    assert chunk is not None
    assert chunk.text_search_ar == (
        "\u0648\u062d\u0646\u0627\u0646\u0627 \u0645\u0646 "
        "\u0644\u062f\u0646\u0627 \u0648\u0632\u0643\u0627\u0629\u0627"
    )
    assert "\u0648\u062d\u0646\u0627\u0646\u0627" in chunk.tokens_ar
    assert "\u062d\u0646\u0627\u0646\u0627" in chunk.tokens_ar
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
                text=ARABIC_SAMPLE_LONG,
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
            ChunkSearchIn(
                query="\u0648\u062d\u0646\u0627\u0646\u0627",
                document_ids=["doc-quran"],
                limit=5,
            )
        )

    await engine.dispose()

    assert result.total == 1
    assert result.items[0].id == "chunk-19-13"
    assert result.items[0].metadata["text_search_ar"] == (
        "\u0648\u062d\u0646\u0627\u0646\u0627 \u0645\u0646 \u0644\u062f\u0646\u0627 "
        "\u0648\u0632\u0643\u0627\u0629\u0627 \u0648\u0643\u0627\u0646 \u062a\u0642\u064a\u0627"
    )
    assert "\u062d\u0646\u0627\u0646\u0627" in result.items[0].metadata["tokens_ar"]


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
                    text=ARABIC_SAMPLE,
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
    assert "\u0648\u062d\u0646\u0627\u0646\u0627" in chunks[0].metadata["tokens_ar"]


@pytest.mark.asyncio
async def test_chunk_service_assembles_canonical_references_before_modal_preprocessing(
    database_url,
    tmp_path,
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    arabic_body = "\u0642\u0627\u0644 \u0631\u0633\u0648\u0644 \u0627\u0644\u0644\u0647"
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": "Sunan Ibn Majah", "page_idx": 0},
                {"type": "text", "text": "Book 1, Hadith 1", "page_idx": 1},
                {"type": "text", "text": arabic_body, "page_idx": 1},
                {
                    "type": "text",
                    "text": "The Messenger of Allah said a short narration.",
                    "page_idx": 1,
                },
                {"type": "text", "text": "Book 1, Hadith 2", "page_idx": 1},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class FakeParser:
        async def parse(self, document, options, *, on_mineru_status=None):
            return [
                AdapterChunk(
                    text="fallback markdown should not be used",
                    source_location={"artifact": "source/auto/source.md"},
                    metadata={
                        "parser_metadata": {
                            "backend": "mineru",
                            "artifact_extract_dir": str(tmp_path),
                            "content_list_ref": "source_content_list.json",
                        }
                    },
                )
            ]

    metadata = DomainMetadata(
        domain="hadith",
        document_type="collection",
        tags=["hadith", "arabic", "english"],
        script="mixed",
        custom_json={
            "reference_schema": {
                "type": "book_hadith",
                "display": "Book {book}, Hadith {hadith}",
                "canonical_ref_template": "book:{book}:hadith:{hadith}",
            },
            "chunking": {"unit": "hadith", "preserve_parallel_text": True},
            "reference_resolution": {
                "enabled": True,
                "build_canonical_units": True,
                "carry_forward_body_blocks": True,
                "header_only_policy": "provenance_only",
                "continuation_policy": "until_next_reference",
                "max_page_gap": 2,
                "require_single_reference_per_answerable_chunk": True,
            },
            "provenance": {"preserve_original_blocks": True},
            "quality_policy": {
                "required_scripts": ["arabic"],
                "optional_scripts": ["latin"],
                "required_scripts_by_unit_role": {"hadith": ["arabic"]},
                "optional_scripts_by_unit_role": {"hadith": ["latin"]},
                "missing_optional_script_action": "no_warning",
                "missing_required_script_action": "warn",
                "materialization_policy": "allow_if_required_scripts_present",
            },
        },
    )

    async with factory() as session:
        document = Document(
            id="doc-canonical-hadith",
            filename="hadith.pdf",
            content_type="application/pdf",
            sha256="canonical-hadith-sha",
            artifact_path=str(tmp_path / "hadith.pdf"),
            status="ready",
        )
        session.add(document)
        await session.commit()

        chunks = await ChunkService(
            session,
            tmp_path,
            document_parser=FakeParser(),
        ).index_document(
            "doc-canonical-hadith",
            options=IndexDocumentIn(parser_mode="mineru_strict", domain_metadata=metadata),
        )

    await engine.dispose()

    assert chunks is not None
    answerable = [
        chunk
        for chunk in chunks
        if chunk.metadata.get("canonical_reference_unit", {}).get("answerable") is True
    ]
    assert len(answerable) == 1
    assert "Book 1, Hadith 1" in answerable[0].text
    assert arabic_body in answerable[0].text
    assert "The Messenger of Allah" in answerable[0].text
    assert answerable[0].metadata["reference_metadata"]["references"] == [
        "book:1:hadith:1"
    ]
    assert answerable[0].metadata.get("modal_router_processed") is None
    assert "reference_unit_missing_expected_script" not in {
        warning["code"]
        for warning in answerable[0].metadata.get("extraction_quality", {}).get(
            "parser_warnings", []
        )
    }
