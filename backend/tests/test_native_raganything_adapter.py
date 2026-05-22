import asyncio
import os
from types import SimpleNamespace

import pytest
from ragstudio.config import AppSettings
from ragstudio.schemas.runtime import RuntimeProfile
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.native_raganything_adapter import (
    NativeRAGAnythingAdapter,
    ScopedVectorStorageProxy,
)

OPENAI_CALLS: list[dict] = []


def profile(**overrides):
    data = {
        "id": "default",
        "runtime_mode": "runtime",
        "provider": "openai-compatible",
        "llm_model": "gpt-4o",
        "llm_base_url": "http://127.0.0.1:8004/v1",
        "llm_timeout_ms": 10000,
        "llm_capabilities": ["text", "vision"],
        "vision_model": None,
        "vision_base_url": None,
        "vision_timeout_ms": 10000,
        "embedding_provider": "vllm_openai",
        "embedding_model": "text-embedding-3-large",
        "embedding_base_url": "http://127.0.0.1:8001/v1",
        "embedding_dimensions": 1536,
        "embedding_batch_size": 16,
        "embedding_timeout_ms": 10000,
        "reranker_provider": "disabled",
        "reranker_model": None,
        "reranker_base_url": None,
        "reranker_timeout_ms": 10000,
        "storage_backend": "postgres_pgvector_neo4j",
        "pgvector_schema": "public",
        "pgvector_table_prefix": "ragstudio",
        "neo4j_uri": "bolt://127.0.0.1:57687",
        "neo4j_username": "neo4j",
        "neo4j_password": "secret",
        "parser": "mineru",
        "parse_method": "auto",
        "chunk_token_size": 1200,
        "chunk_overlap_token_size": 100,
        "enable_image_processing": True,
        "enable_table_processing": True,
        "enable_equation_processing": True,
        "context_window": 1,
        "context_mode": "page",
        "max_context_tokens": 2000,
        "include_headers": True,
        "include_captions": True,
        "query_mode": "mix",
        "top_k": 40,
        "chunk_top_k": 20,
        "enable_rerank": True,
        "cosine_better_than_threshold": 0.2,
        "max_total_tokens": 30000,
        "max_entity_tokens": 6000,
        "max_relation_tokens": 8000,
        "enable_llm_cache": True,
        "enable_llm_cache_for_entity_extract": True,
        "llm_model_max_async": 4,
        "embedding_func_max_async": 8,
        "max_parallel_insert": 2,
        "runtime_working_dir": "/tmp/ragstudio-runtime",
        "index_shape": {},
    }
    data.update(overrides)
    return RuntimeProfile(**data)


class FakeRAGAnything:
    instances = []
    doc_status_records = {}

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.inserted_doc_id = None
        self.inserted_content_list = None
        self.parse_called = False
        self.initialized = False
        self.aquery_error = None
        self.aquery_calls = []
        self.query_cache_enabled = []
        self.lightrag = FakeLightRAG(dict(FakeRAGAnything.doc_status_records))
        self.deleted = self.lightrag.deleted
        FakeRAGAnything.instances.append(self)

    async def parse_document(self, file_path, output_dir, parse_method, display_stats):
        self.parse_called = True
        return (
            [
                {"type": "text", "text": "Native chunk", "page_idx": 0},
                {"type": "table", "table_body": "|A|B|", "page_idx": 1},
            ],
            "generated-doc",
        )

    async def insert_content_list(self, content_list, file_path, doc_id, display_stats):
        self.inserted_doc_id = doc_id
        self.inserted_content_list = content_list

    async def aquery(self, query, mode="mix", **kwargs):
        if not self.initialized:
            raise AssertionError("aquery called before LightRAG initialization")
        if self.aquery_error is not None:
            raise self.aquery_error
        self.query_cache_enabled.append(
            self.lightrag.llm_response_cache.global_config.get("enable_llm_cache")
        )
        self.aquery_calls.append({"query": query, "mode": mode, "kwargs": dict(kwargs)})
        if "chunk_top_k" in kwargs:
            rows = await self.lightrag.chunks_vdb.query(
                query,
                top_k=kwargs.get("chunk_top_k") or kwargs["top_k"],
            )
            if [row["full_doc_id"] for row in rows] != ["doc-1"]:
                raise AssertionError(f"unscoped rows reached native query: {rows}")
            return f"native scoped answer: {query}:{mode}:{kwargs['top_k']}"
        return f"native answer: {query}:{mode}:{kwargs['top_k']}"

    async def _ensure_lightrag_initialized(self):
        self.initialized = True
        return {"success": True}


class FakeEmbeddingFunc:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeChunkVectorStorage:
    def __init__(self, rows, hydrated_rows=None):
        self.rows = rows
        self.hydrated_rows = hydrated_rows or rows
        self.calls = []
        self.get_by_ids_calls = []
        self.cosine_better_than_threshold = 0.2

    async def query(self, query, top_k, query_embedding=None):
        self.calls.append(
            {"query": query, "top_k": top_k, "query_embedding": query_embedding}
        )
        return self.rows[:top_k]

    async def get_by_ids(self, ids):
        self.get_by_ids_calls.append(ids)
        by_id = {str(row.get("id")): row for row in self.hydrated_rows}
        return [by_id.get(str(row_id)) for row_id in ids]


class FakeFilterableChunkVectorStorage(FakeChunkVectorStorage):
    def __init__(self, rows, hydrated_rows=None):
        super().__init__(rows, hydrated_rows)
        self.query_by_full_doc_ids_calls = []

    async def query_by_full_doc_ids(
        self,
        query,
        top_k,
        document_ids,
        query_embedding=None,
    ):
        self.query_by_full_doc_ids_calls.append(
            {
                "query": query,
                "top_k": top_k,
                "document_ids": document_ids,
                "query_embedding": query_embedding,
            }
        )
        allowed = {str(document_id) for document_id in document_ids}
        return [
            row
            for row in self.rows
            if str(row.get("full_doc_id") or "") in allowed
        ][:top_k]


class FailingFilterableChunkVectorStorage(FakeFilterableChunkVectorStorage):
    async def query_by_full_doc_ids(
        self,
        query,
        top_k,
        document_ids,
        query_embedding=None,
    ):
        self.query_by_full_doc_ids_calls.append(
            {
                "query": query,
                "top_k": top_k,
                "document_ids": document_ids,
                "query_embedding": query_embedding,
            }
        )
        raise RuntimeError("storage filter failed")


class FakeLightRAG:
    def __init__(self, doc_status_records=None):
        self.deleted = []
        self.aquery_data_calls = 0
        self.doc_status = FakeDocStatus(doc_status_records or {})
        self.llm_response_cache = SimpleNamespace(
            global_config={"enable_llm_cache": True}
        )
        self.chunks_vdb = FakeFilterableChunkVectorStorage(
            [
                {
                    "id": "chunk-1",
                    "full_doc_id": "doc-1",
                    "content": "Sahih al-Bukhari 7277 Hadith Collection",
                    "file_path": "bukhari.pdf",
                    "score": 0.91,
                },
            ]
        )

    async def adelete_by_doc_id(self, doc_id):
        self.deleted.append(doc_id)

    async def aquery_data(self, query, param):
        self.aquery_data_calls += 1
        raise AssertionError("scoped query should collect sources from rag.aquery")


class FakeDocStatus:
    def __init__(self, records):
        self.records = records

    async def get_by_id(self, doc_id):
        return self.records.get(doc_id)


@pytest.fixture(autouse=True)
def fake_upstream(monkeypatch):
    FakeRAGAnything.instances.clear()
    FakeRAGAnything.doc_status_records = {}
    OPENAI_CALLS.clear()

    def fake_import(name):
        if name == "raganything":
            return SimpleNamespace(RAGAnything=FakeRAGAnything)
        if name == "raganything.config":
            return SimpleNamespace(RAGAnythingConfig=FakeConfig)
        if name == "lightrag.llm.openai":
            async def fake_call(*args, **kwargs):
                OPENAI_CALLS.append({"args": args, "kwargs": kwargs})
                return "ok"

            return SimpleNamespace(
                openai_complete_if_cache=fake_call,
                openai_embed=fake_call,
            )
        if name == "lightrag.utils":
            return SimpleNamespace(EmbeddingFunc=FakeEmbeddingFunc)
        raise AssertionError(f"unexpected import {name}")

    monkeypatch.setattr("ragstudio.services.native_raganything_adapter.import_module", fake_import)


@pytest.mark.asyncio
async def test_scoped_vector_proxy_filters_by_full_doc_id():
    base = FakeChunkVectorStorage(
        [
            {"id": "chunk-1", "full_doc_id": "doc-1", "content": "inside one"},
            {"id": "chunk-2", "full_doc_id": "doc-2", "content": "outside"},
            {"id": "chunk-3", "full_doc_id": "doc-1", "content": "inside two"},
        ]
    )
    proxy = ScopedVectorStorageProxy(base, ["doc-1"])

    rows = await proxy.query("question", top_k=2, query_embedding=[0.1, 0.2])

    assert [row["id"] for row in rows] == ["chunk-1", "chunk-3"]
    assert base.calls == [
        {"query": "question", "top_k": 16, "query_embedding": [0.1, 0.2]}
    ]
    assert [row["id"] for row in proxy.raw_results] == [
        "chunk-1",
        "chunk-2",
        "chunk-3",
    ]
    assert [row["id"] for row in proxy.collected_results] == ["chunk-1", "chunk-3"]


@pytest.mark.asyncio
async def test_scoped_vector_proxy_preserves_base_attributes():
    base = FakeChunkVectorStorage([])
    proxy = ScopedVectorStorageProxy(base, ["doc-1"])

    assert proxy.cosine_better_than_threshold == 0.2


@pytest.mark.asyncio
async def test_scoped_vector_proxy_hydrates_full_doc_id_before_filtering():
    base = FakeChunkVectorStorage(
        [
            {"id": "chunk-1", "content": "inside one"},
            {"id": "chunk-2", "content": "outside"},
        ],
        hydrated_rows=[
            {"id": "chunk-1", "full_doc_id": "doc-1", "content": "inside one"},
            {"id": "chunk-2", "full_doc_id": "doc-2", "content": "outside"},
        ],
    )
    proxy = ScopedVectorStorageProxy(base, ["doc-1"])

    rows = await proxy.query("question", top_k=2)

    assert [row["id"] for row in rows] == ["chunk-1"]
    assert base.get_by_ids_calls == [["chunk-1", "chunk-2"]]
    assert proxy.raw_results[0]["full_doc_id"] == "doc-1"
    assert proxy.collected_results[0]["full_doc_id"] == "doc-1"


@pytest.mark.asyncio
async def test_scoped_vector_proxy_uses_storage_level_full_doc_id_filter():
    base = FakeFilterableChunkVectorStorage(
        [
            {"id": "outside-1", "full_doc_id": "doc-2", "content": "outside one"},
            {"id": "outside-2", "full_doc_id": "doc-3", "content": "outside two"},
            {"id": "inside-1", "full_doc_id": "doc-1", "content": "inside one"},
            {"id": "inside-2", "full_doc_id": "doc-1", "content": "inside two"},
        ]
    )
    proxy = ScopedVectorStorageProxy(base, ["doc-1"], require_storage_filter=True)

    rows = await proxy.query("question", top_k=2, query_embedding=[0.1, 0.2])

    assert [row["id"] for row in rows] == ["inside-1", "inside-2"]
    assert base.calls == []
    assert base.query_by_full_doc_ids_calls == [
        {
            "query": "question",
            "top_k": 2,
            "document_ids": ["doc-1"],
            "query_embedding": [0.1, 0.2],
        }
    ]
    assert [row["id"] for row in proxy.raw_results] == ["inside-1", "inside-2"]
    assert [row["id"] for row in proxy.collected_results] == ["inside-1", "inside-2"]


@pytest.mark.asyncio
async def test_scoped_vector_proxy_filters_pgvector_storage_by_full_doc_id():
    class FakeDB:
        vector_index_type = "HNSW_HALFVEC"

        def __init__(self):
            self.calls = []

        async def query(self, sql, params, multirows):
            self.calls.append({"sql": sql, "params": params, "multirows": multirows})
            return [
                {
                    "id": "chunk-1",
                    "full_doc_id": "doc-1",
                    "content": "inside",
                    "file_path": "inside.pdf",
                    "score": 0.91,
                }
            ]

    async def embedding_func(texts, **kwargs):
        assert texts == ["question"]
        assert kwargs == {"context": "query", "_priority": 5}
        return [[0.1, 0.2]]

    db = FakeDB()
    base = SimpleNamespace(
        db=db,
        table_name="LIGHTRAG_DOC_CHUNKS_model",
        workspace="ragstudio_default",
        embedding_func=embedding_func,
        cosine_better_than_threshold=0.2,
    )
    proxy = ScopedVectorStorageProxy(base, ["doc-1"], require_storage_filter=True)

    rows = await proxy.query("question", top_k=3)

    assert [row["id"] for row in rows] == ["chunk-1"]
    assert "full_doc_id = ANY($5)" in db.calls[0]["sql"]
    assert "$4::halfvec" in db.calls[0]["sql"]
    assert db.calls[0]["params"] == [
        "ragstudio_default",
        0.8,
        3,
        [0.1, 0.2],
        ["doc-1"],
    ]
    assert db.calls[0]["multirows"] is True


@pytest.mark.asyncio
async def test_native_adapter_preflight_without_scope_reports_filter_not_required(tmp_path):
    adapter = NativeRAGAnythingAdapter(
        profile(runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )

    report = await adapter.preflight_scoped_retrieval([])

    assert report == {
        "status": "ok",
        "storage_filter": "not_required",
        "embedding_dimensions": 1536,
        "send_dimensions": True,
        "scoped_cache_policy": "not_required",
    }


@pytest.mark.asyncio
async def test_native_adapter_preflight_reports_storage_filter_and_embedding_shape(tmp_path):
    adapter = NativeRAGAnythingAdapter(
        profile(runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )

    report = await adapter.preflight_scoped_retrieval(["doc-1"])

    assert report["status"] == "ok"
    assert report["storage_filter"] == "supported"
    assert report["embedding_dimensions"] == 1536
    assert report["send_dimensions"] is True
    assert report["scoped_cache_policy"] == "disabled_for_query"


@pytest.mark.asyncio
async def test_native_adapter_preflight_blocks_unfilterable_storage(tmp_path):
    rag = FakeRAGAnything()
    rag.lightrag.chunks_vdb = FakeChunkVectorStorage([])
    adapter = NativeRAGAnythingAdapter(
        profile(runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )
    adapter._rag = rag

    report = await adapter.preflight_scoped_retrieval(["doc-1"])

    assert report["status"] == "degraded"
    assert report["error_type"] == "native_document_scope_unsupported"
    assert "full_doc_id filtering" in report["detail"]
    assert report["embedding_dimensions"] == 1536
    assert report["send_dimensions"] is True
    assert report["scoped_cache_policy"] == "disabled_for_query"


@pytest.mark.asyncio
async def test_native_adapter_indexes_with_studio_document_id(tmp_path):
    artifact = tmp_path / "paper.txt"
    artifact.write_text("hello", encoding="utf-8")
    adapter = NativeRAGAnythingAdapter(
        profile(runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )

    chunks = await adapter.index_document(artifact, document_id="studio-doc-id")

    assert FakeRAGAnything.instances[0].inserted_doc_id == "studio-doc-id"
    assert [chunk.text for chunk in chunks] == ["Native chunk", "|A|B|"]
    assert chunks[0].metadata["backend"] == "raganything"


@pytest.mark.asyncio
async def test_native_adapter_indexes_normalized_preparsed_chunks_without_local_parse(
    tmp_path,
):
    artifact = tmp_path / "paper.pdf"
    artifact.write_text("pdf", encoding="utf-8")
    extract_dir = tmp_path / "mineru"
    extract_dir.mkdir()
    (extract_dir / "source_content_list.json").write_text(
        "["
        '{"type": "text", "text": "Raw MinerU text should not be reinserted", "page_idx": 2},'
        '{"type": "page_footnote", "text": "Footer should not become multimodal"},'
        '{"type": "image", "img_path": "images/page.png"}'
        "]",
        encoding="utf-8",
    )
    adapter = NativeRAGAnythingAdapter(
        profile(runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )

    chunks = await adapter.index_preparsed_chunks(
        artifact,
        [
            AdapterChunk(
                text="Remote MinerU text",
                source_location={"page_start": 3, "page_end": 3},
                metadata={
                    "parser_metadata": {
                        "backend": "mineru",
                        "artifact_extract_dir": str(extract_dir),
                        "content_list_ref": "source_content_list.json",
                        "artifact_ref": "page.md",
                    }
                },
            )
        ],
        document_id="studio-doc-id",
    )

    rag = FakeRAGAnything.instances[0]
    assert rag.parse_called is False
    assert rag.inserted_doc_id == "studio-doc-id"
    assert len(rag.inserted_content_list) == 1
    row = rag.inserted_content_list[0]
    assert row["id"] == "studio-doc-id|page.md|None|0"
    assert row["chunk_identity"] == "studio-doc-id|page.md|None|0"
    assert row["canonical_chunk_id"] == "studio-doc-id|page.md|None|0"
    assert row["full_doc_id"] == "studio-doc-id"
    assert row["type"] == "text"
    assert row["text"] == "Remote MinerU text"
    assert row["page_idx"] == 2
    assert row["metadata"]["chunk_identity"] == "studio-doc-id|page.md|None|0"
    assert row["metadata"]["content_type"] == "text"
    assert row["metadata"]["evidence_context"]["page"] == 3
    assert chunks[0].text == "Remote MinerU text"
    assert chunks[0].metadata["backend"] == "mineru"
    assert chunks[0].metadata["chunk_identity"] == "studio-doc-id|page.md|None|0"
    assert chunks[0].runtime_source_id == "studio-doc-id|page.md|None|0"


@pytest.mark.asyncio
async def test_native_adapter_keeps_all_normalized_chunks_sharing_content_list(tmp_path):
    artifact = tmp_path / "paper.pdf"
    artifact.write_text("pdf", encoding="utf-8")
    extract_dir = tmp_path / "mineru"
    extract_dir.mkdir()
    (extract_dir / "source_content_list.json").write_text(
        '[{"type": "text", "text": "Page one", "page_idx": 0},'
        '{"type": "text", "text": "Page two", "page_idx": 1}]',
        encoding="utf-8",
    )
    shared_metadata = {
        "parser_metadata": {
            "backend": "mineru",
            "artifact_extract_dir": str(extract_dir),
            "content_list_ref": "source_content_list.json",
        }
    }
    adapter = NativeRAGAnythingAdapter(
        profile(runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )

    chunks = await adapter.index_preparsed_chunks(
        artifact,
        [
            AdapterChunk(
                text="Markdown artifact one",
                source_location={"artifact": "one.md"},
                metadata=shared_metadata,
            ),
            AdapterChunk(
                text="Markdown artifact two",
                source_location={"artifact": "two.md"},
                metadata=shared_metadata,
            ),
        ],
        document_id="studio-doc-id",
    )

    assert len(chunks) == 2
    inserted_rows = FakeRAGAnything.instances[0].inserted_content_list
    assert [row["id"] for row in inserted_rows] == [
        "studio-doc-id|one.md|None|0",
        "studio-doc-id|two.md|None|1",
    ]
    assert [row["canonical_chunk_id"] for row in inserted_rows] == [
        "studio-doc-id|one.md|None|0",
        "studio-doc-id|two.md|None|1",
    ]
    assert [row["full_doc_id"] for row in inserted_rows] == [
        "studio-doc-id",
        "studio-doc-id",
    ]
    assert [row["text"] for row in inserted_rows] == [
        "Markdown artifact one",
        "Markdown artifact two",
    ]
    assert inserted_rows[0]["metadata"]["chunk_identity"] == "studio-doc-id|one.md|None|0"
    assert inserted_rows[1]["metadata"]["chunk_identity"] == "studio-doc-id|two.md|None|1"


def test_preparsed_content_list_includes_context_prefix_and_bridge_metadata(tmp_path):
    adapter = NativeRAGAnythingAdapter(profile(runtime_working_dir=str(tmp_path)), AppSettings())
    chunk = AdapterChunk(
        text="Guide us to the straight path.",
        source_location={"page": 1, "reference": "1:5"},
        metadata={
            "chunk_identity": "doc-1|1:5",
            "document_metadata": {"title": "Synthetic Tafseer"},
            "reference_metadata": {"references": ["1:5"]},
            "content_type": "text",
            "quality_action_policy": {"index_vector": True, "project_graph": True},
            "provenance": {"blocks": [{"block_type": "paragraph", "role": "body"}]},
        },
        runtime_source_id="runtime-1",
        content_type="text",
    )

    rows = adapter._content_list_from_preparsed_chunks([chunk], document_id="doc-1")

    assert rows[0]["text"].startswith("[Context: Synthetic Tafseer > 1:5")
    assert rows[0]["canonical_chunk_id"] == "doc-1|1:5"
    assert rows[0]["chunk_identity"] == "doc-1|1:5"
    assert rows[0]["full_doc_id"] == "doc-1"
    assert rows[0]["metadata"]["runtime_source_id"] == "runtime-1"
    assert rows[0]["metadata"]["quality_action_policy"]["index_vector"] is True
    assert rows[0]["metadata"]["evidence_context"]["reference"] == "1:5"


def test_preparsed_content_list_keeps_native_type_text_for_studio_chunk_types(tmp_path):
    adapter = NativeRAGAnythingAdapter(profile(runtime_working_dir=str(tmp_path)), AppSettings())
    chunk = AdapterChunk(
        text="Structured warning payload",
        source_location={"page": 1},
        metadata={"chunk_identity": "doc-1|warning"},
        content_type="parser_quality_warning",
    )

    rows = adapter._content_list_from_preparsed_chunks([chunk], document_id="doc-1")

    assert rows[0]["type"] == "text"
    assert rows[0]["metadata"]["content_type"] == "parser_quality_warning"


def test_preparsed_content_list_preserves_quality_policy_for_runtime_bridge(tmp_path):
    adapter = NativeRAGAnythingAdapter(profile(runtime_working_dir=str(tmp_path)), AppSettings())
    chunk = AdapterChunk(
        text="Unsafe text",
        source_location={"page": 1},
        metadata={"quality_action_policy": {"index_vector": False, "project_graph": False}},
        content_type="text",
    )

    rows = adapter._content_list_from_preparsed_chunks([chunk], document_id="doc-1")

    assert rows[0]["metadata"]["quality_action_policy"]["index_vector"] is False
    assert rows[0]["metadata"]["quality_action_policy"]["project_graph"] is False


def test_preparsed_content_list_preserves_layout_bridge_fields(tmp_path):
    adapter = NativeRAGAnythingAdapter(profile(runtime_working_dir=str(tmp_path)), AppSettings())
    chunk = AdapterChunk(
        text="Figure caption text.",
        content_type="figure",
        source_location={"page": 4, "bbox": [10, 20, 200, 80]},
        metadata={
            "chunk_identity": "chunk-layout",
            "quality_action_policy": {"index_vector": True, "project_graph": True},
            "layout_group_id": "figure-1",
            "layout_role": "caption",
            "reading_order": 7,
            "provenance": {"blocks": [{"block_type": "caption", "role": "figure"}]},
        },
    )

    content_list = adapter._content_list_from_preparsed_chunks(
        [chunk],
        document_id="doc-layout",
    )

    metadata = content_list[0]["metadata"]
    assert metadata["layout_group_id"] == "figure-1"
    assert metadata["layout_role"] == "caption"
    assert metadata["reading_order"] == 7
    assert metadata["quality_action_policy"]["index_vector"] is True
    assert metadata["evidence_context"]["layout_summary"] == (
        "figure; page=4; block=caption; role=figure"
    )


@pytest.mark.asyncio
async def test_native_adapter_raises_failed_lightrag_doc_status_after_insert(tmp_path):
    artifact = tmp_path / "paper.pdf"
    artifact.write_text("pdf", encoding="utf-8")
    FakeRAGAnything.doc_status_records = {
        "studio-doc-id": {
            "status": "failed",
            "error_msg": "LLM func: Worker execution timeout after 360s",
        }
    }
    adapter = NativeRAGAnythingAdapter(
        profile(runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )

    with pytest.raises(RuntimeError, match="Worker execution timeout"):
        await adapter.index_preparsed_chunks(
            artifact,
            [
                AdapterChunk(
                    text="Remote MinerU text",
                    source_location={"page_start": 3, "page_end": 3},
                    metadata={"parser_metadata": {"backend": "mineru"}},
                )
            ],
            document_id="studio-doc-id",
        )


@pytest.mark.asyncio
async def test_native_adapter_queries_raganything(tmp_path):
    adapter = NativeRAGAnythingAdapter(
        profile(runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )

    result = await adapter.query(
        "question",
        document_ids=[],
        query_config={"mode": "hybrid", "top_k": 12, "parser": "ignored"},
    )

    assert result.answer == "native answer: question:hybrid:12"
    assert result.sources == []
    assert result.timings["native_scoped_query"] is False


@pytest.mark.asyncio
async def test_storage_env_is_visible_to_threads_and_restored(tmp_path, monkeypatch):
    monkeypatch.delenv("POSTGRES_WORKSPACE", raising=False)
    monkeypatch.delenv("NEO4J_WORKSPACE", raising=False)
    runtime_profile = profile(id="tenant", runtime_working_dir=str(tmp_path / "runtime"))
    adapter = NativeRAGAnythingAdapter(
        runtime_profile,
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )
    workspace = f"ragstudio_{runtime_profile.id}"

    async with adapter._storage_env():
        assert NativeRAGAnythingAdapter._env_lock.locked() is True
        assert os.environ["POSTGRES_WORKSPACE"] == workspace
        assert await asyncio.to_thread(os.environ.get, "NEO4J_WORKSPACE") == workspace

    assert "POSTGRES_WORKSPACE" not in os.environ
    assert "NEO4J_WORKSPACE" not in os.environ


def test_native_adapter_reports_scoped_query_capability(tmp_path):
    adapter = NativeRAGAnythingAdapter(
        profile(runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )

    report = adapter.capability_report()

    assert report["native_scoped_query"] == "conditional"
    assert report["scoped_query"] == "requires_storage_verification"
    assert (
        report["scoped_query_detail"]
        == "Selected-document native query requires LightRAG chunk storage with "
        "full_doc_id filtering support; the storage backend is verified when "
        "a scoped query initializes LightRAG."
    )


@pytest.mark.asyncio
async def test_native_adapter_supplies_placeholder_api_key_for_local_openai_compatible_endpoints(
    tmp_path,
):
    runtime_profile = profile(
        runtime_working_dir=str(tmp_path / "runtime"),
        llm_api_key=None,
        embedding_api_key=None,
        vision_api_key=None,
    )
    adapter = NativeRAGAnythingAdapter(
        runtime_profile,
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )

    adapter._raganything()

    rag = FakeRAGAnything.instances[0]
    llm_func = rag.kwargs["llm_model_func"]
    embedding_wrapper = rag.kwargs["embedding_func"]
    embedding_func = embedding_wrapper.kwargs["func"]
    vision_func = rag.kwargs["vision_model_func"]

    assert await llm_func("hello", model="runtime-overrides-are-ignored") == "ok"
    assert await vision_func("look", model="runtime-overrides-are-ignored") == "ok"
    assert OPENAI_CALLS[0]["args"][:2] == ("gpt-4o", "hello")
    assert OPENAI_CALLS[0]["kwargs"]["api_key"] == "unused"
    assert "model" not in OPENAI_CALLS[0]["kwargs"]
    assert embedding_func.keywords["api_key"] == "unused"
    assert embedding_wrapper.kwargs["send_dimensions"] is True
    assert OPENAI_CALLS[1]["args"][:2] == ("gpt-4o", "look")
    assert OPENAI_CALLS[1]["kwargs"]["api_key"] == "unused"
    assert "model" not in OPENAI_CALLS[1]["kwargs"]


@pytest.mark.asyncio
async def test_native_adapter_queries_selected_documents_with_scoped_lightrag(tmp_path):
    adapter = NativeRAGAnythingAdapter(
        profile(runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )

    result = await adapter.query(
        "how many hadith in bukhari",
        document_ids=["doc-1"],
        query_config={"mode": "hybrid", "top_k": 12, "chunk_top_k": 4},
    )

    assert result.error is None
    assert result.error_type is None
    assert result.answer == "native scoped answer: how many hadith in bukhari:naive:12"
    assert result.sources == [
        {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "text": "Sahih al-Bukhari 7277 Hadith Collection",
            "source_location": {},
            "metadata": {
                "chunk_identity": "chunk-1",
                "full_doc_id": "doc-1",
                "runtime_source_id": "chunk-1",
                "score": 0.91,
                "native_scope": True,
                "source_role": "retrieved_candidate",
                "retrieval_scope": "document_ids",
                "retrieval_mode": "native_vector_naive",
            },
        }
    ]
    assert result.timings["native_scoped_query"] is True
    assert result.timings["requested_query_mode"] == "hybrid"
    assert result.timings["effective_query_mode"] == "naive"
    assert result.timings["runtime_query_ms"] >= 0
    rag = FakeRAGAnything.instances[0]
    assert rag.aquery_calls == [
        {
            "query": "how many hadith in bukhari",
            "mode": "naive",
            "kwargs": {"top_k": 12, "chunk_top_k": 4, "vlm_enhanced": False},
        }
    ]
    assert rag.lightrag.aquery_data_calls == 0
    assert rag.lightrag.chunks_vdb.calls == []
    assert rag.lightrag.chunks_vdb.query_by_full_doc_ids_calls == [
        {
            "query": "how many hadith in bukhari",
            "top_k": 4,
            "document_ids": ["doc-1"],
            "query_embedding": None,
        }
    ]
    assert rag.query_cache_enabled == [False]
    assert rag.lightrag.llm_response_cache.global_config["enable_llm_cache"] is True


@pytest.mark.asyncio
async def test_native_adapter_disables_llm_cache_for_scoped_queries(tmp_path):
    adapter = NativeRAGAnythingAdapter(
        profile(runtime_working_dir=str(tmp_path / "runtime"), enable_llm_cache=True),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )

    await adapter.query(
        "same scoped question",
        document_ids=["doc-1"],
        query_config={"mode": "hybrid", "top_k": 12, "chunk_top_k": 4},
    )

    rag = FakeRAGAnything.instances[0]
    assert rag.query_cache_enabled == [False]
    assert rag.lightrag.llm_response_cache.global_config["enable_llm_cache"] is True


@pytest.mark.asyncio
async def test_native_adapter_filters_raw_overfetch_without_scope_leak(tmp_path):
    rag = FakeRAGAnything()
    rag.lightrag.chunks_vdb = FakeFilterableChunkVectorStorage(
        [
            {
                "id": "chunk-1",
                "full_doc_id": "doc-1",
                "content": "Inside document",
                "file_path": "inside.pdf",
                "score": 0.91,
            },
            {
                "id": "chunk-2",
                "full_doc_id": "doc-2",
                "content": "Outside document",
                "file_path": "outside.pdf",
                "score": 0.88,
            },
        ]
    )
    adapter = NativeRAGAnythingAdapter(
        profile(runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )
    adapter._rag = rag

    result = await adapter.query(
        "how many hadith in bukhari",
        document_ids=["doc-1"],
        query_config={"mode": "hybrid", "top_k": 12, "chunk_top_k": 4},
    )

    assert result.error is None
    assert result.error_type is None
    assert result.answer == "native scoped answer: how many hadith in bukhari:naive:12"
    assert [source["chunk_id"] for source in result.sources] == ["chunk-1"]
    assert rag.aquery_calls == [
        {
            "query": "how many hadith in bukhari",
            "mode": "naive",
            "kwargs": {"top_k": 12, "chunk_top_k": 4, "vlm_enhanced": False},
        }
    ]
    assert rag.lightrag.aquery_data_calls == 0


def test_native_sources_from_proxy_scrubs_file_paths(tmp_path):
    adapter = NativeRAGAnythingAdapter(
        profile(runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )
    proxy = SimpleNamespace(
        collected_results=[
            {
                "id": "chunk-1",
                "full_doc_id": "doc-1",
                "content": "Scoped native text",
                "file_path": "/srv/ragstudio/uploads/private.pdf",
                "page": 7,
                "page_idx": 6,
                "reference": "2:255",
                "score": 0.93,
            }
        ]
    )

    sources = adapter._native_sources_from_proxy(proxy, ["doc-1"])

    assert sources[0]["source_location"] == {
        "page": 7,
        "page_idx": 6,
        "reference": "2:255",
    }
    assert "file_path" not in sources[0]["source_location"]
    assert "/srv/ragstudio" not in str(sources)


@pytest.mark.asyncio
async def test_native_adapter_scoped_query_fails_closed_for_unfiltered_storage(tmp_path):
    rag = FakeRAGAnything()
    original_chunks_vdb = FakeChunkVectorStorage(
        [
            {
                "id": "chunk-1",
                "full_doc_id": "doc-1",
                "content": "Inside document",
                "file_path": "inside.pdf",
                "score": 0.91,
            },
        ]
    )
    rag.lightrag.chunks_vdb = original_chunks_vdb
    adapter = NativeRAGAnythingAdapter(
        profile(runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )
    adapter._rag = rag

    result = await adapter.query(
        "how many hadith in bukhari",
        document_ids=["doc-1"],
        query_config={"mode": "hybrid", "top_k": 12, "chunk_top_k": 4},
    )

    assert result.answer == ""
    assert result.sources == []
    assert result.error_type == "native_document_scope_unsupported"
    assert "storage-level full_doc_id filtering" in (result.error or "")
    assert result.timings["native_scoped_query"] is True
    assert rag.lightrag.chunks_vdb is original_chunks_vdb
    assert rag.lightrag.llm_response_cache.global_config["enable_llm_cache"] is True


@pytest.mark.asyncio
async def test_native_adapter_reports_swallowed_scoped_storage_filter_errors(tmp_path):
    rag = FakeRAGAnything()
    original_chunks_vdb = FailingFilterableChunkVectorStorage(
        [
            {
                "id": "chunk-1",
                "full_doc_id": "doc-1",
                "content": "Inside document",
                "file_path": "inside.pdf",
                "score": 0.91,
            },
        ]
    )
    rag.lightrag.chunks_vdb = original_chunks_vdb

    async def swallowing_aquery(query, mode="mix", **kwargs):
        rag.query_cache_enabled.append(
            rag.lightrag.llm_response_cache.global_config.get("enable_llm_cache")
        )
        rag.aquery_calls.append({"query": query, "mode": mode, "kwargs": dict(kwargs)})
        try:
            await rag.lightrag.chunks_vdb.query(
                query,
                top_k=kwargs.get("chunk_top_k") or kwargs["top_k"],
            )
        except RuntimeError:
            return "LightRAG fail response"
        raise AssertionError("expected storage filter failure")

    rag.aquery = swallowing_aquery
    adapter = NativeRAGAnythingAdapter(
        profile(runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )
    adapter._rag = rag

    result = await adapter.query(
        "how many hadith in bukhari",
        document_ids=["doc-1"],
        query_config={"mode": "hybrid", "top_k": 12, "chunk_top_k": 4},
    )

    assert result.answer == ""
    assert result.sources == []
    assert result.error_type == "native_document_scope_filter_failed"
    assert "storage filter failed" in (result.error or "")
    assert result.timings["native_scoped_query"] is True
    assert result.timings["requested_query_mode"] == "hybrid"
    assert result.timings["effective_query_mode"] == "naive"
    assert rag.lightrag.chunks_vdb is original_chunks_vdb
    assert rag.lightrag.llm_response_cache.global_config["enable_llm_cache"] is True


def test_scope_leak_error_detects_polluted_collected_results(tmp_path):
    adapter = NativeRAGAnythingAdapter(
        profile(runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )
    proxy = SimpleNamespace(
        collected_results=[
            {"id": "chunk-1", "full_doc_id": "doc-1"},
            {"id": "chunk-2", "full_doc_id": "doc-2"},
        ]
    )

    result = adapter._scope_leak_error(proxy, ["doc-1"])

    assert result is not None
    assert result.error_type == "native_document_scope_leak"
    assert "doc-2" in (result.error or "")


@pytest.mark.asyncio
async def test_scoped_chunks_vdb_restores_original_storage_when_query_raises(tmp_path):
    rag = FakeRAGAnything()
    original_chunks_vdb = rag.lightrag.chunks_vdb
    rag.aquery_error = RuntimeError("native query failed")
    adapter = NativeRAGAnythingAdapter(
        profile(runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )
    adapter._rag = rag

    with pytest.raises(RuntimeError, match="native query failed"):
        await adapter.query(
            "how many hadith in bukhari",
            document_ids=["doc-1"],
            query_config={"mode": "hybrid", "top_k": 12, "chunk_top_k": 4},
        )

    assert rag.lightrag.chunks_vdb is original_chunks_vdb


@pytest.mark.asyncio
async def test_native_graph_requires_neo4j_uri(tmp_path):
    adapter = NativeRAGAnythingAdapter(
        profile(neo4j_uri=None, runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )

    with pytest.raises(RuntimeError, match="Neo4j URI is not configured"):
        await adapter.graph()


def test_native_graph_query_scopes_to_workspace_label(tmp_path):
    adapter = NativeRAGAnythingAdapter(
        profile(id="tenant", runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )
    adapter._workspace = lambda: "ragstudio_tenant`one"

    class FakeSession:
        queries = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def run(self, query):
            self.queries.append(query)
            return []

    class FakeDriver:
        def __init__(self):
            self.session_instance = FakeSession()

        def session(self):
            return self.session_instance

    driver = FakeDriver()

    nodes, edges = adapter._read_neo4j_graph(driver)

    assert nodes == []
    assert edges == []
    assert "MATCH (n:`ragstudio_tenant``one`)" in driver.session_instance.queries[0]
    assert (
        "MATCH (source:`ragstudio_tenant``one`)-[relationship]->"
        "(target:`ragstudio_tenant``one`)"
        in driver.session_instance.queries[1]
    )
