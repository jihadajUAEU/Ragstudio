import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from ragstudio.schemas.settings import LlmConnectionTestOut, SettingsProfileIn
from ragstudio.services.http_retry import raise_for_transient_status, retry_async_http


class LlmConnectionService:
    def __init__(self, http_client: httpx.AsyncClient | None = None):
        self._http_client = http_client

    async def test(self, settings: SettingsProfileIn) -> LlmConnectionTestOut:
        base_url = (settings.llm_base_url or "").rstrip("/")
        if not base_url:
            return LlmConnectionTestOut(
                ok=False,
                provider=settings.llm_provider,
                model=settings.llm_model,
                latency_ms=0,
                detail="LLM base URL is not configured.",
            )

        headers = {"content-type": "application/json"}
        if settings.llm_api_key:
            headers["authorization"] = f"Bearer {settings.llm_api_key}"

        started = time.perf_counter()
        try:
            async with self._client(settings.llm_timeout_ms / 1000) as client:
                response = await retry_async_http(
                    lambda: self._post_for_retry(
                        client,
                        f"{base_url}/chat/completions",
                        headers=headers,
                        json={
                            "model": settings.llm_model,
                            "messages": [
                                {"role": "user", "content": "Ragstudio LLM connection test"}
                            ],
                            "max_tokens": 8,
                            "temperature": 0,
                        },
                    ),
                    attempts=2,
                )
            latency_ms = int((time.perf_counter() - started) * 1000)
            if response.status_code >= 400:
                return LlmConnectionTestOut(
                    ok=False,
                    provider=settings.llm_provider,
                    model=settings.llm_model,
                    latency_ms=latency_ms,
                    detail=f"LLM connection test returned HTTP {response.status_code}.",
                )
            payload = response.json()
            choices = payload.get("choices") if isinstance(payload, dict) else None
            if not isinstance(choices, list) or not choices:
                return LlmConnectionTestOut(
                    ok=False,
                    provider=settings.llm_provider,
                    model=settings.llm_model,
                    latency_ms=latency_ms,
                    detail="LLM response did not include choices.",
                )
            return LlmConnectionTestOut(
                ok=True,
                provider=settings.llm_provider,
                model=settings.llm_model,
                latency_ms=latency_ms,
                detail="LLM chat completions test succeeded.",
            )
        except (httpx.HTTPError, ValueError) as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return LlmConnectionTestOut(
                ok=False,
                provider=settings.llm_provider,
                model=settings.llm_model,
                latency_ms=latency_ms,
                detail=str(exc),
            )

    @asynccontextmanager
    async def _client(self, timeout: float) -> AsyncIterator[httpx.AsyncClient]:
        if self._http_client is not None:
            yield self._http_client
            return
        async with httpx.AsyncClient(timeout=timeout) as client:
            yield client

    async def _post_for_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
    ) -> httpx.Response:
        response = await client.post(url, headers=headers, json=json)
        raise_for_transient_status(response)
        return response
