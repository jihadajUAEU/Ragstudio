from typing import Any
from urllib.parse import urlparse

import httpx
from ragstudio.schemas.settings import (
    MINERU_DEFAULT_TIMEOUT_MS,
    RUNTIME_TIMEOUT_MAX_MS,
    RUNTIME_TIMEOUT_MIN_MS,
    ProviderSyncPreviewOut,
    SettingsProfileOut,
)

SUPPORTED_SECTIONS = {"reasoning", "embeddings", "hpcMineru", "reranker"}
KNOWN_SECTIONS = {"stt", "reasoning", "embeddings", "ragAnything", "hpcMineru", "reranker"}
CAPABILITIES = {"text", "vision", "reasoning"}


class ProviderManifestError(Exception):
    pass


class ProviderManifestService:
    async def preview(
        self,
        manifest_url: str,
        current: SettingsProfileOut | None,
        timeout_s: float = 5.0,
    ) -> ProviderSyncPreviewOut:
        manifest = await self._fetch_manifest(manifest_url, timeout_s)
        patch = self._build_patch(manifest)
        ignored_sections = sorted(
            key for key in manifest if key in KNOWN_SECTIONS and key not in SUPPORTED_SECTIONS
        )
        changed_fields = self._changed_fields(patch, current)
        manifest_version = manifest.get("version")
        updated_at = manifest.get("updatedAt")
        return ProviderSyncPreviewOut(
            ok=True,
            manifest_url=manifest_url,
            manifest_version=manifest_version if isinstance(manifest_version, int) else None,
            updated_at=updated_at if isinstance(updated_at, str) else None,
            patch=patch,
            changed_fields=changed_fields,
            ignored_sections=ignored_sections,
            detail="Provider manifest preview generated.",
        )

    async def _fetch_manifest(self, manifest_url: str, timeout_s: float) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.get(manifest_url)
            if response.status_code >= 400:
                raise ProviderManifestError(
                    f"Provider manifest returned HTTP {response.status_code}."
                )
            payload = response.json()
        except ProviderManifestError:
            raise
        except httpx.HTTPError as exc:
            raise ProviderManifestError(str(exc)) from exc
        except ValueError as exc:
            raise ProviderManifestError("Provider manifest must be valid JSON.") from exc

        if not isinstance(payload, dict):
            raise ProviderManifestError("Provider manifest must be a JSON object.")

        for section in SUPPORTED_SECTIONS:
            if section in payload and not isinstance(payload[section], dict):
                raise ProviderManifestError(
                    f"Provider manifest section {section} must be an object."
                )
        self._validate_supported_fields(payload)
        return payload

    def _validate_supported_fields(self, manifest: dict[str, Any]) -> None:
        reasoning = manifest.get("reasoning")
        if isinstance(reasoning, dict):
            self._validate_optional_str(reasoning, "apiUrl", "reasoning.apiUrl")
            self._validate_optional_str(reasoning, "model", "reasoning.model")
            self._validate_optional_int_range(
                reasoning,
                "timeoutMs",
                "reasoning.timeoutMs",
                minimum=RUNTIME_TIMEOUT_MIN_MS,
                maximum=RUNTIME_TIMEOUT_MAX_MS,
            )
            self._validate_optional_capabilities(reasoning)

        embeddings = manifest.get("embeddings")
        if isinstance(embeddings, dict):
            self._validate_optional_str(embeddings, "apiUrl", "embeddings.apiUrl")
            self._validate_optional_str(embeddings, "model", "embeddings.model")
            self._validate_optional_positive_int(
                embeddings, "dimensions", "embeddings.dimensions"
            )
            self._validate_optional_int_range(
                embeddings,
                "timeoutMs",
                "embeddings.timeoutMs",
                minimum=RUNTIME_TIMEOUT_MIN_MS,
                maximum=RUNTIME_TIMEOUT_MAX_MS,
            )

        mineru = manifest.get("hpcMineru")
        if isinstance(mineru, dict):
            if "enabled" in mineru and not isinstance(mineru["enabled"], bool):
                raise ProviderManifestError(
                    "Provider manifest field hpcMineru.enabled must be a boolean."
                )
            self._validate_optional_str(mineru, "apiUrl", "hpcMineru.apiUrl")
            self._validate_optional_positive_int(
                mineru, "timeoutMs", "hpcMineru.timeoutMs"
            )
            self._validate_optional_str(mineru, "backend", "hpcMineru.backend")
            self._validate_optional_str(mineru, "device", "hpcMineru.device")
            self._validate_optional_str(mineru, "lang", "hpcMineru.lang")
            if "formula" in mineru and not isinstance(mineru["formula"], bool):
                raise ProviderManifestError(
                    "Provider manifest field hpcMineru.formula must be a boolean."
                )
            if "table" in mineru and not isinstance(mineru["table"], bool):
                raise ProviderManifestError(
                    "Provider manifest field hpcMineru.table must be a boolean."
                )
            self._validate_optional_str(mineru, "source", "hpcMineru.source")
            self._validate_optional_int_range(
                mineru,
                "maxConcurrentFiles",
                "hpcMineru.maxConcurrentFiles",
                minimum=1,
                maximum=8,
            )

        reranker = manifest.get("reranker")
        if isinstance(reranker, dict):
            if "enabled" in reranker and not isinstance(reranker["enabled"], bool):
                raise ProviderManifestError(
                    "Provider manifest field reranker.enabled must be a boolean."
                )
            self._validate_optional_str(reranker, "apiUrl", "reranker.apiUrl")
            self._validate_optional_str(reranker, "model", "reranker.model")
            self._validate_optional_str(reranker, "endpoint", "reranker.endpoint")
            self._validate_optional_int_range(
                reranker,
                "timeoutMs",
                "reranker.timeoutMs",
                minimum=RUNTIME_TIMEOUT_MIN_MS,
                maximum=RUNTIME_TIMEOUT_MAX_MS,
            )

    def _validate_optional_str(
        self, section: dict[str, Any], key: str, field_name: str
    ) -> None:
        if key in section and not isinstance(section[key], str):
            raise ProviderManifestError(
                f"Provider manifest field {field_name} must be a string."
            )

    def _validate_optional_positive_int(
        self, section: dict[str, Any], key: str, field_name: str
    ) -> None:
        value = section.get(key)
        if key in section and (
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
        ):
            raise ProviderManifestError(
                f"Provider manifest field {field_name} must be a positive integer."
            )

    def _validate_optional_int_range(
        self,
        section: dict[str, Any],
        key: str,
        field_name: str,
        *,
        minimum: int,
        maximum: int,
    ) -> None:
        value = section.get(key)
        if key not in section:
            return
        if not isinstance(value, int) or isinstance(value, bool):
            raise ProviderManifestError(
                f"Provider manifest field {field_name} must be an integer."
            )
        if value < minimum or value > maximum:
            raise ProviderManifestError(
                f"Provider manifest field {field_name} must be between {minimum} and {maximum}."
            )

    def _validate_optional_capabilities(self, section: dict[str, Any]) -> None:
        raw = section.get("capabilities")
        if "capabilities" in section and (
            not isinstance(raw, list) or any(not isinstance(item, str) for item in raw)
        ):
            raise ProviderManifestError(
                "Provider manifest field reasoning.capabilities must be a list of strings."
            )

    def _build_patch(self, manifest: dict[str, Any]) -> dict[str, object]:
        patch: dict[str, object] = {}
        reasoning = manifest.get("reasoning")
        if isinstance(reasoning, dict):
            api_url = self._optional_str(reasoning.get("apiUrl"))
            model = self._optional_str(reasoning.get("model"))
            timeout_ms = self._optional_int(reasoning.get("timeoutMs"))
            if api_url:
                patch["llm_provider"] = "openai_compatible"
                patch["llm_base_url"] = api_url.rstrip("/")
            if model:
                patch["llm_model"] = model
            if timeout_ms is not None:
                patch["llm_timeout_ms"] = timeout_ms
            capabilities = self._capabilities(reasoning.get("capabilities"), model)
            if capabilities:
                patch["llm_capabilities"] = capabilities

        embeddings = manifest.get("embeddings")
        if isinstance(embeddings, dict):
            api_url = self._optional_str(embeddings.get("apiUrl"))
            model = self._optional_str(embeddings.get("model"))
            dimensions = self._optional_int(embeddings.get("dimensions"))
            timeout_ms = self._optional_int(embeddings.get("timeoutMs"))
            if api_url:
                patch["embedding_provider"] = "vllm_openai"
                patch["embedding_base_url"] = api_url.rstrip("/")
            if model:
                patch["embedding_provider"] = "vllm_openai"
                patch["embedding_model"] = model
            if dimensions is not None:
                patch["embedding_dimensions"] = dimensions
            if timeout_ms is not None:
                patch["embedding_timeout_ms"] = timeout_ms

        mineru = manifest.get("hpcMineru")
        if isinstance(mineru, dict):
            enabled = mineru.get("enabled")
            api_url = self._optional_str(mineru.get("apiUrl"))
            timeout_ms = self._optional_int(mineru.get("timeoutMs"))
            backend = self._optional_str(mineru.get("backend"))
            device = self._optional_str(mineru.get("device"))
            lang = self._optional_str(mineru.get("lang"))
            source = self._optional_str(mineru.get("source"))
            max_concurrent_files = self._optional_int(mineru.get("maxConcurrentFiles"))
            if isinstance(enabled, bool):
                patch["mineru_enabled"] = enabled
                if enabled:
                    patch["mineru_require_hpc"] = True
            if api_url:
                patch["mineru_base_url"] = api_url.rstrip("/")
            if timeout_ms is not None:
                patch["mineru_timeout_ms"] = max(timeout_ms, MINERU_DEFAULT_TIMEOUT_MS)
            if backend:
                patch["mineru_backend"] = backend
            if device:
                patch["mineru_device"] = device
            if lang:
                patch["mineru_lang"] = lang
            if isinstance(mineru.get("formula"), bool):
                patch["mineru_formula"] = mineru["formula"]
            if isinstance(mineru.get("table"), bool):
                patch["mineru_table"] = mineru["table"]
            if source:
                patch["mineru_source"] = source
            if max_concurrent_files is not None:
                patch["mineru_max_concurrent_files"] = max_concurrent_files

        reranker = manifest.get("reranker")
        if isinstance(reranker, dict):
            enabled = reranker.get("enabled")
            api_url = self._optional_str(reranker.get("apiUrl"))
            endpoint = self._optional_str(reranker.get("endpoint"))
            model = self._optional_str(reranker.get("model"))
            timeout_ms = self._optional_int(reranker.get("timeoutMs"))
            if enabled is False:
                patch["enable_rerank"] = False
                patch["reranker_provider"] = "disabled"
            elif api_url or endpoint or model or timeout_ms is not None or enabled is True:
                patch["enable_rerank"] = True
                if api_url or endpoint:
                    reranker_url = self._reranker_endpoint_url(api_url, endpoint)
                    if reranker_url:
                        patch["reranker_provider"] = "generic_http"
                        patch["reranker_base_url"] = reranker_url
                if model:
                    patch["reranker_provider"] = "generic_http"
                    patch["reranker_model"] = model
                if timeout_ms is not None:
                    patch["reranker_timeout_ms"] = timeout_ms

        return patch

    def _reranker_endpoint_url(self, api_url: str | None, endpoint: str | None) -> str | None:
        if endpoint:
            endpoint_parsed = urlparse(endpoint)
            if endpoint_parsed.scheme in {"http", "https"} and endpoint_parsed.netloc:
                return endpoint.rstrip("/")

        if not api_url:
            return None

        base = api_url.rstrip("/")
        if not endpoint:
            return base if base.endswith("/rerank") else f"{base}/rerank"

        endpoint_path = f"/{endpoint.strip('/')}"
        parsed_base = urlparse(base)
        base_path = parsed_base.path.rstrip("/")
        if (
            parsed_base.scheme in {"http", "https"}
            and parsed_base.netloc
            and base_path
            and endpoint_path.startswith(f"{base_path}/")
        ):
            return f"{parsed_base.scheme}://{parsed_base.netloc}{endpoint_path}"
        return f"{base}{endpoint_path}"

    def _capabilities(self, raw: object, model: str | None) -> list[str]:
        if isinstance(raw, list):
            explicit = [item for item in raw if isinstance(item, str) and item in CAPABILITIES]
            if explicit:
                return self._ordered_capabilities(explicit)

        inferred = ["text", "reasoning"]
        model_text = (model or "").lower()
        if "vl" in model_text or "vision" in model_text or "multimodal" in model_text:
            inferred.append("vision")
        return self._ordered_capabilities(inferred)

    def _ordered_capabilities(self, values: list[str]) -> list[str]:
        return [
            capability
            for capability in ["text", "vision", "reasoning"]
            if capability in values
        ]

    def _changed_fields(
        self, patch: dict[str, object], current: SettingsProfileOut | None
    ) -> list[str]:
        if current is None:
            return sorted(patch)
        current_map = current.model_dump()
        return sorted(key for key, value in patch.items() if current_map.get(key) != value)

    def _optional_str(self, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped or None

    def _optional_int(self, value: object) -> int | None:
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
        return None
