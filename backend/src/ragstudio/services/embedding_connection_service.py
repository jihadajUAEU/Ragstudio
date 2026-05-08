from time import perf_counter
from typing import Any

import httpx
from ragstudio.schemas.settings import EmbeddingConnectionTestOut, SettingsProfileIn


class EmbeddingConnectionService:
    async def test(self, settings: SettingsProfileIn) -> EmbeddingConnectionTestOut:
        start = perf_counter()
        if settings.embedding_provider == "fallback":
            return EmbeddingConnectionTestOut(
                ok=True,
                provider=settings.embedding_provider,
                model=settings.embedding_model,
                dimensions=None,
                latency_ms=0,
                detail="Local fallback embeddings selected.",
            )

        if not settings.embedding_base_url:
            return self._result(
                settings=settings,
                start=start,
                ok=False,
                dimensions=None,
                detail="Embedding base URL is required for vLLM/OpenAI-compatible embeddings.",
            )
        if not settings.embedding_model.strip():
            return self._result(
                settings=settings,
                start=start,
                ok=False,
                dimensions=None,
                detail="Embedding model is required.",
            )

        headers = {"content-type": "application/json"}
        if settings.embedding_api_key:
            headers["authorization"] = f"Bearer {settings.embedding_api_key}"

        try:
            async with httpx.AsyncClient(timeout=settings.embedding_timeout_ms / 1000) as client:
                response = await client.post(
                    f"{settings.embedding_base_url}/embeddings",
                    headers=headers,
                    json={
                        "model": settings.embedding_model,
                        "input": "Ragstudio embedding connection test",
                        "dimensions": settings.embedding_dimensions,
                    },
                )
            if response.status_code == 401:
                detail = "Embedding endpoint rejected the API key."
            elif response.status_code == 404:
                detail = "Embedding endpoint was not found. Check that the base URL ends with /v1."
            elif response.status_code >= 400:
                detail = f"Embedding endpoint returned HTTP {response.status_code}."
            else:
                payload = response.json()
                embedding = self._first_embedding(payload)
                dimensions = len(embedding) if embedding else None
                if not dimensions:
                    detail = "Embedding endpoint returned no vector."
                elif dimensions != settings.embedding_dimensions:
                    detail = (
                        f"Embedding endpoint returned {dimensions} dimensions; "
                        f"expected {settings.embedding_dimensions}."
                    )
                else:
                    return self._result(
                        settings=settings,
                        start=start,
                        ok=True,
                        dimensions=dimensions,
                        detail="Embedding endpoint returned a valid vector.",
                    )
        except httpx.TimeoutException:
            detail = "Embedding endpoint timed out."
        except httpx.ConnectError:
            detail = "Could not connect to embedding endpoint."
        except httpx.HTTPError:
            detail = "Embedding endpoint request failed."
        except ValueError:
            detail = "Embedding endpoint returned invalid JSON."

        return self._result(
            settings=settings,
            start=start,
            ok=False,
            dimensions=None,
            detail=detail,
        )

    def _first_embedding(self, payload: Any) -> list[float] | None:
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        if not isinstance(data, list) or not data:
            return None
        first = data[0]
        if not isinstance(first, dict):
            return None
        embedding = first.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            return None
        if not all(isinstance(item, int | float) for item in embedding):
            return None
        return embedding

    def _result(
        self,
        *,
        settings: SettingsProfileIn,
        start: float,
        ok: bool,
        dimensions: int | None,
        detail: str,
    ) -> EmbeddingConnectionTestOut:
        return EmbeddingConnectionTestOut(
            ok=ok,
            provider=settings.embedding_provider,
            model=settings.embedding_model,
            dimensions=dimensions,
            latency_ms=round((perf_counter() - start) * 1000),
            detail=detail,
        )
