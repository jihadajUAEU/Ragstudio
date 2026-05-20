import httpx
import pytest
from ragstudio.services.http_retry import retry_async_http


@pytest.mark.asyncio
async def test_retry_async_http_retries_transient_status():
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            response = httpx.Response(503, request=httpx.Request("GET", "http://test"))
            raise httpx.HTTPStatusError(
                "unavailable",
                request=response.request,
                response=response,
            )
        return "ok"

    result = await retry_async_http(operation, attempts=2, base_delay_seconds=0)

    assert result == "ok"
    assert calls == 2


@pytest.mark.asyncio
async def test_retry_async_http_does_not_retry_client_error():
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        response = httpx.Response(400, request=httpx.Request("GET", "http://test"))
        raise httpx.HTTPStatusError("bad request", request=response.request, response=response)

    with pytest.raises(httpx.HTTPStatusError):
        await retry_async_http(operation, attempts=3, base_delay_seconds=0)

    assert calls == 1
