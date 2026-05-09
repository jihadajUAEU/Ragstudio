from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx
from ragstudio.schemas.chunks import ChunkOut


class RerankerService:
    def __init__(self, allowed_hosts: list[str] | None = None):
        self.allowed_hosts = {host.lower() for host in (allowed_hosts or [])}

    async def rerank(
        self,
        query: str,
        chunks: list[ChunkOut],
        profile: Any,
    ) -> tuple[list[ChunkOut], list[dict[str, Any]]]:
        if not self._enabled(query, chunks, profile):
            return chunks, []
        if not self._is_allowed_endpoint(str(profile.reranker_base_url)):
            return chunks, [self._failure_trace(profile, "blocked_endpoint")]

        payload = self._payload(query, chunks, profile)
        headers = self._headers(profile)
        timeout = (getattr(profile, "reranker_timeout_ms", None) or 10000) / 1000
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    str(profile.reranker_base_url),
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
        except Exception as exc:
            return chunks, [self._failure_trace(profile, "failed", exc)]

        scores = self._scores(body)
        if not scores:
            return chunks, [
                {
                    "provider": profile.reranker_provider,
                    "model": profile.reranker_model,
                    "status": "no_results",
                }
            ]

        indexed_chunks = {index: chunk for index, chunk in enumerate(chunks)}
        ranked_indices = [
            index for index, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        ]
        reranked = [indexed_chunks[index] for index in ranked_indices if index in indexed_chunks]
        reranked.extend(chunk for index, chunk in indexed_chunks.items() if index not in scores)
        if not any(index in indexed_chunks for index in scores):
            return chunks, [
                {
                    "provider": profile.reranker_provider,
                    "model": profile.reranker_model,
                    "status": "no_usable_results",
                }
            ]

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

    def _is_allowed_endpoint(self, url: str) -> bool:
        if not self.allowed_hosts:
            return False
        host = (urlparse(url).hostname or "").lower()
        return host in self.allowed_hosts

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

    def _enabled(self, query: str, chunks: list[ChunkOut], profile: Any) -> bool:
        return (
            bool(query.strip())
            and bool(chunks)
            and bool(getattr(profile, "enable_rerank", False))
            and getattr(profile, "reranker_provider", "disabled") != "disabled"
            and bool(getattr(profile, "reranker_base_url", None))
        )

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
