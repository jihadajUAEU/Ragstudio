from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn, MinerUParseOptionsIn

CHAPTER_VERSE_PRIMARY_ANCHOR_PATTERN = (
    r"(\bVerse\s+|\[)(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})\]?"
)
CHAPTER_VERSE_INLINE_REFERENCE_PATTERN = (
    r"(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})"
)
BOOK_HADITH_PRIMARY_ANCHOR_PATTERN = (
    r"\bBook\s+(?P<book>\d{1,4})\s*,?\s*Hadith\s+(?P<hadith>\d{1,6})\b"
)
LEGAL_SECTION_PRIMARY_ANCHOR_PATTERN = (
    r"\b(Article|Section|Sec\.?)\s+(?P<section>\d{1,4})"
)

CHAPTER_VERSE_TYPES = {
    "chapter_verse",
    "surah_ayah",
    "surah_aya",
    "surah_verse",
    "quran_verse",
    "quran_ayah",
    "surah:verse",
    "surah:ayah",
    "chapter:verse",
}
BOOK_HADITH_TYPES = {"book_hadith", "hadith", "hadith_reference", "book:hadith"}
LEGAL_SECTION_TYPES = {"legal_section", "section", "article", "article_section"}
REFERENCE_UNITS = {"verse", "ayah", "aya", "hadith", "section", "article"}


class DomainMetadataContractError(ValueError):
    """Raised when metadata describes reference chunking but is not executable."""


def compile_index_options(options: IndexDocumentIn) -> IndexDocumentIn:
    domain_metadata = compile_domain_metadata(options.domain_metadata)
    mineru_parse_options = options.mineru_parse_options or _compile_mineru_parse_options(
        domain_metadata
    )
    return options.model_copy(
        update={
            "domain_metadata": domain_metadata,
            "mineru_parse_options": mineru_parse_options,
        },
        deep=True,
    )


def compile_domain_metadata(metadata: DomainMetadata) -> DomainMetadata:
    custom_json = deepcopy(metadata.custom_json) if isinstance(metadata.custom_json, dict) else {}
    reference_family = _reference_family(metadata, custom_json)
    if reference_family is None:
        return metadata.model_copy(update={"custom_json": custom_json}, deep=True)

    _compile_reference_schema(custom_json, reference_family)
    _compile_chunking(custom_json, reference_family)
    _compile_domain_structure(custom_json, reference_family)
    _compile_reference_resolution(custom_json, reference_family)
    _compile_provenance(custom_json)
    _compile_quality_policy(custom_json, reference_family)
    return metadata.model_copy(update={"custom_json": custom_json}, deep=True)


def validate_executable_reference_contract(metadata: DomainMetadata) -> None:
    custom_json = metadata.custom_json if isinstance(metadata.custom_json, dict) else {}
    reference_family = _reference_family(metadata, custom_json)
    if reference_family is None:
        return

    chunking = _dict_value(custom_json.get("chunking"))
    reference_resolution = _dict_value(custom_json.get("reference_resolution"))
    chunk_unit = _normalized_token(chunking.get("unit"))
    canonical_enabled = reference_resolution.get("enabled") is True and (
        reference_resolution.get("build_canonical_units") is True
    )
    if chunk_unit not in REFERENCE_UNITS and not canonical_enabled:
        return

    domain_structure = _dict_value(custom_json.get("domain_structure"))
    primary_anchor = _dict_value(domain_structure.get("primary_anchor"))
    regex = primary_anchor.get("regex")
    if not isinstance(regex, str) or not regex.strip():
        raise DomainMetadataContractError(
            "Reference-unit chunking requires custom_json.domain_structure."
            "primary_anchor.regex before indexing."
        )

    required_groups = _required_groups(reference_family)
    try:
        compiled = re.compile(regex)
    except re.error as exc:
        raise DomainMetadataContractError(
            "custom_json.domain_structure.primary_anchor.regex must compile before indexing: "
            f"{exc.msg}"
        ) from exc
    missing = sorted(required_groups - set(compiled.groupindex))
    if missing:
        raise DomainMetadataContractError(
            "custom_json.domain_structure.primary_anchor.regex is missing required named "
            f"groups: {', '.join(missing)}."
        )

    if canonical_enabled is not True:
        raise DomainMetadataContractError(
            "Reference-unit chunking requires custom_json.reference_resolution.enabled=true "
            "and build_canonical_units=true before indexing."
        )


def _compile_reference_schema(custom_json: dict[str, Any], family: str) -> None:
    schema = _dict_value(custom_json.get("reference_schema"))
    if family == "chapter_verse":
        schema.update(
            {
                "type": "chapter_verse",
                "display": schema.get("display") or "{chapter}:{verse}",
                "canonical_ref_template": schema.get("canonical_ref_template")
                or "{chapter}:{verse}",
            }
        )
        fields = _dict_value(schema.get("fields"))
        fields.update(
            {
                "chapter": fields.get("chapter") or "chapter",
                "verse": fields.get("verse") or "verse",
            }
        )
        schema["fields"] = fields
    elif family == "book_hadith":
        schema.update(
            {
                "type": "book_hadith",
                "display": schema.get("display") or "Book {book}, Hadith {hadith}",
                "canonical_ref_template": schema.get("canonical_ref_template")
                or "book:{book}:hadith:{hadith}",
            }
        )
        fields = _dict_value(schema.get("fields"))
        fields.update(
            {
                "book": fields.get("book") or "book",
                "hadith": fields.get("hadith") or "hadith",
            }
        )
        schema["fields"] = fields
    elif family == "legal_section":
        schema.update(
            {
                "type": "legal_section",
                "display": schema.get("display") or "Section {section}",
                "canonical_ref_template": schema.get("canonical_ref_template")
                or "section:{section}",
            }
        )
        fields = _dict_value(schema.get("fields"))
        fields.update({"section": fields.get("section") or "section"})
        schema["fields"] = fields
    custom_json["reference_schema"] = schema


def _compile_chunking(custom_json: dict[str, Any], family: str) -> None:
    chunking = _dict_value(custom_json.get("chunking"))
    if family == "chapter_verse":
        chunking["unit"] = _unit_or_default(chunking.get("unit"), "verse")
        chunking["include_neighbors"] = chunking.get("include_neighbors", 1)
        chunking["preserve_parallel_text"] = chunking.get("preserve_parallel_text", True)
        chunking["merge_reference_header_with_body"] = chunking.get(
            "merge_reference_header_with_body", True
        )
    elif family == "book_hadith":
        chunking["unit"] = _unit_or_default(chunking.get("unit"), "hadith")
        chunking["include_neighbors"] = chunking.get("include_neighbors", 1)
        chunking["preserve_parallel_text"] = chunking.get("preserve_parallel_text", True)
        chunking["merge_reference_header_with_body"] = chunking.get(
            "merge_reference_header_with_body", True
        )
    elif family == "legal_section":
        chunking["unit"] = _unit_or_default(chunking.get("unit"), "section")
        chunking["include_neighbors"] = chunking.get("include_neighbors", 0)
    custom_json["chunking"] = chunking


def _compile_domain_structure(custom_json: dict[str, Any], family: str) -> None:
    domain_structure = _dict_value(custom_json.get("domain_structure"))
    primary_anchor = _dict_value(domain_structure.get("primary_anchor"))
    inline_references = _dict_value(domain_structure.get("inline_references"))

    if family == "chapter_verse":
        primary_anchor.update(
            {
                "type": "chapter_verse",
                "regex": primary_anchor.get("regex") or CHAPTER_VERSE_PRIMARY_ANCHOR_PATTERN,
                "unit": primary_anchor.get("unit") or "verse",
            }
        )
        inline_references.update(
            {
                "type": "chapter_verse",
                "regex": inline_references.get("regex")
                or CHAPTER_VERSE_INLINE_REFERENCE_PATTERN,
                "policy": inline_references.get("policy") or "cross_reference_only",
            }
        )
    elif family == "book_hadith":
        primary_anchor.update(
            {
                "type": "book_hadith",
                "regex": primary_anchor.get("regex") or BOOK_HADITH_PRIMARY_ANCHOR_PATTERN,
                "unit": primary_anchor.get("unit") or "hadith",
            }
        )
        if not inline_references.get("regex"):
            inline_references.update(
                {
                    "type": "chapter_verse",
                    "regex": CHAPTER_VERSE_INLINE_REFERENCE_PATTERN,
                    "policy": inline_references.get("policy") or "cross_reference_only",
                }
            )
    elif family == "legal_section":
        primary_anchor.update(
            {
                "type": "legal_section",
                "regex": primary_anchor.get("regex") or LEGAL_SECTION_PRIMARY_ANCHOR_PATTERN,
                "unit": primary_anchor.get("unit") or "section",
            }
        )

    domain_structure["primary_anchor"] = primary_anchor
    if inline_references:
        domain_structure["inline_references"] = inline_references
    custom_json["domain_structure"] = domain_structure


def _compile_reference_resolution(custom_json: dict[str, Any], family: str) -> None:
    reference_resolution = _dict_value(custom_json.get("reference_resolution"))
    reference_resolution.update(
        {
            "enabled": reference_resolution.get("enabled", True),
            "build_canonical_units": reference_resolution.get("build_canonical_units", True),
            "carry_forward_body_blocks": reference_resolution.get(
                "carry_forward_body_blocks", True
            ),
            "header_only_policy": reference_resolution.get(
                "header_only_policy", "provenance_only"
            ),
            "continuation_policy": reference_resolution.get(
                "continuation_policy", "until_next_reference"
            ),
            "max_page_gap": reference_resolution.get(
                "max_page_gap", 1 if family == "chapter_verse" else 2
            ),
            "require_single_reference_per_answerable_chunk": reference_resolution.get(
                "require_single_reference_per_answerable_chunk", True
            ),
        }
    )
    custom_json["reference_resolution"] = reference_resolution


def _compile_provenance(custom_json: dict[str, Any]) -> None:
    provenance = _dict_value(custom_json.get("provenance"))
    provenance.update(
        {
            "preserve_original_blocks": provenance.get("preserve_original_blocks", True),
            "block_preview_chars": provenance.get("block_preview_chars", 160),
            "store_text_hash": provenance.get("store_text_hash", True),
        }
    )
    custom_json["provenance"] = provenance


def _compile_quality_policy(custom_json: dict[str, Any], family: str) -> None:
    policy = _dict_value(custom_json.get("quality_policy"))
    gate = _dict_value(policy.get("reference_contract_gate"))
    gate.update(
        {
            "enabled": gate.get("enabled", True),
            "action": gate.get("action", "block"),
            "required": gate.get("required")
            or [
                "reference_schema.type",
                "domain_structure.primary_anchor.regex",
                "reference_resolution.build_canonical_units",
            ],
            "reference_family": gate.get("reference_family") or family,
        }
    )
    policy["reference_contract_gate"] = gate
    custom_json["quality_policy"] = policy


def _compile_mineru_parse_options(metadata: DomainMetadata) -> MinerUParseOptionsIn | None:
    custom_json = metadata.custom_json if isinstance(metadata.custom_json, dict) else {}
    reference_family = _reference_family(metadata, custom_json)
    values = [
        metadata.domain,
        metadata.language,
        metadata.script,
        metadata.reference_pattern,
        *metadata.tags,
    ]
    normalized = {str(value).casefold() for value in values if value}
    if reference_family == "chapter_verse" and (
        "arabic" in normalized or "quran" in normalized or "surah:verse" in normalized
    ):
        return MinerUParseOptionsIn(
            parse_method="ocr",
            lang="arabic",
            formula=False,
            table=False,
        )
    return None


def _reference_family(metadata: DomainMetadata, custom_json: dict[str, Any]) -> str | None:
    schema = _dict_value(custom_json.get("reference_schema"))
    domain_structure = _dict_value(custom_json.get("domain_structure"))
    primary_anchor = _dict_value(domain_structure.get("primary_anchor"))
    tokens = {
        _normalized_token(value)
        for value in (
            metadata.domain,
            metadata.document_type,
            metadata.citation_style,
            metadata.reference_pattern,
            metadata.expected_structure,
            metadata.content_role,
            schema.get("type"),
            primary_anchor.get("type"),
            primary_anchor.get("unit"),
            *_safe_tags(metadata.tags),
        )
        if value is not None
    }
    tokens = {token for token in tokens if token}
    if tokens & CHAPTER_VERSE_TYPES or any(
        ("quran" in token or "surah" in token or "ayah" in token)
        and "hadith" not in token
        for token in tokens
    ):
        return "chapter_verse"
    if tokens & BOOK_HADITH_TYPES or any("hadith" in token for token in tokens):
        return "book_hadith"
    if tokens & LEGAL_SECTION_TYPES:
        return "legal_section"
    return None


def _required_groups(family: str) -> set[str]:
    if family == "chapter_verse":
        return {"chapter", "verse"}
    if family == "book_hadith":
        return {"book", "hadith"}
    if family == "legal_section":
        return {"section"}
    return set()


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _safe_tags(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _normalized_token(value: Any) -> str:
    return str(value).strip().casefold().replace("-", "_") if value is not None else ""


def _unit_or_default(value: Any, default: str) -> str:
    unit = _normalized_token(value)
    return unit or default
