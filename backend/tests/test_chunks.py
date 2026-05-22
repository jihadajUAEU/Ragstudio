import json

import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document
from ragstudio.schemas.chunks import ChunkSearchIn
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.chunk_sanitizer import sanitize_db_value
from ragstudio.services.chunk_service import ChunkService
from ragstudio.services.chunk_splitter import ChunkSplitter


def test_chunk_splitter_splits_mineru_content_list_by_reference_units(tmp_path):
    content_list = tmp_path / "content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {
                    "page_idx": 0,
                    "text": "[113:1] Say, I seek refuge in the Lord of daybreak.",
                },
                {
                    "page_idx": 0,
                    "text": "[113:2] From the evil of that which He created.",
                },
            ]
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="ignored when content_list_ref is available",
        source_location={"artifact": "quran.pdf"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "content_list.json",
                "chunk_index": 0,
            }
        },
    )

    chunks = ChunkSplitter().split(
        [chunk],
        domain_metadata=DomainMetadata(
            domain="quran_tafseer",
            document_type="commentary",
            custom_json={
                "reference_schema": {"type": "chapter_verse"},
                "chunking": {"unit": "verse"},
            },
        ),
        parser_mode="mineru_strict",
    )

    assert [item.text for item in chunks] == [
        "[113:1] Say, I seek refuge in the Lord of daybreak.",
        "[113:2] From the evil of that which He created.",
    ]
    assert [item.metadata["reference_metadata"]["references"] for item in chunks] == [
        ["113:1"],
        ["113:2"],
    ]
    assert all(item.source_location["page_start"] == 1 for item in chunks)


def test_sanitize_db_value_converts_json_unsafe_values(tmp_path):
    payload = {
        "path": tmp_path / "artifact.txt",
        "set": {"a", "b"},
        "tuple": ("x", 1),
        "nested": {"bytes": b"abc"},
    }

    sanitized = sanitize_db_value(payload)

    assert sanitized["path"] == str(tmp_path / "artifact.txt")
    assert sanitized["set"] in {"{'a', 'b'}", "{'b', 'a'}"}
    assert sanitized["tuple"] == ["x", 1]
    assert sanitized["nested"]["bytes"] == "abc"


@pytest.mark.asyncio
async def test_domain_metadata_for_documents_dedupes_and_copies(
    database_url,
    tmp_path,
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    repeated_metadata = {
        "domain": "quran_tafseer",
        "language": "arabic",
        "nested": {"reference_schema": "chapter_verse"},
    }
    different_metadata = {
        "domain": "hadith",
        "language": "arabic",
        "nested": {"reference_schema": "book_hadith"},
    }

    async with factory() as session:
        session.add_all(
            [
                Document(
                    id="doc-a",
                    filename="a.pdf",
                    content_type="application/pdf",
                    sha256="sha-a",
                    artifact_path=str(tmp_path / "a.pdf"),
                ),
                Document(
                    id="doc-b",
                    filename="b.pdf",
                    content_type="application/pdf",
                    sha256="sha-b",
                    artifact_path=str(tmp_path / "b.pdf"),
                ),
                Chunk(
                    id="chunk-a-1",
                    document_id="doc-a",
                    text="A first chunk",
                    metadata_json={"domain_metadata": repeated_metadata},
                ),
                Chunk(
                    id="chunk-a-2",
                    document_id="doc-a",
                    text="A repeated metadata chunk",
                    metadata_json={"domain_metadata": dict(repeated_metadata)},
                ),
                Chunk(
                    id="chunk-b-1",
                    document_id="doc-b",
                    text="B different metadata chunk",
                    metadata_json={"domain_metadata": different_metadata},
                ),
                Chunk(
                    id="chunk-b-2",
                    document_id="doc-b",
                    text="B no metadata chunk",
                    metadata_json={"parser_metadata": {"backend": "mineru"}},
                ),
            ]
        )
        await session.commit()

        assert await ChunkService(session, tmp_path).domain_metadata_for_documents([]) == []

        result = await ChunkService(session, tmp_path).domain_metadata_for_documents(
            ["doc-b", "doc-a", "doc-b"]
        )

        assert result == [
            {
                **different_metadata,
                "document_id": "doc-b",
            },
            {
                **repeated_metadata,
                "document_id": "doc-a",
            },
        ]

        result[1]["nested"]["reference_schema"] = "mutated"
        stored = await session.get(Chunk, "chunk-a-1")

    await engine.dispose()

    assert stored is not None
    assert (
        stored.metadata_json["domain_metadata"]["nested"]["reference_schema"]
        == "chapter_verse"
    )


@pytest.mark.asyncio
async def test_domain_metadata_for_documents_prefers_document_index_contract(
    database_url,
    tmp_path,
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        doc = Document(
            id="doc-contract-route",
            filename="contract.txt",
            content_type="text/plain",
            sha256="contract-route-sha",
            artifact_path=str(tmp_path / "contract.txt"),
            index_contract={
                "contract_status": "compiled_reference_contract",
                "domain_metadata": {
                    "domain": "quran_tafseer",
                    "language": "arabic",
                    "custom_json": {
                        "reference_schema": {"type": "chapter_verse"},
                        "reference_resolution": {"build_canonical_units": True},
                    },
                },
            },
        )
        session.add(doc)
        session.add(
            Chunk(
                id="chunk-generic-old",
                document_id=doc.id,
                text="old generic chunk",
                metadata_json={"domain_metadata": {"domain": "generic"}},
            )
        )
        await session.commit()

        metadata = await ChunkService(session, tmp_path).domain_metadata_for_documents(
            [doc.id]
        )

    await engine.dispose()

    assert metadata == [
        {
            "domain": "quran_tafseer",
            "language": "arabic",
            "custom_json": {
                "reference_schema": {"type": "chapter_verse"},
                "reference_resolution": {"build_canonical_units": True},
            },
            "document_id": "doc-contract-route",
            "contract_status": "compiled_reference_contract",
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("unsafe_value", "unsafe_key"),
    [
        ("/var/private/ragstudio/artifacts/a.pdf", "source_root"),
        ("C:\\Users\\meet\\Ragstudio\\artifacts\\a.pdf", "source_root"),
    ],
)
async def test_domain_metadata_for_documents_removes_absolute_path_values(
    database_url,
    tmp_path,
    unsafe_value,
    unsafe_key,
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    domain_metadata = {
        "domain": "quran_tafseer",
        "language": "arabic",
        unsafe_key: unsafe_value,
        "tags": ["reference", unsafe_value],
        "custom_json": {
            "reference_schema": {"type": "chapter_verse"},
            "examples": ["safe-example", unsafe_value],
        },
    }

    async with factory() as session:
        session.add_all(
            [
                Document(
                    id="doc-path-value",
                    filename="path-value.pdf",
                    content_type="application/pdf",
                    sha256=f"sha-{unsafe_key}",
                    artifact_path=str(tmp_path / "path-value.pdf"),
                ),
                Chunk(
                    id="chunk-path-value",
                    document_id="doc-path-value",
                    text="A chunk with path-like domain metadata",
                    metadata_json={"domain_metadata": domain_metadata},
                ),
            ]
        )
        await session.commit()

        result = await ChunkService(session, tmp_path).domain_metadata_for_documents(
            ["doc-path-value"]
        )

    await engine.dispose()

    assert result == [
        {
            "domain": "quran_tafseer",
            "language": "arabic",
            "tags": ["reference"],
            "custom_json": {
                "reference_schema": {"type": "chapter_verse"},
                "examples": ["safe-example"],
            },
            "document_id": "doc-path-value",
        }
    ]


@pytest.mark.asyncio
async def test_domain_metadata_for_documents_removes_nested_path_keys(
    database_url,
    tmp_path,
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    domain_metadata = {
        "domain": "hadith",
        "document_type": "collection",
        "custom_json": {
            "path": "relative/path/is-removed-by-key.pdf",
            "reference_schema": {
                "type": "book_hadith",
                "file_path": "relative/hadith-source.json",
                "fields": {"book": "book", "hadith": "hadith"},
            },
            "evidence": [
                {"page": 1, "artifact_path": "relative/page-1.json"},
                {"page": 2, "observation": "safe"},
            ],
            "layout": {
                "preview_path": "relative/preview.png",
                "role": "parallel_text",
            },
        },
    }

    async with factory() as session:
        session.add_all(
            [
                Document(
                    id="doc-path-key",
                    filename="path-key.pdf",
                    content_type="application/pdf",
                    sha256="sha-path-key",
                    artifact_path=str(tmp_path / "path-key.pdf"),
                ),
                Chunk(
                    id="chunk-path-key",
                    document_id="doc-path-key",
                    text="A chunk with nested path keys",
                    metadata_json={"domain_metadata": domain_metadata},
                ),
            ]
        )
        await session.commit()

        result = await ChunkService(session, tmp_path).domain_metadata_for_documents(
            ["doc-path-key"]
        )

    await engine.dispose()

    assert result == [
        {
            "domain": "hadith",
            "document_type": "collection",
            "custom_json": {
                "reference_schema": {
                    "type": "book_hadith",
                    "fields": {"book": "book", "hadith": "hadith"},
                },
                "evidence": [{"page": 1}, {"page": 2, "observation": "safe"}],
                "layout": {"role": "parallel_text"},
            },
            "document_id": "doc-path-key",
        }
    ]


@pytest.mark.asyncio
async def test_search_scores_full_scope_after_english_prefilter(
    database_url,
    tmp_path,
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        document = Document(
            id="doc-english-prefilter",
            filename="prefilter.txt",
            content_type="text/plain",
            sha256="prefilter-sha",
            artifact_path=str(tmp_path / "prefilter.txt"),
            status="succeeded",
        )
        session.add(document)
        await session.flush()
        session.add_all(
            [
                Chunk(
                    id=f"weak-prefilter-{index}",
                    document_id=document.id,
                    text=f"offering filler {index} sacrifice id adha",
                    metadata_json={},
                    source_location={},
                )
                for index in range(25)
            ]
        )
        session.add(
            Chunk(
                id="target-after-prefilter-window",
                document_id=document.id,
                text="offering sacrifice eid",
                metadata_json={},
                source_location={},
            )
        )
        await session.commit()

        result = await ChunkService(session, tmp_path).search(
            ChunkSearchIn(
                query="offering sacrifice eid",
                document_ids=[document.id],
                limit=1,
            )
        )

    await engine.dispose()

    assert [item.id for item in result.items] == ["target-after-prefilter-window"]


@pytest.mark.asyncio
async def test_search_fallback_reports_bounded_ranked_candidate_set(
    database_url,
    tmp_path,
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        document = Document(
            id="doc-search-fallback-bounded",
            filename="fallback-bounded.txt",
            content_type="text/plain",
            sha256="fallback-bounded-sha",
            artifact_path=str(tmp_path / "fallback-bounded.txt"),
            status="succeeded",
        )
        session.add(document)
        await session.flush()
        session.add_all(
            [
                Chunk(
                    id=f"chunk-fallback-{index:03d}",
                    document_id=document.id,
                    text=f"body without query terms {index}",
                    metadata_json={
                        "chunk_index": index,
                        "domain_metadata": {"tags": ["metadataonly"]},
                    },
                    source_location={},
                )
                for index in range(125)
            ]
        )
        await session.commit()

        result = await ChunkService(session, tmp_path).search(
            ChunkSearchIn(
                query="metadataonly",
                document_ids=[document.id],
                limit=10,
            )
        )

    await engine.dispose()

    assert result.total == 100
    assert result.has_more is True
    assert len(result.items) == 10
    assert [item.id for item in result.items] == [
        f"chunk-fallback-{index:03d}" for index in range(10)
    ]


@pytest.mark.asyncio
async def test_search_paginates_ranked_results_and_returns_total(
    database_url,
    tmp_path,
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        document = Document(
            id="doc-search-pagination",
            filename="pagination.txt",
            content_type="text/plain",
            sha256="pagination-sha",
            artifact_path=str(tmp_path / "pagination.txt"),
            status="succeeded",
        )
        session.add(document)
        await session.flush()
        session.add_all(
            [
                Chunk(
                    id=f"chunk-page-{index}",
                    document_id=document.id,
                    text="needle shared term",
                    metadata_json={"chunk_index": index},
                    source_location={},
                )
                for index in range(3)
            ]
        )
        await session.commit()

        result = await ChunkService(session, tmp_path).search(
            ChunkSearchIn(
                query="needle shared",
                document_ids=[document.id],
                limit=1,
                offset=1,
            )
        )

    await engine.dispose()

    assert result.total == 3
    assert result.has_more is True
    assert [item.id for item in result.items] == ["chunk-page-1"]


@pytest.mark.asyncio
async def test_search_route_reads_pagination_from_request_body(client, tmp_path):
    async with client._transport.app.state.session_factory() as session:
        document = Document(
            id="doc-search-route-pagination",
            filename="route-pagination.txt",
            content_type="text/plain",
            sha256="route-pagination-sha",
            artifact_path=str(tmp_path / "route-pagination.txt"),
            status="succeeded",
        )
        session.add(document)
        await session.flush()
        session.add_all(
            [
                Chunk(
                    id=f"chunk-route-page-{index}",
                    document_id=document.id,
                    text="needle route shared term",
                    metadata_json={"chunk_index": index},
                    source_location={},
                )
                for index in range(3)
            ]
        )
        await session.commit()

    response = await client.post(
        "/api/chunks/search",
        json={
            "query": "needle route",
            "document_ids": ["doc-search-route-pagination"],
            "limit": 1,
            "offset": 1,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["has_more"] is True
    assert [item["id"] for item in body["items"]] == ["chunk-route-page-1"]
