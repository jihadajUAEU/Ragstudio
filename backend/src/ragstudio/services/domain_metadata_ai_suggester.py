# pyright: reportArgumentType=false, reportCallIssue=false, reportReturnType=false
from __future__ import annotations

import json
import re
from collections.abc import Sequence
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
        metadata.custom_json = self._apply_autosuggest_reference_defaults(metadata)
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
        sampled_pages = pages[:10]
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
                            "type": "text",
                            "text": f"Page {page.page_number} image:",
                        }
                    )
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
            "max_tokens": 1400,
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
Review up to 10 sampled pages/images when available. If the samples show structured
references that users may need to edit or tune, propose generic reference semantics
in custom_json instead of relying on a hardcoded local strategy. Separate primary answerable units
from inline cross-references, and provide a document-specific quality/script policy
and layout/block recovery policy instead of only broad domain metadata.
Examples include Quran chapter:verse references, legal sections/subsections,
page-line references, case or article citations, and similar cited corpora.
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
      "domain_structure": {{
        "primary_anchor": {{
          "type": null,
          "regex": null,
          "unit": null
        }},
        "inline_references": {{
          "type": null,
          "regex": null,
          "policy": "cross_reference_only|starts_unit|ignore"
        }}
      }},
      "quality_policy": {{
        "document_role": null,
        "observed_scripts": [],
        "required_scripts": [],
        "optional_scripts": [],
        "required_scripts_by_unit_role": {{}},
        "optional_scripts_by_unit_role": {{}},
        "missing_required_script_action": "warn|block|info|no_warning",
        "missing_optional_script_action": "no_warning|info|warn|block",
        "materialization_policy": "allow_if_required_scripts_present",
        "evidence": [{{"page": 1, "observation": "short evidence"}}],
        "confidence": 0.0
      }},
      "layout_quality_policy": {{
        "expected_block_roles": {{}},
        "misclassified_block_policy": {{
          "equation_with_recovered_text": {{
            "treat_as": null,
            "action": "recover_as_text|ignore|block",
            "warning_level": "info|warn|block"
          }}
        }},
        "disallowed_block_policy": {{
          "text_bearing_disallowed_block": {{
            "action": "recover_as_text|ignore|block",
            "warning_level": "info|warn|block"
          }}
        }},
        "failure_policy": {{
          "required_text_not_recovered": "info|warn|block",
          "unreadable_primary_anchor": "info|warn|block"
        }}
      }},
      "vision_recovery_policy": {{
        "enabled": false,
        "target_block_types": ["image", "figure", "equation"],
        "triggers": [
          "missing_pdf_text_layer",
          "suspected_text_misclassified_as_equation",
          "missing_required_script"
        ],
        "languages": [],
        "max_blocks_per_page": 3,
        "max_total_blocks": 40,
        "failure_action": "info|warn|block",
        "prompt_hint": null,
        "evidence": [{{"page": 1, "observation": "short evidence"}}],
        "confidence": 0.0
      }},
      "mineru_parse_options": null,
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
For custom_json.domain_structure, identify the text pattern that starts a primary
answerable unit and distinguish it from inline cross-references. For example, a
Tafseer page may use "Verse 18:30" as the section anchor while "25:75-76" inside
the commentary is only a cross-reference.
For hadith collections, Book N, Hadith N usually starts the primary answerable
hadith unit. Quran-style parenthetical references such as (6:83), (31:13), or
(3:64) inside a hadith explanation are cross-references/provenance only unless
the page visibly uses them as the primary heading pattern.
For custom_json.quality_policy, identify which scripts are visible, which scripts
are required for answerable chunks, which scripts are optional enrichment, whether
missing optional script should warn, and page-level evidence for each decision.
If sampled pages show English-only translations alongside Arabic-bearing hadith
records, do not require Arabic for every English-only translation unit; make Arabic
optional or role-scoped instead of globally required.
For custom_json.layout_quality_policy, identify expected layout/block roles and
whether recovered text from blocks misclassified as equations or disallowed block
types is acceptable recovery, degraded quality, or a true blocker. For Arabic
religious prose, stylized Arabic verse images may be misclassified as equations;
classify that as info only when the visible page evidence supports it.
For custom_json.vision_recovery_policy, enable it only when sampled page images show
important visible text that the extracted page text may miss or distort. Use it to
describe which block types should later be cropped and sent to a vision OCR model
when PDF text-layer recovery fails or a required script is missing.
If the document is commentary, translation, explanation, legal analysis, or another
secondary-source role, do not require a primary-source script unless the sampled
pages show that every answerable unit depends on that script.
For custom_json.mineru_parse_options, suggest upstream MinerU/RAG-Anything parse
overrides only when the samples justify them. Use parse_method="ocr" when the PDF
appears scanned or when Arabic glyphs need OCR, lang="arabic" for Arabic or mixed
Arabic religious texts, formula=false when standalone Arabic prose/verses could be
misclassified as formulas, and table=false when tables are not part of the evidence.
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

    def _apply_autosuggest_reference_defaults(
        self,
        metadata: DomainMetadata,
    ) -> dict[str, object]:
        custom_json = self._normalize_custom_json(
            metadata.custom_json if isinstance(metadata.custom_json, dict) else {},
            require_graph_policy=False,
        )
        if not self._looks_like_hadith_metadata(metadata, custom_json):
            return custom_json

        domain_structure = self._dict_value(custom_json.get("domain_structure"))
        primary_anchor = self._dict_value(domain_structure.get("primary_anchor"))
        primary_type = str(primary_anchor.get("type") or "").casefold()
        if primary_type in {"", "book_hadith", "hadith"} and not primary_anchor.get("regex"):
            primary_anchor = {
                **primary_anchor,
                "type": "book_hadith",
                "regex": (
                    r"\bBook\s+(?P<book>\d{1,4})\s*,?\s*Hadith\s+"
                    r"(?P<hadith>\d{1,6})\b"
                ),
                "unit": primary_anchor.get("unit") or "hadith",
            }
            domain_structure["primary_anchor"] = primary_anchor

        inline_references = self._dict_value(domain_structure.get("inline_references"))
        inline_type = str(inline_references.get("type") or "").casefold()
        inline_policy = inline_references.get("policy")
        if (
            inline_type in {"", "quran_verse", "chapter_verse", "cross_reference"}
            or inline_policy == "cross_reference_only"
        ) and not inline_references.get("regex"):
            inline_references = {
                **inline_references,
                "type": "chapter_verse",
                "regex": r"(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})",
                "policy": "cross_reference_only",
            }
            domain_structure["inline_references"] = inline_references

        if domain_structure:
            custom_json["domain_structure"] = domain_structure
        reference_resolution = self._dict_value(custom_json.get("reference_resolution"))
        reference_resolution = {
            "enabled": reference_resolution.get("enabled", True),
            "build_canonical_units": reference_resolution.get(
                "build_canonical_units",
                True,
            ),
            "carry_forward_body_blocks": reference_resolution.get(
                "carry_forward_body_blocks",
                True,
            ),
            "header_only_policy": reference_resolution.get(
                "header_only_policy",
                "provenance_only",
            ),
            "continuation_policy": reference_resolution.get(
                "continuation_policy",
                "until_next_reference",
            ),
            "max_page_gap": reference_resolution.get("max_page_gap", 2),
            "require_single_reference_per_answerable_chunk": reference_resolution.get(
                "require_single_reference_per_answerable_chunk",
                True,
            ),
        }
        custom_json["reference_resolution"] = reference_resolution

        provenance = self._dict_value(custom_json.get("provenance"))
        provenance = {
            "preserve_original_blocks": provenance.get("preserve_original_blocks", True),
            "block_preview_chars": provenance.get("block_preview_chars", 160),
            "store_text_hash": provenance.get("store_text_hash", True),
        }
        custom_json["provenance"] = provenance
        return custom_json

    def _looks_like_hadith_metadata(
        self,
        metadata: DomainMetadata,
        custom_json: dict[str, object],
    ) -> bool:
        reference_schema = custom_json.get("reference_schema")
        reference_type = (
            reference_schema.get("type")
            if isinstance(reference_schema, dict)
            else None
        )
        tokens = {
            str(item).casefold()
            for item in (
                metadata.domain,
                metadata.document_type,
                metadata.citation_style,
                metadata.reference_pattern,
                metadata.content_role,
                reference_type,
                *metadata.tags,
            )
            if item
        }
        return "hadith" in tokens or "book_hadith" in tokens or any(
            "hadith" in token for token in tokens
        )

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

        normalized_custom_json = self._normalize_custom_json(value.custom_json)
        generic_parser_normalization = {
            "allow_equations_as_content": False,
            "recover_text_bearing_blocks_as_prose": False,
            "preserve_original_block_type": True,
        }
        return (
            self._is_empty_metadata_value(value.language)
            and value.tags in ([], ["document"])
            and value.authority is None
            and value.source is None
            and value.collection is None
            and value.citation_style is None
            and value.expected_structure in (None, "sections")
            and normalized_custom_json
            in (
                {},
                {"chunking": {"unit": "section"}},
                {
                    "chunking": {"unit": "section"},
                    "parser_normalization": generic_parser_normalization,
                },
            )
            and value.reference_pattern is None
            and value.script is None
            and value.content_role is None
            and value.metadata_sources == []
        )

    def _merge_unique_strings(
        self, first: Sequence[object], second: Sequence[object]
    ) -> list[str]:
        merged: list[str] = []
        for item in [*first, *second]:
            if isinstance(item, str) and item and item not in merged:
                merged.append(item)
        return merged

    def _merge_lists(self, first: Sequence[object], second: Sequence[object]) -> list[object]:
        if all(isinstance(item, str) for item in [*first, *second]):
            return self._merge_unique_strings(first, second)

        merged: list[object] = []
        seen: set[str] = set()
        for item in [*first, *second]:
            key = json.dumps(item, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
        return merged

    def _dict_value(self, value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            return {}
        return {key: item for key, item in value.items() if isinstance(key, str)}

    def _merge_custom_json(
        self,
        baseline: dict[str, object],
        ai_value: dict[str, object],
    ) -> dict[str, object]:
        merged = self._normalize_custom_json(baseline)
        ai = self._normalize_custom_json(ai_value, require_graph_policy=False)
        for key in (
            "reference_schema",
            "relationships",
            "chunking",
            "domain_structure",
            "quality_policy",
            "layout_quality_policy",
            "reference_resolution",
            "provenance",
            "parser_normalization",
            "mineru_parse_options",
            "vision_recovery_policy",
            "retrieval",
            "graph",
        ):
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
                merged[key] = self._merge_lists(existing, value)
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
            merge_reference_header_with_body = chunking.get("merge_reference_header_with_body")
            if isinstance(unit, str):
                chunking_values["unit"] = unit
            if isinstance(include_neighbors, int) and not isinstance(include_neighbors, bool):
                chunking_values["include_neighbors"] = max(0, include_neighbors)
            if isinstance(preserve_parallel_text, bool):
                chunking_values["preserve_parallel_text"] = preserve_parallel_text
            if isinstance(merge_reference_header_with_body, bool):
                chunking_values["merge_reference_header_with_body"] = (
                    merge_reference_header_with_body
                )
            if chunking_values:
                normalized["chunking"] = chunking_values

        domain_structure_values = self._normalize_domain_structure(
            value.get("domain_structure")
        )
        if domain_structure_values:
            normalized["domain_structure"] = domain_structure_values

        quality_policy_values = self._normalize_quality_policy(value.get("quality_policy"))
        if quality_policy_values:
            normalized["quality_policy"] = quality_policy_values

        layout_quality_policy_values = self._normalize_layout_quality_policy(
            value.get("layout_quality_policy")
        )
        if layout_quality_policy_values:
            normalized["layout_quality_policy"] = layout_quality_policy_values

        reference_resolution = value.get("reference_resolution")
        if isinstance(reference_resolution, dict):
            reference_resolution_values: dict[str, object] = {}
            for key in (
                "enabled",
                "build_canonical_units",
                "carry_forward_body_blocks",
                "require_single_reference_per_answerable_chunk",
                "carry_forward_previous_reference",
                "continuation_reference_carry_forward",
                "mark_title_front_matter_non_reference_chunks",
            ):
                item = reference_resolution.get(key)
                if isinstance(item, bool):
                    reference_resolution_values[key] = item
            for key in ("header_only_policy", "continuation_policy"):
                item = reference_resolution.get(key)
                if isinstance(item, str):
                    reference_resolution_values[key] = item
            max_page_gap = reference_resolution.get("max_page_gap")
            if isinstance(max_page_gap, int) and not isinstance(max_page_gap, bool):
                reference_resolution_values["max_page_gap"] = max(0, max_page_gap)
            if reference_resolution_values:
                normalized["reference_resolution"] = reference_resolution_values

        provenance = value.get("provenance")
        if isinstance(provenance, dict):
            provenance_values: dict[str, object] = {}
            for key in ("preserve_original_blocks", "store_text_hash"):
                item = provenance.get(key)
                if isinstance(item, bool):
                    provenance_values[key] = item
            block_preview_chars = provenance.get("block_preview_chars")
            if isinstance(block_preview_chars, int) and not isinstance(block_preview_chars, bool):
                provenance_values["block_preview_chars"] = max(0, block_preview_chars)
            if provenance_values:
                normalized["provenance"] = provenance_values

        parser_normalization = value.get("parser_normalization")
        if isinstance(parser_normalization, dict):
            parser_values: dict[str, object] = {}
            for key in (
                "allow_equations_as_content",
                "recover_text_bearing_blocks_as_prose",
                "preserve_original_block_type",
            ):
                item = parser_normalization.get(key)
                if isinstance(item, bool):
                    parser_values[key] = item
            for key in ("parser_strictness", "strictness"):
                item = parser_normalization.get(key)
                if isinstance(item, str):
                    parser_values[key] = item
            for key in ("allowed_block_types", "expected_scripts", "reference_patterns"):
                items = parser_normalization.get(key)
                if isinstance(items, list):
                    strings = [item for item in items if isinstance(item, str) and item]
                    if strings:
                        parser_values[key] = strings
            if parser_values:
                normalized["parser_normalization"] = parser_values

        mineru_parse_options = value.get("mineru_parse_options")
        if isinstance(mineru_parse_options, dict):
            mineru_values: dict[str, object] = {}
            for key in ("parser", "parse_method", "backend", "device", "lang", "source"):
                item = mineru_parse_options.get(key)
                if isinstance(item, str) and item.strip():
                    mineru_values[key] = item.strip()
            for key in ("formula", "table"):
                item = mineru_parse_options.get(key)
                if isinstance(item, bool):
                    mineru_values[key] = item
            max_concurrent_files = mineru_parse_options.get("max_concurrent_files")
            if (
                isinstance(max_concurrent_files, int)
                and not isinstance(max_concurrent_files, bool)
            ):
                mineru_values["max_concurrent_files"] = max(
                    1,
                    min(max_concurrent_files, 8),
                )
            if mineru_values:
                normalized["mineru_parse_options"] = mineru_values

        vision_recovery_policy_values = self._normalize_vision_recovery_policy(
            value.get("vision_recovery_policy")
        )
        if vision_recovery_policy_values:
            normalized["vision_recovery_policy"] = vision_recovery_policy_values

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

    def _normalize_vision_recovery_policy(self, value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, object] = {}
        enabled = value.get("enabled")
        if isinstance(enabled, bool):
            normalized["enabled"] = enabled
        for key in ("target_block_types", "triggers", "languages"):
            items = value.get(key)
            if not isinstance(items, list):
                continue
            strings = []
            for item in items:
                if not isinstance(item, str) or not item.strip():
                    continue
                strings.append(
                    self._normalize_script_label(item)
                    if key == "languages"
                    else item.strip().casefold()
                )
            if strings:
                normalized[key] = list(dict.fromkeys(strings))
        max_blocks_per_page = value.get("max_blocks_per_page")
        if isinstance(max_blocks_per_page, int) and not isinstance(max_blocks_per_page, bool):
            normalized["max_blocks_per_page"] = max(1, min(max_blocks_per_page, 20))
        max_total_blocks = value.get("max_total_blocks")
        if isinstance(max_total_blocks, int) and not isinstance(max_total_blocks, bool):
            normalized["max_total_blocks"] = max(1, min(max_total_blocks, 500))
        failure_action = value.get("failure_action")
        if failure_action in {"info", "warn", "block"}:
            normalized["failure_action"] = failure_action
        prompt_hint = value.get("prompt_hint")
        if isinstance(prompt_hint, str) and prompt_hint.strip():
            normalized["prompt_hint"] = prompt_hint.strip()[:500]
        evidence = value.get("evidence")
        if isinstance(evidence, list):
            clean_evidence: list[dict[str, object]] = []
            for entry in evidence:
                if not isinstance(entry, dict):
                    continue
                page = entry.get("page")
                observation = entry.get("observation")
                if (
                    isinstance(page, int)
                    and not isinstance(page, bool)
                    and isinstance(observation, str)
                    and observation.strip()
                ):
                    clean_evidence.append(
                        {"page": page, "observation": observation.strip()[:300]}
                    )
            if clean_evidence:
                normalized["evidence"] = clean_evidence[:10]
        confidence = value.get("confidence")
        if isinstance(confidence, int | float) and not isinstance(confidence, bool):
            normalized["confidence"] = min(max(float(confidence), 0.0), 1.0)
        return normalized

    def _normalize_script_label(self, value: str) -> str:
        normalized = value.strip().casefold()
        if normalized in {"english", "eng", "latin_script", "roman"}:
            return "latin"
        if normalized in {"arab", "arabic_script"}:
            return "arabic"
        return normalized

    def _normalize_domain_structure(self, value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, object] = {}
        for key in ("primary_anchor", "inline_references"):
            section = value.get(key)
            if not isinstance(section, dict):
                continue
            section_values: dict[str, object] = {}
            for string_key in ("type", "unit", "pattern", "display"):
                item = section.get(string_key)
                if isinstance(item, str) and item.strip():
                    section_values[string_key] = item.strip()
            regex = section.get("regex")
            if isinstance(regex, str) and self._is_valid_domain_structure_regex(regex):
                section_values["regex"] = regex
            policy = section.get("policy")
            if key == "inline_references" and policy in {
                "cross_reference_only",
                "starts_unit",
                "ignore",
            }:
                section_values["policy"] = policy
            if section_values:
                normalized[key] = section_values
        return normalized

    def _normalize_quality_policy(self, value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, object] = {}
        document_role = value.get("document_role")
        if isinstance(document_role, str) and document_role.strip():
            normalized["document_role"] = document_role.strip()
        for key in ("observed_scripts", "required_scripts", "optional_scripts"):
            items = value.get(key)
            if not isinstance(items, list):
                continue
            scripts = [
                self._normalize_script_label(item)
                for item in items
                if isinstance(item, str) and item.strip()
            ]
            if scripts:
                normalized[key] = list(dict.fromkeys(scripts))
        for key in ("required_scripts_by_unit_role", "optional_scripts_by_unit_role"):
            role_map = value.get(key)
            if not isinstance(role_map, dict):
                continue
            clean_map: dict[str, list[str]] = {}
            for role, scripts in role_map.items():
                if not isinstance(role, str) or not isinstance(scripts, list):
                    continue
                clean_scripts = [
                    self._normalize_script_label(script)
                    for script in scripts
                    if isinstance(script, str) and script.strip()
                ]
                clean_map[role.strip()] = list(dict.fromkeys(clean_scripts))
            if clean_map:
                normalized[key] = clean_map
        for key in ("missing_required_script_action", "missing_optional_script_action"):
            action = value.get(key)
            if action in {"no_warning", "info", "warn", "block"}:
                normalized[key] = action
        materialization_policy = value.get("materialization_policy")
        if materialization_policy in {
            "allow",
            "allow_if_required_scripts_present",
            "warn_if_required_scripts_missing",
            "block_if_required_scripts_missing",
        }:
            normalized["materialization_policy"] = materialization_policy
        evidence = value.get("evidence")
        if isinstance(evidence, list):
            clean_evidence: list[dict[str, object]] = []
            for entry in evidence:
                if not isinstance(entry, dict):
                    continue
                page = entry.get("page")
                observation = entry.get("observation")
                if (
                    isinstance(page, int)
                    and not isinstance(page, bool)
                    and isinstance(observation, str)
                    and observation.strip()
                ):
                    clean_evidence.append(
                        {"page": page, "observation": observation.strip()[:300]}
                    )
            if clean_evidence:
                normalized["evidence"] = clean_evidence[:10]
        confidence = value.get("confidence")
        if isinstance(confidence, int | float) and not isinstance(confidence, bool):
            normalized["confidence"] = min(max(float(confidence), 0.0), 1.0)
        return normalized

    def _normalize_layout_quality_policy(self, value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, object] = {}
        expected_block_roles = value.get("expected_block_roles")
        if isinstance(expected_block_roles, dict):
            role_values: dict[str, list[str]] = {}
            for role, block_types in expected_block_roles.items():
                if not isinstance(role, str) or not isinstance(block_types, list):
                    continue
                clean_types = [
                    block_type.strip().casefold()
                    for block_type in block_types
                    if isinstance(block_type, str) and block_type.strip()
                ]
                if clean_types:
                    role_values[role.strip()] = list(dict.fromkeys(clean_types))
            if role_values:
                normalized["expected_block_roles"] = role_values

        for section_name in ("misclassified_block_policy", "disallowed_block_policy"):
            section = value.get(section_name)
            if not isinstance(section, dict):
                continue
            section_values: dict[str, dict[str, str]] = {}
            for policy_name, policy in section.items():
                if not isinstance(policy_name, str) or not isinstance(policy, dict):
                    continue
                policy_values: dict[str, str] = {}
                treat_as = policy.get("treat_as")
                if isinstance(treat_as, str) and treat_as.strip():
                    policy_values["treat_as"] = treat_as.strip()
                action = policy.get("action")
                if action in {"recover_as_text", "ignore", "block"}:
                    policy_values["action"] = action
                warning_level = policy.get("warning_level")
                if warning_level in {"info", "warn", "block"}:
                    policy_values["warning_level"] = warning_level
                if policy_values:
                    section_values[policy_name.strip()] = policy_values
            if section_values:
                normalized[section_name] = section_values

        failure_policy = value.get("failure_policy")
        if isinstance(failure_policy, dict):
            clean_failures = {
                key.strip(): action
                for key, action in failure_policy.items()
                if isinstance(key, str) and action in {"info", "warn", "block"}
            }
            if clean_failures:
                normalized["failure_policy"] = clean_failures
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

    def _is_valid_domain_structure_regex(self, value: str) -> bool:
        try:
            validate_custom_json({"domain_structure": {"primary_anchor": {"regex": value}}})
        except ValueError:
            return False
        return True
