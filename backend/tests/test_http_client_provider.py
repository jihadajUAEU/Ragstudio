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
async def test_http_client_provider_rejects_use_after_close():
    provider = HttpClientProvider()
    await provider.aclose()

    with pytest.raises(RuntimeError, match="closed"):
        provider.client("mineru")
