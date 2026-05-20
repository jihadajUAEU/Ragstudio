from types import SimpleNamespace

import pytest
from ragstudio.schemas.chunks import ChunkOut
from ragstudio.services.reranker_service import RerankerService


def test_reranker_allowlist_accepts_ipv4_wildcard():
    service = RerankerService(allowed_hosts=["10.10.9.*"])

    assert service._is_allowed_endpoint("http://10.10.9.193:8005/v1/rerank")


def test_reranker_allowlist_rejects_other_private_subnets():
    service = RerankerService(allowed_hosts=["10.10.9.*"])

    assert not service._is_allowed_endpoint("http://10.10.8.193:8005/v1/rerank")


def test_reranker_allowlist_wildcard_requires_valid_ipv4_host():
    service = RerankerService(allowed_hosts=["10.10.9.*"])

    assert not service._is_allowed_endpoint("http://10.10.9.evil.test/v1/rerank")


@pytest.mark.asyncio
async def test_reranker_provider_uses_profile_timeout():
    timeouts: list[float] = []

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [{"index": 0, "relevance_score": 1.0}]}

    class FakeClient:
        async def post(self, url, headers, json):
            return FakeResponse()

    class FakeProvider:
        def client(self, name, *, timeout=30.0):
            timeouts.append(timeout)
            return FakeClient()

    profile = SimpleNamespace(
        enable_rerank=True,
        reranker_provider="generic_http",
        reranker_base_url="http://127.0.0.1:8005/v1/rerank",
        reranker_model="reranker",
        reranker_api_key=None,
        reranker_timeout_ms=1234,
        reranker_fallback_provider="disabled",
    )
    chunks = [
        ChunkOut(
            id="chunk-1",
            document_id="doc-1",
            text="evidence",
            source_location={},
            metadata={},
        )
    ]

    _, traces = await RerankerService(
        allowed_hosts=["127.0.0.1"],
        http_client_provider=FakeProvider(),
    ).rerank("query", chunks, profile)

    assert timeouts == [1.234]
    assert traces[0]["rank"] == 1
