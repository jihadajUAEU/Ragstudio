import pytest
from ragstudio.schemas.runtime import RuntimeProfile
from ragstudio.services.retrieval_evidence import EvidenceCandidate
from ragstudio.services.runtime_answer_service import RuntimeAnswerService


def profile(**overrides):
    values = {
        "id": "default",
        "runtime_mode": "runtime",
        "provider": "openai-compatible",
        "llm_model": "test-model",
        "llm_base_url": "http://llm.example/v1",
        "llm_api_key": "secret",
        "llm_timeout_ms": 5000,
        "llm_capabilities": ["text"],
        "vision_model": None,
        "vision_base_url": None,
        "vision_timeout_ms": 5000,
        "embedding_provider": "vllm_openai",
        "embedding_model": "embed",
        "embedding_base_url": "http://embed.example/v1",
        "embedding_dimensions": 1536,
        "embedding_batch_size": 16,
        "embedding_timeout_ms": 5000,
        "reranker_provider": "disabled",
        "reranker_model": None,
        "reranker_base_url": None,
        "reranker_timeout_ms": 5000,
        "storage_backend": "postgres_pgvector_neo4j",
        "pgvector_schema": "public",
        "pgvector_table_prefix": "ragstudio",
        "neo4j_uri": None,
        "neo4j_username": None,
        "neo4j_password": None,
        "parser": "mineru",
        "parse_method": "auto",
        "chunk_token_size": 1200,
        "chunk_overlap_token_size": 100,
        "enable_image_processing": False,
        "enable_table_processing": False,
        "enable_equation_processing": False,
        "context_window": 1,
        "context_mode": "page",
        "max_context_tokens": 2000,
        "include_headers": True,
        "include_captions": True,
        "query_mode": "mix",
        "top_k": 40,
        "chunk_top_k": 20,
        "enable_rerank": False,
        "cosine_better_than_threshold": 0.2,
        "max_total_tokens": 30000,
        "max_entity_tokens": 6000,
        "max_relation_tokens": 8000,
        "enable_llm_cache": True,
        "enable_llm_cache_for_entity_extract": True,
        "llm_model_max_async": 4,
        "embedding_func_max_async": 8,
        "max_parallel_insert": 2,
        "runtime_working_dir": "/tmp/ragstudio",
        "index_shape": {},
    }
    values.update(overrides)
    return RuntimeProfile(**values)


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.requests = []
        self.timeout = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, *, headers, json):
        self.requests.append({"url": url, "headers": headers, "json": json})
        return FakeResponse(self.response)


@pytest.mark.asyncio
async def test_answer_service_sends_fused_evidence_and_returns_usage(monkeypatch):
    fake_client = FakeClient(
        {
            "choices": [
                {"message": {"content": "Sahih al-Bukhari contains 7277 hadith. [S1]"}}
            ],
            "usage": {
                "prompt_tokens": 42,
                "completion_tokens": 12,
                "total_tokens": 54,
            },
        }
    )

    def fake_async_client(*, timeout):
        fake_client.timeout = timeout
        return fake_client

    monkeypatch.setattr(
        "ragstudio.services.runtime_answer_service.httpx.AsyncClient",
        fake_async_client,
    )
    service = RuntimeAnswerService()
    evidence = [
        EvidenceCandidate(
            candidate_id="metadata:m1",
            text="Sahih al-Bukhari\n\n7277 Hadith Collection",
            document_id="doc-1",
            chunk_id="chunk-1",
            source_location={},
            metadata={"deduped_tools": ["metadata", "native"]},
            tool="metadata",
            tool_rank=1,
            base_score=10,
            final_score=40,
            reasons=["title_count_match", "answer_bearing_count"],
        )
    ]

    answer, token_metadata = await service.answer(
        "how many hadith in bukhari",
        evidence,
        profile(),
    )

    request = fake_client.requests[0]
    assert answer == "Sahih al-Bukhari contains 7277 hadith. [S1]"
    assert token_metadata == {
        "prompt_tokens": 42,
        "completion_tokens": 12,
        "total_tokens": 54,
    }
    assert fake_client.timeout == 5
    assert request["url"] == "http://llm.example/v1/chat/completions"
    assert request["headers"]["authorization"] == "Bearer secret"
    assert request["json"]["model"] == "test-model"
    assert request["json"]["messages"][0]["role"] == "system"
    user_prompt = request["json"]["messages"][1]["content"]
    assert "[S1]" in user_prompt
    assert "7277 Hadith Collection" in user_prompt
    assert "metadata" in user_prompt
    assert "answer_bearing_count" in user_prompt


@pytest.mark.asyncio
async def test_answer_service_does_not_duplicate_chat_completions_suffix(monkeypatch):
    fake_client = FakeClient({"choices": [{"message": {"content": "Supported. [S1]"}}]})
    monkeypatch.setattr(
        "ragstudio.services.runtime_answer_service.httpx.AsyncClient",
        lambda *, timeout: fake_client,
    )

    answer, token_metadata = await RuntimeAnswerService().answer(
        "what is supported",
        [
            EvidenceCandidate(
                candidate_id="native:1",
                text="A supported fact.",
                document_id=None,
                chunk_id=None,
                source_location={},
                metadata={},
                tool="native",
                tool_rank=1,
                base_score=1,
            )
        ],
        profile(llm_base_url="http://llm.example/v1/chat/completions/"),
    )

    assert answer == "Supported. [S1]"
    assert token_metadata == {}
    assert fake_client.requests[0]["url"] == "http://llm.example/v1/chat/completions"
