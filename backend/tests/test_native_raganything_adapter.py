from types import SimpleNamespace

import pytest
from ragstudio.config import AppSettings
from ragstudio.schemas.runtime import RuntimeProfile
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.native_raganything_adapter import NativeRAGAnythingAdapter


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

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.inserted_doc_id = None
        self.inserted_content_list = None
        self.parse_called = False
        self.initialized = False
        self.lightrag = SimpleNamespace(adelete_by_doc_id=self._delete)
        self.deleted = []
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
        return f"native answer: {query}:{mode}:{kwargs['top_k']}"

    async def _ensure_lightrag_initialized(self):
        self.initialized = True
        return {"success": True}

    async def _delete(self, doc_id):
        self.deleted.append(doc_id)


class FakeEmbeddingFunc:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


@pytest.fixture(autouse=True)
def fake_upstream(monkeypatch):
    FakeRAGAnything.instances.clear()

    def fake_import(name):
        if name == "raganything":
            return SimpleNamespace(RAGAnything=FakeRAGAnything)
        if name == "raganything.config":
            return SimpleNamespace(RAGAnythingConfig=FakeConfig)
        if name == "lightrag.llm.openai":
            async def fake_call(*args, **kwargs):
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
async def test_native_adapter_indexes_preparsed_chunks_without_local_parse(tmp_path):
    artifact = tmp_path / "paper.pdf"
    artifact.write_text("pdf", encoding="utf-8")
    extract_dir = tmp_path / "mineru"
    extract_dir.mkdir()
    (extract_dir / "source_content_list.json").write_text(
        '[{"type": "text", "text": "Remote MinerU text", "page_idx": 2}]',
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
    assert rag.inserted_content_list == [
        {"type": "text", "text": "Remote MinerU text", "page_idx": 2}
    ]
    assert chunks[0].text == "Remote MinerU text"
    assert chunks[0].metadata["backend"] == "mineru"


@pytest.mark.asyncio
async def test_native_adapter_deduplicates_shared_content_list_mirror_seeds(tmp_path):
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

    assert len(chunks) == 1
    assert FakeRAGAnything.instances[0].inserted_content_list == [
        {"type": "text", "text": "Page one", "page_idx": 0},
        {"type": "text", "text": "Page two", "page_idx": 1},
    ]


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


@pytest.mark.asyncio
async def test_native_adapter_refuses_unscoped_document_queries(tmp_path):
    adapter = NativeRAGAnythingAdapter(
        profile(runtime_working_dir=str(tmp_path / "runtime")),
        AppSettings(database_url="postgresql+asyncpg://user:pass@localhost:5432/ragstudio"),
    )

    result = await adapter.query(
        "question",
        document_ids=["doc-1"],
        query_config={"mode": "hybrid", "top_k": 12},
    )

    assert result.error_type == "native_document_scope_unsupported"
    assert "document_ids" in (result.error or "")
    assert FakeRAGAnything.instances == []


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
