from typing import Any

import httpx
from ragstudio.schemas.settings import ProviderSyncPreviewOut, SettingsProfileOut

SUPPORTED_SECTIONS = {"reasoning", "embeddings", "hpcMineru"}
KNOWN_SECTIONS = {"stt", "reasoning", "embeddings", "ragAnything", "hpcMineru"}
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
        return payload

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
            if isinstance(enabled, bool):
                patch["mineru_enabled"] = enabled
            if api_url:
                patch["mineru_base_url"] = api_url.rstrip("/")
            if timeout_ms is not None:
                patch["mineru_timeout_ms"] = timeout_ms

        return patch

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
        if isinstance(value, int) and value > 0:
            return value
        return None
