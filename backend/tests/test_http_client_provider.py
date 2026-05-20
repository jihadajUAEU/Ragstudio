import pytest
from ragstudio.services.http_client_provider import HttpClientProvider


@pytest.mark.asyncio
async def test_http_client_provider_reuses_named_clients():
    provider = HttpClientProvider()
    client_a = provider.client("mineru", timeout=5.0)
    client_b = provider.client("mineru", timeout=5.0)

    assert client_a is client_b

    await provider.aclose()
    assert client_a.is_closed


@pytest.mark.asyncio
async def test_http_client_provider_keeps_timeout_scopes_separate():
    provider = HttpClientProvider()
    client_a = provider.client("reranker", timeout=1.0)
    client_b = provider.client("reranker", timeout=9.0)

    assert client_a is not client_b

    await provider.aclose()
    assert client_a.is_closed
    assert client_b.is_closed


@pytest.mark.asyncio
async def test_http_client_provider_rejects_use_after_close():
    provider = HttpClientProvider()
    await provider.aclose()

    with pytest.raises(RuntimeError, match="closed"):
        provider.client("mineru")
