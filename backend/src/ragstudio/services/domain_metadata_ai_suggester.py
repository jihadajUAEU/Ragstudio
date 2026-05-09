from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, Field, ValidationError

from ragstudio.db.models import SettingsProfile
from ragstudio.schemas.parsing import DomainMetadata, DomainMetadataSuggestOut
from ragstudio.services.metadata_json_schema import validate_custom_json
from ragstudio.services.page_sampler import SampledPage


@dataclass(frozen=True)
class LlmTarget:
    base_url: str
    model: str
    api_key: str | None
    timeout_ms: int
    source: str
    supports_images: bool


class AiMetadataSuggestion(BaseModel):
    domain_metadata: DomainMetadata
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_pages: list[int] = Field(default_factory=list)
    rationale: str = ""
    warnings: list[str] = Field(default_factory=list)


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

        try:
            response = await self._post_completion(target, headers, payload)
            if response.status_code >= 400:
                raise ValueError(
                    f"Metadata autosuggest LLM returned HTTP {response.status_code}."
                )

            parsed = self._parse_json(self._message_content(response.json()))
            suggestion = AiMetadataSuggestion.model_validate(parsed)
        except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValidationError) as exc:
            raise ValueError(f"Metadata autosuggest LLM response was invalid: {exc}") from exc

        metadata = suggestion.domain_metadata
        validate_custom_json(metadata.custom_json)
        metadata.metadata_sources = ["ai_vision" if target.supports_images else "ai_llm"]
        evidence_pages = self._validated_evidence_pages(suggestion.evidence_pages, pages)
        return DomainMetadataSuggestOut(
            domain_metadata=metadata,
            confidence=suggestion.confidence,
            evidence_pages=evidence_pages,
            rationale=suggestion.rationale,
            warnings=[*sampler_warnings, *suggestion.warnings],
        )

    def _target(self, profile: SettingsProfile) -> LlmTarget:
        if profile.vision_base_url and profile.vision_model:
            return LlmTarget(
                base_url=profile.vision_base_url,
                model=profile.vision_model,
                api_key=profile.vision_api_key,
                timeout_ms=profile.vision_timeout_ms or profile.llm_timeout_ms or 10000,
                source="vision",
                supports_images=True,
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
                supports_images=True,
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
        sampled_pages = pages[:4]
        content: list[dict[str, object]] = [
            {
                "type": "text",
                "text": self._prompt(
                    filename=filename,
                    content_type=content_type,
                    pages=sampled_pages,
                ),
            }
        ]
        if target.supports_images:
            for page in sampled_pages:
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
            "response_format": {"type": "json_object"},
        }

    async def _post_completion(
        self,
        target: LlmTarget,
        headers: dict[str, str],
        payload: dict[str, object],
    ) -> httpx.Response:
        url = f"{target.base_url.rstrip('/')}/chat/completions"
        async with httpx.AsyncClient(timeout=target.timeout_ms / 1000) as client:
            response = await client.post(url, headers=headers, json=payload)
            if (
                response.status_code not in {400, 422}
                or "response_format" not in payload
                or not self._is_response_format_rejection(response)
            ):
                return response

            fallback_payload = dict(payload)
            fallback_payload.pop("response_format", None)
            return await client.post(url, headers=headers, json=fallback_payload)

    def _is_response_format_rejection(self, response: httpx.Response) -> bool:
        try:
            error_text = json.dumps(response.json())
        except (json.JSONDecodeError, TypeError, ValueError):
            error_text = getattr(response, "text", "")
        lower_error = error_text.lower()
        return "response_format" in lower_error or (
            "response format" in lower_error and "unsupported" in lower_error
        )

    def _prompt(self, *, filename: str, content_type: str, pages: list[SampledPage]) -> str:
        page_text = "\n\n".join(
            f"Page {page.page_number} text excerpt:\n{page.text or '[no extracted text]'}"
            for page in pages
        )
        return f"""You classify documents for a RAG indexing system.
Be honest. Use only the sampled pages and filename as evidence.
Do not guess a specific collection unless the pages show it.
Review the 3-4 sampled pages/images when available. If the samples show structured
references that users may need to edit or tune, propose generic reference semantics
in custom_json instead of relying on a hardcoded local strategy. Examples include
Quran chapter:verse references, legal sections/subsections, page-line references,
case or article citations, and similar cited corpora.
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
    "custom_json": {{
      "reference_schema": null,
      "relationships": null,
      "chunking": null,
      "retrieval": null
    }},
    "reference_pattern": null,
    "script": null,
    "content_role": null,
    "metadata_sources": ["ai_vision"]
  }},
  "confidence": 0.0,
  "evidence_pages": [1],
  "rationale": "one sentence explaining evidence",
  "warnings": []
}}

For custom_json.reference_schema, describe the editable reference type, display
format, fields, and any observed pattern only when supported by the samples.
For custom_json.relationships, describe useful relationships such as previous,
next, same_section, same_page, same_article, or same_chapter when they are visible
or strongly implied by the reference system.
For custom_json.chunking, suggest the natural chunk unit and whether neighboring
references, parallel text, headings, page-line spans, or section boundaries should
be preserved.
For custom_json.retrieval, suggest honest retrieval hints such as exact reference
top result, same-section boosting, neighbor expansion, or page-line matching only
when the samples justify them. Leave these custom_json keys null or omit details
when the document does not show structured references.

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

    def _validated_evidence_pages(
        self,
        evidence_pages: list[int],
        sampled_pages: list[SampledPage],
    ) -> list[int]:
        sampled = {page.page_number for page in sampled_pages}
        validated: list[int] = []
        for page_number in evidence_pages:
            if page_number in sampled and page_number not in validated:
                validated.append(page_number)
        return validated
