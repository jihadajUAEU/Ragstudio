from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx

TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}


async def retry_async_http[T](
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay_seconds: float = 0.25,
) -> T:
    attempts = max(attempts, 1)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return await operation()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in TRANSIENT_STATUS_CODES:
                raise
            last_error = exc
        except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException) as exc:
            last_error = exc
        if attempt < attempts - 1 and base_delay_seconds > 0:
            await asyncio.sleep(base_delay_seconds * (2**attempt))
    if last_error is not None:
        raise last_error
    raise RuntimeError("retry_async_http exhausted without result or error.")


def raise_for_transient_status(response: httpx.Response) -> None:
    if getattr(response, "status_code", 200) in TRANSIENT_STATUS_CODES:
        response.raise_for_status()
