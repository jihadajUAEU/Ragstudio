from __future__ import annotations

import ipaddress
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
from ragstudio.schemas.chunks import ChunkOut
from ragstudio.services.http_retry import raise_for_transient_status, retry_async_http
from ragstudio.services.llm_reranker_service import LLMRerankerService


class HttpClientProvider(Protocol):
    def client(self, name: str, *, timeout: float | httpx.Timeout = 30.0) -> httpx.AsyncClient: ...


class RerankerService:
    def __init__(
        self,
        allowed_hosts: list[str] | None = None,
        llm_reranker: LLMRerankerService | None = None,
        http_client: httpx.AsyncClient | None = None,
        http_client_provider: HttpClientProvider | None = None,
    ):
        self.allowed_hosts = {host.lower() for host in (allowed_hosts or [])}
        self.llm_reranker = llm_reranker or LLMRerankerService()
        self._http_client = http_client
        self._http_client_provider = http_client_provider

    async def rerank(
        self,
        query: str,
        chunks: list[ChunkOut],
        profile: Any,
    ) -> tuple[list[ChunkOut], list[dict[str, Any]]]:
        skipped_trace = self._skipped_trace(query, chunks, profile)
        if skipped_trace is not None:
            return chunks, [skipped_trace]
        if profile.reranker_provider == "llm":
            return await self.llm_reranker.rerank(query, chunks, profile)
        if not self._is_allowed_endpoint(str(profile.reranker_base_url)):
            return await self._fallback_or_return(
                query,
                chunks,
                profile,
                self._failure_trace(profile, "blocked_endpoint"),
            )

        payload = self._payload(query, chunks, profile)
        headers = self._headers(profile)
        timeout = (getattr(profile, "reranker_timeout_ms", None) or 10000) / 1000
        try:
            async with self._client(timeout) as client:
                response = await retry_async_http(
                    lambda: self._post_for_retry(
                        client,
                        str(profile.reranker_base_url),
                        headers=headers,
                        json=payload,
                    ),
                    attempts=2,
                )
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            return await self._fallback_or_return(
                query,
                chunks,
                profile,
                self._failure_trace(profile, "failed", exc),
            )

        scores = self._scores(body)
        if not scores:
            return await self._fallback_or_return(
                query,
                chunks,
                profile,
                {
                    "provider": profile.reranker_provider,
                    "model": profile.reranker_model,
                    "status": "no_results",
                },
            )

        indexed_chunks = {index: chunk for index, chunk in enumerate(chunks)}
        ranked_indices = [
            index for index, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        ]
        reranked = [indexed_chunks[index] for index in ranked_indices if index in indexed_chunks]
        reranked.extend(chunk for index, chunk in indexed_chunks.items() if index not in scores)
        if not any(index in indexed_chunks for index in scores):
            return await self._fallback_or_return(
                query,
                chunks,
                profile,
                {
                    "provider": profile.reranker_provider,
                    "model": profile.reranker_model,
                    "status": "no_usable_results",
                },
            )

        traces = [
            {
                "rank": rank,
                "original_rank": index + 1,
                "chunk_id": indexed_chunks[index].id,
                "score": score,
                "provider": profile.reranker_provider,
                "model": profile.reranker_model,
            }
            for rank, (index, score) in enumerate(
                sorted(scores.items(), key=lambda item: item[1], reverse=True),
                start=1,
            )
            if index in indexed_chunks
        ]
        return reranked, traces

    async def _fallback_or_return(
        self,
        query: str,
        chunks: list[ChunkOut],
        profile: Any,
        primary_trace: dict[str, Any],
    ) -> tuple[list[ChunkOut], list[dict[str, Any]]]:
        if getattr(profile, "reranker_fallback_provider", "disabled") != "llm":
            return chunks, [primary_trace]
        reranked, fallback_traces = await self.llm_reranker.rerank(query, chunks, profile)
        return reranked, [{**primary_trace, "fallback_provider": "llm"}, *fallback_traces]

    def _is_allowed_endpoint(self, url: str) -> bool:
        if not self.allowed_hosts:
            return False
        host = (urlparse(url).hostname or "").lower()
        return any(_host_matches_allowed_pattern(host, allowed) for allowed in self.allowed_hosts)

    def _failure_trace(
        self,
        profile: Any,
        status: str,
        exc: Exception | None = None,
    ) -> dict[str, Any]:
        trace: dict[str, Any] = {
            "provider": profile.reranker_provider,
            "model": profile.reranker_model,
            "status": status,
        }
        if exc is not None:
            trace["error_type"] = exc.__class__.__name__
            trace["detail"] = str(exc)
        return trace

    def _skipped_trace(
        self,
        query: str,
        chunks: list[ChunkOut],
        profile: Any,
    ) -> dict[str, Any] | None:
        provider = getattr(profile, "reranker_provider", "disabled")
        model = getattr(profile, "reranker_model", None)
        if not getattr(profile, "enable_rerank", False) or provider == "disabled":
            return {"provider": provider, "model": model, "status": "disabled"}
        if not query.strip():
            return {
                "provider": provider,
                "model": model,
                "status": "skipped",
                "reason": "empty_query",
            }
        if not chunks:
            return {
                "provider": provider,
                "model": model,
                "status": "skipped",
                "reason": "no_chunks",
            }
        if provider == "llm":
            return None
        if not getattr(profile, "reranker_base_url", None):
            return {
                "provider": provider,
                "model": model,
                "status": "skipped",
                "reason": "missing_endpoint",
            }
        return None

    def _payload(self, query: str, chunks: list[ChunkOut], profile: Any) -> dict[str, Any]:
        documents = [chunk.text for chunk in chunks]
        payload: dict[str, Any] = {
            "query": query,
            "documents": documents,
            "top_n": len(documents),
        }
        if getattr(profile, "reranker_model", None):
            payload["model"] = profile.reranker_model
        return payload

    def _headers(self, profile: Any) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        api_key = getattr(profile, "reranker_api_key", None)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _scores(self, body: Any) -> dict[int, float]:
        if not isinstance(body, dict):
            return {}
        raw_results = body.get("results") or body.get("data") or body.get("rankings")
        if not isinstance(raw_results, list):
            return {}

        scores: dict[int, float] = {}
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            index = self._int_value(self._first_present(item, "index", "document_index"))
            score = self._float_value(
                self._first_present(item, "relevance_score", "score", "relevance")
            )
            if index is not None and score is not None:
                scores[index] = score
        return scores

    def _first_present(self, item: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in item:
                return item[key]
        return None

    def _int_value(self, value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _float_value(self, value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @asynccontextmanager
    async def _client(self, timeout: float) -> AsyncIterator[httpx.AsyncClient]:
        if self._http_client is not None:
            yield self._http_client
            return
        if self._http_client_provider is not None:
            yield self._http_client_provider.client("reranker", timeout=timeout)
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


def _host_matches_allowed_pattern(host: str, allowed: str) -> bool:
    if host == allowed:
        return True
    if "*" not in allowed:
        return False
    return _ipv4_wildcard_matches(host, allowed)


def _ipv4_wildcard_matches(host: str, pattern: str) -> bool:
    host_parts = host.split(".")
    pattern_parts = pattern.split(".")
    if len(host_parts) != 4 or len(pattern_parts) != 4:
        return False
    try:
        ipaddress.IPv4Address(host)
    except ValueError:
        return False
    for host_part, pattern_part in zip(host_parts, pattern_parts, strict=True):
        if pattern_part == "*":
            continue
        if host_part != pattern_part:
            return False
    return True
