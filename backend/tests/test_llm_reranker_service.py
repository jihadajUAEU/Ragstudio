import pytest
from ragstudio.schemas.chunks import ChunkOut
from ragstudio.services.llm_reranker_service import LLMRerankerService


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class FakeAsyncClient:
    requests = []

    def __init__(self, *args, **kwargs):
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, *, headers, json):
        self.requests.append({"url": url, "headers": headers, "json": json})
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": '[{"index": 1, "score": 0.98, "reason": "direct answer"}]'
                        }
                    }
                ],
                "usage": {"prompt_tokens": 30, "completion_tokens": 12},
            }
        )


class FakeProvider:
    def __init__(self, client):
        self.client_instance = client
        self.requests = []

    def client(self, name, *, timeout=30.0):
        self.requests.append({"name": name, "timeout": timeout})
        return self.client_instance


def profile():
    return type(
        "Profile",
        (),
        {
            "llm_base_url": "http://127.0.0.1:8004/v1",
            "llm_api_key": None,
            "llm_model": "QuantTrio/Qwen3-VL-32B-Instruct-AWQ",
            "llm_timeout_ms": 5000,
            "reranker_model": "",
        },
    )()


@pytest.mark.asyncio
async def test_llm_reranker_reorders_chunks(monkeypatch):
    FakeAsyncClient.requests = []
    monkeypatch.setattr(
        "ragstudio.services.llm_reranker_service.httpx.AsyncClient",
        FakeAsyncClient,
    )
    chunks = [
        ChunkOut(
            id="weak",
            document_id="doc-1",
            text="Book 65, Hadith 201",
            source_location={},
            metadata={},
        ),
        ChunkOut(
            id="strong",
            document_id="doc-1",
            text="Sahih al-Bukhari 7277 Hadith Collection",
            source_location={},
            metadata={},
        ),
    ]

    reranked, traces = await LLMRerankerService().rerank(
        "how many hadith in bukhari",
        chunks,
        profile(),
    )

    assert reranked[0].id == "strong"
    assert traces[0]["provider"] == "llm"
    assert traces[0]["chunk_id"] == "strong"
    assert traces[0]["score"] == 0.98
    assert FakeAsyncClient.requests[0]["url"] == "http://127.0.0.1:8004/v1/chat/completions"
    assert FakeAsyncClient.requests[0]["json"]["model"] == "QuantTrio/Qwen3-VL-32B-Instruct-AWQ"


@pytest.mark.asyncio
async def test_llm_reranker_uses_injected_http_client_provider():
    FakeAsyncClient.requests = []
    provider = FakeProvider(FakeAsyncClient())
    chunks = [
        ChunkOut(id="first", document_id="doc-1", text="first", source_location={}, metadata={}),
        ChunkOut(id="second", document_id="doc-1", text="second", source_location={}, metadata={}),
    ]

    reranked, _traces = await LLMRerankerService(http_client_provider=provider).rerank(
        "query",
        chunks,
        profile(),
    )

    assert provider.requests == [{"name": "llm-reranker", "timeout": 5.0}]
    assert reranked[0].id == "second"
    assert FakeAsyncClient.requests[0]["url"] == "http://127.0.0.1:8004/v1/chat/completions"


@pytest.mark.asyncio
async def test_llm_reranker_returns_original_order_when_json_is_invalid(monkeypatch):
    class BadJsonClient(FakeAsyncClient):
        async def post(self, url, *, headers, json):
            return FakeResponse({"choices": [{"message": {"content": "not json"}}]})

    monkeypatch.setattr("ragstudio.services.llm_reranker_service.httpx.AsyncClient", BadJsonClient)
    chunks = [
        ChunkOut(id="first", document_id="doc-1", text="first", source_location={}, metadata={}),
        ChunkOut(id="second", document_id="doc-1", text="second", source_location={}, metadata={}),
    ]

    reranked, traces = await LLMRerankerService().rerank("query", chunks, profile())

    assert [chunk.id for chunk in reranked] == ["first", "second"]
    assert traces[0]["status"] == "invalid_json"


@pytest.mark.asyncio
async def test_llm_reranker_returns_original_order_on_failure(monkeypatch):
    class FailingClient(FakeAsyncClient):
        async def post(self, url, *, headers, json):
            raise RuntimeError("llm offline")

    monkeypatch.setattr("ragstudio.services.llm_reranker_service.httpx.AsyncClient", FailingClient)
    chunks = [
        ChunkOut(id="first", document_id="doc-1", text="first", source_location={}, metadata={}),
        ChunkOut(id="second", document_id="doc-1", text="second", source_location={}, metadata={}),
    ]

    reranked, traces = await LLMRerankerService().rerank("query", chunks, profile())

    assert [chunk.id for chunk in reranked] == ["first", "second"]
    assert traces[0]["status"] == "failed"
    assert traces[0]["error_type"] == "RuntimeError"
