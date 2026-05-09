from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

from ragstudio.db.models import SettingsProfile
from ragstudio.schemas.parsing import DomainMetadata, DomainMetadataSuggestOut
from ragstudio.services.page_sampler import SampledPage


@dataclass(frozen=True)
class LlmTarget:
    base_url: str
    model: str
    api_key: str | None
    timeout_ms: int
    source: str


class DomainMetadataAiSuggester:
    async def suggest(
        self,
        *,
        settings_profile: SettingsProfile,
        filename: str,
        content_type: str,
        pages: list[SampledPage],
        sampler_warnings: list[str],
    ) -> DomainMetadataSuggestOut:
        target = self._target(settings_profile)
        payload = self._payload(
            target=target,
            filename=filename,
            content_type=content_type,
            pages=pages,
        )
        headers = {"content-type": "application/json"}
        if target.api_key:
            headers["authorization"] = f"Bearer {target.api_key}"

        async with httpx.AsyncClient(timeout=target.timeout_ms / 1000) as client:
            response = await client.post(
                f"{target.base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
        if response.status_code >= 400:
            raise ValueError(f"Metadata autosuggest LLM returned HTTP {response.status_code}.")

        parsed = self._parse_json(self._message_content(response.json()))
        metadata = DomainMetadata.model_validate(parsed["domain_metadata"])
        metadata.metadata_sources = ["ai_vision" if target.source == "vision" else "ai_llm"]
        return DomainMetadataSuggestOut(
            domain_metadata=metadata,
            confidence=float(parsed.get("confidence", 0.0)),
            evidence_pages=[page.page_number for page in pages],
            rationale=str(parsed.get("rationale", "")),
            warnings=[*sampler_warnings, *list(parsed.get("warnings", []))],
        )

    def _target(self, profile: SettingsProfile) -> LlmTarget:
        if profile.vision_base_url and profile.vision_model:
            return LlmTarget(
                base_url=profile.vision_base_url,
                model=profile.vision_model,
                api_key=profile.vision_api_key,
                timeout_ms=profile.vision_timeout_ms or profile.llm_timeout_ms or 10000,
                source="vision",
            )
        if (
            profile.llm_base_url
            and profile.llm_model
            and "vision" in (profile.llm_capabilities or [])
        ):
            return LlmTarget(
                base_url=profile.llm_base_url,
                model=profile.llm_model,
                api_key=profile.llm_api_key,
                timeout_ms=profile.llm_timeout_ms or 10000,
                source="llm",
            )
        raise ValueError("Vision model is not configured for AI metadata autosuggest.")

    def _payload(
        self,
        *,
        target: LlmTarget,
        filename: str,
        content_type: str,
        pages: list[SampledPage],
    ) -> dict[str, object]:
        content: list[dict[str, object]] = [
            {
                "type": "text",
                "text": self._prompt(filename=filename, content_type=content_type, pages=pages),
            }
        ]
        if target.source == "vision":
            for page in pages:
                if page.image_data_url:
                    content.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": page.image_data_url},
                        }
                    )
        return {
            "model": target.model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
            "max_tokens": 900,
        }

    def _prompt(self, *, filename: str, content_type: str, pages: list[SampledPage]) -> str:
        page_text = "\n\n".join(
            f"Page {page.page_number} text excerpt:\n{page.text or '[no extracted text]'}"
            for page in pages
        )
        return f"""You classify documents for a RAG indexing system.
Be honest. Use only the sampled pages and filename as evidence.
Do not guess a specific collection unless the pages show it.
Return JSON only with this shape:
{{
  "domain_metadata": {{
    "domain": "short_domain",
    "document_type": "short_type",
    "language": "unknown|english|arabic|mixed|other",
    "tags": ["short", "tags"],
    "authority": null,
    "source": null,
    "collection": null,
    "citation_style": null,
    "expected_structure": null,
    "custom_json": {{}},
    "reference_pattern": null,
    "script": null,
    "content_role": null,
    "metadata_sources": ["ai_vision"]
  }},
  "confidence": 0.0,
  "rationale": "one sentence explaining evidence",
  "warnings": []
}}

Filename: {filename}
Content type: {content_type}

{page_text}
"""

    def _message_content(self, payload: object) -> str:
        if not isinstance(payload, dict):
            raise ValueError("LLM response was not a JSON object.")
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("LLM response did not include choices.")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ValueError("LLM response message content was not text.")
        return content

    def _parse_json(self, content: str) -> dict[str, object]:
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
            stripped = re.sub(r"```$", "", stripped).strip()
        data = json.loads(stripped)
        if not isinstance(data, dict):
            raise ValueError("LLM metadata suggestion was not a JSON object.")
        if "domain_metadata" not in data:
            raise ValueError("LLM metadata suggestion omitted domain_metadata.")
        return data
