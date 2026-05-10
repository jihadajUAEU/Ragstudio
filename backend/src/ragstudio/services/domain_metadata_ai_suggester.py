from __future__ import annotations

import json
import re
from dataclasses import dataclass
from itertools import islice
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError
from ragstudio.db.models import SettingsProfile
from ragstudio.schemas.parsing import DomainMetadata, DomainMetadataSuggestOut
from ragstudio.services.metadata_json_schema import validate_custom_json
from ragstudio.services.page_sampler import SampledPage

AUTOSUGGEST_MIN_TIMEOUT_MS = 60_000
BASELINE_PROMPT_MAX_STRING = 200
BASELINE_PROMPT_MAX_LIST = 12
BASELINE_PROMPT_MAX_DICT_ITEMS = 16
BASELINE_PROMPT_MAX_DEPTH = 5


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
        baseline_profile: DomainMetadata | None = None,
    ) -> DomainMetadataSuggestOut:
        target = self._target(settings_profile)
        payload = self._payload(
            target=target,
            filename=filename,
            content_type=content_type,
            pages=pages,
            baseline_profile=baseline_profile,
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

            parsed = self._sanitize_ai_suggestion_payload(
                self._parse_json(self._message_content(response.json()))
            )
            suggestion = AiMetadataSuggestion.model_validate(parsed)
        except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValidationError) as exc:
            raise ValueError(
                "Metadata autosuggest LLM response was invalid: "
                f"{self._exception_detail(exc)}"
            ) from exc

        metadata = suggestion.domain_metadata
        if baseline_profile is not None and not self._is_generic_baseline(baseline_profile):
            metadata = self.merge_with_baseline(metadata, baseline_profile)
            should_merge_baseline = True
        else:
            metadata.custom_json = self._normalize_custom_json(metadata.custom_json)
            should_merge_baseline = False
        validate_custom_json(metadata.custom_json)
        ai_source = "ai_vision" if target.supports_images else "ai_llm"
        if should_merge_baseline:
            metadata.metadata_sources = self._merge_unique_strings(
                metadata.metadata_sources,
                [ai_source],
            )
        else:
            metadata.metadata_sources = [ai_source]
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
                timeout_ms=max(
                    profile.vision_timeout_ms or profile.llm_timeout_ms or 10_000,
                    AUTOSUGGEST_MIN_TIMEOUT_MS,
                ),
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
                timeout_ms=max(
                    profile.llm_timeout_ms or 10_000,
                    AUTOSUGGEST_MIN_TIMEOUT_MS,
                ),
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
        baseline_profile: DomainMetadata | None = None,
    ) -> dict[str, object]:
        sampled_pages = pages[:4]
        content: list[dict[str, object]] = [
            {
                "type": "text",
                "text": self._prompt(
                    filename=filename,
                    content_type=content_type,
                    pages=sampled_pages,
                    baseline_profile=baseline_profile,
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

    def _prompt(
        self,
        *,
        filename: str,
        content_type: str,
        pages: list[SampledPage],
        baseline_profile: DomainMetadata | None = None,
    ) -> str:
        page_text = "\n\n".join(
            f"Page {page.page_number} text excerpt:\n{page.text or '[no extracted text]'}"
            for page in pages
        )
        baseline_text = (
            "No selected baseline profile."
            if baseline_profile is None
            else json.dumps(
                self._baseline_prompt_metadata(baseline_profile),
                ensure_ascii=False,
                indent=2,
            )
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

Selected baseline profile metadata:
{baseline_text}

When a baseline profile is provided, treat it as conservative domain guidance.
Fill empty fields from file evidence. Preserve strong baseline semantics unless
the sampled pages clearly contradict them. Do not copy file-specific values into
reusable profile assumptions.

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

    def _sanitize_ai_suggestion_payload(
        self,
        data: dict[str, object],
    ) -> dict[str, object]:
        metadata = data.get("domain_metadata")
        if not isinstance(metadata, dict):
            return data
        if not isinstance(metadata.get("custom_json", {}), dict):
            sanitized = dict(data)
            sanitized_metadata = dict(metadata)
            sanitized_metadata["custom_json"] = {}
            sanitized["domain_metadata"] = sanitized_metadata
            return sanitized
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

    def _exception_detail(self, exc: Exception) -> str:
        detail = str(exc).strip()
        if detail:
            return f"{type(exc).__name__}: {detail}"
        return type(exc).__name__

    def merge_with_baseline(
        self,
        ai_metadata: DomainMetadata,
        baseline: DomainMetadata,
    ) -> DomainMetadata:
        merged = baseline.model_copy(deep=True)
        for field in (
            "language",
            "authority",
            "source",
            "collection",
            "citation_style",
            "expected_structure",
            "reference_pattern",
            "script",
            "content_role",
        ):
            before = getattr(merged, field)
            after = getattr(ai_metadata, field)
            if self._is_empty_metadata_value(before) and not self._is_empty_metadata_value(
                after
            ):
                setattr(merged, field, after)

        merged.tags = self._merge_unique_strings(baseline.tags, ai_metadata.tags)
        merged.metadata_sources = ["profile"]
        merged.custom_json = self._merge_custom_json(
            baseline.custom_json,
            ai_metadata.custom_json,
        )
        return merged

    def _baseline_prompt_metadata(self, baseline: DomainMetadata) -> dict[str, object]:
        prompt_metadata: dict[str, object] = {
            "domain": self._bounded_prompt_value(baseline.domain),
            "document_type": self._bounded_prompt_value(baseline.document_type),
            "language": self._bounded_prompt_value(baseline.language),
        }
        for field in (
            "tags",
            "citation_style",
            "expected_structure",
            "reference_pattern",
            "script",
            "content_role",
        ):
            value = getattr(baseline, field)
            if not self._is_empty_metadata_value(value):
                bounded_value = self._bounded_prompt_value(value)
                if bounded_value not in (None, "", [], {}):
                    prompt_metadata[field] = bounded_value

        custom_json = self._bounded_prompt_value(
            self._normalize_custom_json(baseline.custom_json)
        )
        if isinstance(custom_json, dict) and custom_json:
            prompt_metadata["custom_json"] = custom_json
        return prompt_metadata

    def _bounded_prompt_value(self, value: Any, *, depth: int = 0) -> object:
        if depth > BASELINE_PROMPT_MAX_DEPTH:
            return None
        if isinstance(value, str):
            return value[:BASELINE_PROMPT_MAX_STRING]
        if isinstance(value, list):
            bounded_items = []
            for item in value[:BASELINE_PROMPT_MAX_LIST]:
                bounded_item = self._bounded_prompt_value(item, depth=depth + 1)
                if bounded_item not in (None, "", [], {}):
                    bounded_items.append(bounded_item)
            return bounded_items
        if isinstance(value, dict):
            bounded: dict[str, object] = {}
            for key, item in islice(value.items(), BASELINE_PROMPT_MAX_DICT_ITEMS):
                if not isinstance(key, str):
                    continue
                bounded_item = self._bounded_prompt_value(item, depth=depth + 1)
                if bounded_item not in (None, "", [], {}):
                    bounded[key[:BASELINE_PROMPT_MAX_STRING]] = bounded_item
            return bounded
        if isinstance(value, (bool, int, float)) or value is None:
            return value
        return None

    def _is_empty_metadata_value(self, value: object) -> bool:
        return value is None or value == "" or value == "unknown"

    def _is_generic_baseline(self, value: DomainMetadata) -> bool:
        if value.domain != "generic" or value.document_type != "document":
            return False

        return (
            self._is_empty_metadata_value(value.language)
            and value.tags in ([], ["document"])
            and value.authority is None
            and value.source is None
            and value.collection is None
            and value.citation_style is None
            and value.expected_structure in (None, "sections")
            and value.custom_json in ({}, {"chunking": {"unit": "section"}})
            and value.reference_pattern is None
            and value.script is None
            and value.content_role is None
            and value.metadata_sources == []
        )

    def _merge_unique_strings(self, first: list[str], second: list[str]) -> list[str]:
        merged: list[str] = []
        for item in [*first, *second]:
            if isinstance(item, str) and item and item not in merged:
                merged.append(item)
        return merged

    def _merge_custom_json(
        self,
        baseline: dict[str, object],
        ai_value: dict[str, object],
    ) -> dict[str, object]:
        merged = self._normalize_custom_json(baseline)
        ai = self._normalize_custom_json(ai_value, require_graph_policy=False)
        for key in ("reference_schema", "relationships", "chunking", "retrieval", "graph"):
            base_section = merged.get(key)
            ai_section = ai.get(key)
            if isinstance(base_section, dict) and isinstance(ai_section, dict):
                merged[key] = self._deep_merge_dicts(base_section, ai_section)
            elif ai_section is not None and key not in merged:
                if key == "graph" and not self._has_required_graph_policy(ai_section):
                    continue
                merged[key] = ai_section
        return merged

    def _deep_merge_dicts(
        self,
        first: dict[str, object],
        second: dict[str, object],
    ) -> dict[str, object]:
        merged = dict(first)
        for key, value in second.items():
            existing = merged.get(key)
            if isinstance(existing, dict) and isinstance(value, dict):
                merged[key] = self._deep_merge_dicts(existing, value)
            elif isinstance(existing, list) and isinstance(value, list):
                merged[key] = self._merge_unique_strings(existing, value)
            elif key not in merged or self._is_empty_metadata_value(existing):
                merged[key] = value
        return merged

    def _normalize_custom_json(
        self,
        value: dict[str, object],
        *,
        require_graph_policy: bool = True,
    ) -> dict[str, object]:
        normalized: dict[str, object] = {}
        reference_schema = value.get("reference_schema")
        if isinstance(reference_schema, dict):
            schema: dict[str, object] = {}
            for key in ("type", "display"):
                item = reference_schema.get(key)
                if isinstance(item, str):
                    schema[key] = item
            for key in ("pattern", "regex"):
                item = reference_schema.get(key)
                if isinstance(item, str) and self._is_valid_reference_pattern(key, item):
                    schema[key] = item
            fields = reference_schema.get("fields")
            if isinstance(fields, dict):
                string_fields = {
                    key: field_value
                    for key, field_value in fields.items()
                    if isinstance(key, str) and isinstance(field_value, str)
                }
                if string_fields:
                    schema["fields"] = string_fields
            if schema:
                normalized["reference_schema"] = schema

        relationships = value.get("relationships")
        if isinstance(relationships, dict):
            relationship_values = {
                key: [item for item in items if isinstance(item, str)]
                for key, items in relationships.items()
                if isinstance(key, str) and isinstance(items, list)
            }
            relationship_values = {
                key: items for key, items in relationship_values.items() if items
            }
            if relationship_values:
                normalized["relationships"] = relationship_values

        chunking = value.get("chunking")
        if isinstance(chunking, dict):
            chunking_values: dict[str, object] = {}
            unit = chunking.get("unit")
            include_neighbors = chunking.get("include_neighbors")
            preserve_parallel_text = chunking.get("preserve_parallel_text")
            if isinstance(unit, str):
                chunking_values["unit"] = unit
            if isinstance(include_neighbors, int) and not isinstance(include_neighbors, bool):
                chunking_values["include_neighbors"] = max(0, include_neighbors)
            if isinstance(preserve_parallel_text, bool):
                chunking_values["preserve_parallel_text"] = preserve_parallel_text
            if chunking_values:
                normalized["chunking"] = chunking_values

        retrieval = value.get("retrieval")
        if isinstance(retrieval, dict):
            retrieval_values = {
                key: retrieval_value
                for key, retrieval_value in retrieval.items()
                if isinstance(key, str) and isinstance(retrieval_value, bool)
            }
            if retrieval_values:
                normalized["retrieval"] = retrieval_values

        graph = value.get("graph")
        if isinstance(graph, dict):
            graph_values: dict[str, object] = {}
            for key in ("node_types", "edge_types", "materialize_from"):
                items = graph.get(key)
                if isinstance(items, list):
                    strings = [item for item in items if isinstance(item, str) and item]
                    if strings:
                        graph_values[key] = strings
            confidence_policy = graph.get("confidence_policy")
            if confidence_policy == "evidence_required":
                graph_values["confidence_policy"] = confidence_policy
            if graph_values and (
                not require_graph_policy or self._has_required_graph_policy(graph_values)
            ):
                normalized["graph"] = graph_values

        return normalized

    def _has_required_graph_policy(self, value: object) -> bool:
        return (
            isinstance(value, dict)
            and value.get("confidence_policy") == "evidence_required"
        )

    def _is_valid_reference_pattern(self, key: str, value: str) -> bool:
        try:
            validate_custom_json({"reference_schema": {key: value}})
        except ValueError:
            return False
        return True
