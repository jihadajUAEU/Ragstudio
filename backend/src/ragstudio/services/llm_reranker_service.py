from __future__ import annotations

import json
from typing import Any

import httpx
from ragstudio.schemas.chunks import ChunkOut
from ragstudio.services.http_client_provider import HttpClientProviderProtocol
from ragstudio.services.http_retry import raise_for_transient_status, retry_async_http


class LLMRerankerService:
    def __init__(self, http_client_provider: HttpClientProviderProtocol | None = None) -> None:
        self.http_client_provider = http_client_provider

    async def rerank(
        self,
        query: str,
        chunks: list[ChunkOut],
        profile: Any,
    ) -> tuple[list[ChunkOut], list[dict[str, Any]]]:
        if not getattr(profile, "llm_base_url", None):
            return chunks, [
                {"provider": "llm", "status": "skipped", "reason": "missing_llm_base_url"}
            ]
        if not query.strip():
            return chunks, [{"provider": "llm", "status": "skipped", "reason": "empty_query"}]
        if not chunks:
            return chunks, [{"provider": "llm", "status": "skipped", "reason": "no_chunks"}]

        payload = _payload(query, chunks, profile)
        headers = {"Content-Type": "application/json"}
        api_key = getattr(profile, "llm_api_key", None)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            timeout = (getattr(profile, "llm_timeout_ms", None) or 10000) / 1000
            if self.http_client_provider is not None:
                client = self.http_client_provider.client("llm-reranker", timeout=timeout)
                response = await retry_async_http(
                    lambda: self._post_for_retry(
                        client,
                        _chat_url(str(profile.llm_base_url)),
                        headers=headers,
                        json=payload,
                    ),
                    attempts=2,
                )
            else:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await retry_async_http(
                        lambda: self._post_for_retry(
                            client,
                            _chat_url(str(profile.llm_base_url)),
                            headers=headers,
                            json=payload,
                        ),
                        attempts=2,
                    )
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            return chunks, [
                {
                    "provider": "llm",
                    "model": _model(profile),
                    "status": "failed",
                    "error_type": exc.__class__.__name__,
                    "detail": str(exc),
                }
            ]

        rankings = _rankings(_content(body))
        if not rankings:
            return chunks, [
                {"provider": "llm", "model": _model(profile), "status": "invalid_json"}
            ]

        indexed_chunks = {index: chunk for index, chunk in enumerate(chunks)}
        usable_rankings = [item for item in rankings if item["index"] in indexed_chunks]
        if not usable_rankings:
            return chunks, [
                {"provider": "llm", "model": _model(profile), "status": "no_usable_results"}
            ]

        ranked_indices = [
            item["index"]
            for item in sorted(usable_rankings, key=lambda item: item["score"], reverse=True)
        ]
        ranked_index_set = set(ranked_indices)
        reranked = [indexed_chunks[index] for index in ranked_indices]
        reranked.extend(
            chunk for index, chunk in indexed_chunks.items() if index not in ranked_index_set
        )

        by_index = {item["index"]: item for item in usable_rankings}
        traces = [
            {
                "provider": "llm",
                "model": _model(profile),
                "rank": rank,
                "original_rank": index + 1,
                "chunk_id": indexed_chunks[index].id,
                "score": by_index[index]["score"],
                "reason": by_index[index].get("reason", ""),
            }
            for rank, index in enumerate(ranked_indices, start=1)
        ]
        return reranked, traces

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


def _payload(query: str, chunks: list[ChunkOut], profile: Any) -> dict[str, Any]:
    evidence = "\n".join(f"[{index}] {chunk.text[:1200]}" for index, chunk in enumerate(chunks))
    return {
        "model": _model(profile),
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Rank evidence for the user query. Return only a JSON array. "
                    "Each item must contain index, score, and reason. Use zero-based "
                    "indexes from the provided evidence."
                ),
            },
            {"role": "user", "content": f"Query: {query}\n\nEvidence:\n{evidence}"},
        ],
    }


def _chat_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _model(profile: Any) -> str | None:
    return getattr(profile, "reranker_model", None) or getattr(profile, "llm_model", None)


def _content(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return ""
    message = first_choice.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    return ""


def _rankings(content: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []

    rankings: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        score = item.get("score")
        if isinstance(index, bool) or isinstance(score, bool):
            continue
        if isinstance(index, int) and isinstance(score, (int, float)):
            rankings.append(
                {
                    "index": index,
                    "score": float(score),
                    "reason": str(item.get("reason") or ""),
                }
            )
    return rankings
