from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ragstudio.schemas.parsing import DomainMetadata

REFERENCE_PATTERN = re.compile(
    r"(?P<prefix>\bQuran\s+)?(?P<bracket>\[)?"
    r"(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})"
    r"(?(bracket)\])",
    flags=re.IGNORECASE,
)
CHAPTER_ONLY_PATTERN = re.compile(
    r"\b(?:surah|sura|chapter)\s+(?P<chapter>\d{1,4})\b",
    flags=re.IGNORECASE,
)
LEGAL_SECTION_PATTERN = re.compile(
    r"(?:\bsection\b|\bsec\.?|§)\s*(?P<section>\d+(?:\.\d+)*)",
    flags=re.IGNORECASE,
)
PAGE_LINE_PATTERN = re.compile(
    r"\b(?:page|p\.?)\s*(?P<page>\d+)(?:\s*(?:[:,-]\s*)?(?:line|l\.?)\s*(?P<line>\d+))?",
    flags=re.IGNORECASE,
)
BOOK_HADITH_PATTERN = re.compile(
    r"\bBook\s+(?P<book>\d+)\s*,?\s*Hadith\s+(?P<hadith>\d+)\b",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class ReferenceSemantics:
    profile_name: str = "generic"
    reference_type: str | None = None
    chunk_unit: str = "section"
    include_neighbors: int = 0
    preserve_parallel_text: bool = False
    exact_reference_top1: bool = False
    boost_same_chapter: bool = False
    boost_neighbor_verses: bool = False
    relationships: dict[str, list[str]] = field(default_factory=dict)
    reference_pattern: str | None = None
    canonical_ref_template: str | None = None
    canonical_units_enabled: bool = False
    carry_forward_body_blocks: bool = False
    header_only_policy: str = "answerable"
    continuation_policy: str = "until_next_reference"
    max_page_gap: int | None = None
    require_single_reference_per_answerable_chunk: bool = False
    preserve_original_blocks: bool = False
    block_preview_chars: int = 160
    store_text_hash: bool = False

    @classmethod
    def from_metadata(cls, metadata: DomainMetadata) -> ReferenceSemantics:
        custom = metadata.custom_json if isinstance(metadata.custom_json, dict) else {}
        reference_schema = custom.get("reference_schema")
        chunking_value = custom.get("chunking")
        retrieval_value = custom.get("retrieval")
        reference_resolution_value = custom.get("reference_resolution")
        provenance_value = custom.get("provenance")
        chunking: dict[str, Any] = chunking_value if isinstance(chunking_value, dict) else {}
        retrieval: dict[str, Any] = retrieval_value if isinstance(retrieval_value, dict) else {}
        reference_resolution: dict[str, Any] = (
            reference_resolution_value
            if isinstance(reference_resolution_value, dict)
            else {}
        )
        provenance: dict[str, Any] = (
            provenance_value if isinstance(provenance_value, dict) else {}
        )
        schema_pattern = cls._schema_pattern(reference_schema)
        canonical_ref_template = cls._canonical_ref_template(reference_schema)

        has_reference_schema = isinstance(reference_schema, dict)
        structured_reference = has_reference_schema or cls._has_structured_reference_fields(
            metadata
        )
        profile_name = "scripture_reference" if structured_reference else "generic"
        reference_type = cls._reference_type(metadata, reference_schema)

        chunk_unit = cls._string_value(chunking.get("unit"), default="section")
        if chunk_unit == "section" and structured_reference:
            chunk_unit = "verse"

        return cls(
            profile_name=profile_name,
            reference_type=reference_type,
            chunk_unit=chunk_unit,
            include_neighbors=cls._safe_nonnegative_int(
                chunking.get("include_neighbors"),
                default=0,
            ),
            preserve_parallel_text=cls._bool_value(
                chunking.get("preserve_parallel_text"),
                default=(
                    isinstance(metadata.expected_structure, str)
                    and metadata.expected_structure.casefold() == "parallel_text"
                ),
            ),
            exact_reference_top1=cls._bool_value(
                retrieval.get("exact_reference_top1"),
                default=structured_reference,
            ),
            boost_same_chapter=cls._bool_value(
                retrieval.get("boost_same_chapter"),
                default=structured_reference,
            ),
            boost_neighbor_verses=cls._bool_value(
                retrieval.get(
                    "boost_neighbor_verses",
                    retrieval.get("boost_neighbor_references"),
                ),
                default=structured_reference,
            ),
            relationships=cls._relationships(custom.get("relationships")),
            reference_pattern=schema_pattern,
            canonical_ref_template=canonical_ref_template,
            canonical_units_enabled=bool(
                structured_reference
                and cls._bool_value(reference_resolution.get("enabled"), default=False)
                and cls._bool_value(
                    reference_resolution.get("build_canonical_units"),
                    default=False,
                )
            ),
            carry_forward_body_blocks=cls._bool_value(
                reference_resolution.get(
                    "carry_forward_body_blocks",
                    reference_resolution.get("continuation_reference_carry_forward"),
                ),
                default=False,
            ),
            header_only_policy=cls._string_value(
                reference_resolution.get("header_only_policy"),
                default="answerable",
            ),
            continuation_policy=cls._string_value(
                reference_resolution.get("continuation_policy"),
                default="until_next_reference",
            ),
            max_page_gap=cls._optional_nonnegative_int(
                reference_resolution.get("max_page_gap")
            ),
            require_single_reference_per_answerable_chunk=cls._bool_value(
                reference_resolution.get("require_single_reference_per_answerable_chunk"),
                default=False,
            ),
            preserve_original_blocks=cls._bool_value(
                provenance.get("preserve_original_blocks"),
                default=False,
            ),
            block_preview_chars=cls._safe_nonnegative_int(
                provenance.get("block_preview_chars"),
                default=160,
            )
            or 160,
            store_text_hash=cls._bool_value(
                provenance.get("store_text_hash"),
                default=False,
            ),
        )

    def extract_query_reference(self, query: str) -> dict[str, int | str] | None:
        for pattern in self._compiled_patterns(include_chapter_only=True):
            match = pattern.search(query)
            if match is not None:
                return self._match_to_reference(match)
        return None

    def extract_chunk_references(self, text: str) -> list[dict[str, int | str]]:
        references: list[dict[str, int | str]] = []
        seen: set[str] = set()
        for match in self._iter_matches(text):
            ref = self._match_to_reference(match)
            key = str(ref["ref"])
            if key in seen:
                continue
            seen.add(key)
            references.append(ref)
        return references

    def split_reference_units(self, text: str) -> list[str]:
        matches = list(self._iter_matches(text))
        if not matches:
            return []

        units: list[str] = []
        leading = text[: matches[0].start()].strip()
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            unit = text[start:end].strip()
            if index == 0 and leading:
                unit = f"{leading}\n\n{unit}".strip()
            if unit:
                units.append(unit)
        return units

    def derive_reference_metadata(
        self,
        text: str,
        source_location: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        references = self.extract_chunk_references(text)
        if not references:
            return {}

        metadata: dict[str, Any] = {
            "reference_type": self.reference_type,
            "references": [str(ref["ref"]) for ref in references],
        }
        chapter_verse_refs = [
            ref
            for ref in references
            if isinstance(ref.get("chapter"), int) and isinstance(ref.get("verse"), int)
        ]
        if chapter_verse_refs:
            chapter_values = [int(ref["chapter"]) for ref in chapter_verse_refs]
            verse_values = [int(ref["verse"]) for ref in chapter_verse_refs]
            chapter_start = min(chapter_values)
            chapter_end = max(chapter_values)
            same_chapter = chapter_start == chapter_end
            verse_start = min(verse_values) if same_chapter else int(chapter_verse_refs[0]["verse"])
            verse_end = max(verse_values) if same_chapter else int(chapter_verse_refs[-1]["verse"])
            metadata.update(
                {
                    "chapter_start": chapter_start,
                    "chapter_end": chapter_end,
                    "verse_start": verse_start,
                    "verse_end": verse_end,
                }
            )
            if self.include_neighbors > 0 and same_chapter:
                previous_verse = verse_start - self.include_neighbors
                if previous_verse > 0:
                    metadata["previous_ref"] = f"{chapter_start}:{previous_verse}"
                metadata["next_ref"] = f"{chapter_end}:{verse_end + self.include_neighbors}"

        book_hadith_refs = [
            ref
            for ref in references
            if isinstance(ref.get("book"), int) and isinstance(ref.get("hadith"), int)
        ]
        if book_hadith_refs:
            book_values = [int(ref["book"]) for ref in book_hadith_refs]
            hadith_values = [int(ref["hadith"]) for ref in book_hadith_refs]
            book_start = min(book_values)
            book_end = max(book_values)
            same_book = book_start == book_end
            hadith_start = (
                min(hadith_values) if same_book else int(book_hadith_refs[0]["hadith"])
            )
            hadith_end = max(hadith_values) if same_book else int(book_hadith_refs[-1]["hadith"])
            metadata.update(
                {
                    "book_start": book_start,
                    "book_end": book_end,
                    "hadith_start": hadith_start,
                    "hadith_end": hadith_end,
                }
            )
            if self.include_neighbors > 0 and same_book:
                previous_hadith = hadith_start - self.include_neighbors
                if previous_hadith > 0:
                    metadata["previous_ref"] = f"book:{book_start}:hadith:{previous_hadith}"
                metadata["next_ref"] = (
                    f"book:{book_end}:hadith:{hadith_end + self.include_neighbors}"
                )

        for reference_field in ("section", "page", "line"):
            values = [ref[reference_field] for ref in references if reference_field in ref]
            if values:
                metadata[f"{reference_field}s"] = values
        metadata.update(self._page_range(source_location))

        return metadata

    def chunk_reference_metadata(
        self,
        text: str,
        source_location: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.derive_reference_metadata(text, source_location)

    def _iter_matches(self, text: str) -> list[re.Match[str]]:
        matches: list[re.Match[str]] = []
        for pattern in self._compiled_patterns():
            matches.extend(pattern.finditer(text))
        return sorted(matches, key=lambda match: match.start())

    def _compiled_patterns(
        self,
        *,
        include_chapter_only: bool = False,
    ) -> list[re.Pattern[str]]:
        patterns: list[re.Pattern[str]] = []
        if self.reference_pattern:
            try:
                patterns.append(re.compile(self.reference_pattern, flags=re.IGNORECASE))
            except re.error:
                pass
        reference_type = (self.reference_type or "").casefold()
        if (
            reference_type in {"surah_ayah", "chapter_verse"}
            or self.profile_name == "scripture_reference"
        ):
            patterns.append(REFERENCE_PATTERN)
            if include_chapter_only:
                patterns.append(CHAPTER_ONLY_PATTERN)
        if reference_type in {"legal_section", "section", "article_section"}:
            patterns.append(LEGAL_SECTION_PATTERN)
        if reference_type in {"page_line", "page"}:
            patterns.append(PAGE_LINE_PATTERN)
        if reference_type in {"book_hadith", "hadith"}:
            patterns.append(BOOK_HADITH_PATTERN)
        return patterns

    def _match_to_reference(self, match: re.Match[str]) -> dict[str, int | str]:
        groups = match.groupdict()
        ref: dict[str, int | str] = {"raw": match.group(0)}
        for key, value in groups.items():
            if value is None:
                continue
            if key in {"prefix", "bracket"}:
                continue
            ref[key] = int(value) if value.isdigit() else value

        templated_ref = self._render_canonical_ref(ref)
        if templated_ref:
            ref["ref"] = templated_ref
        elif isinstance(ref.get("chapter"), int) and isinstance(ref.get("verse"), int):
            ref["ref"] = f"{ref['chapter']}:{ref['verse']}"
        elif isinstance(ref.get("book"), int) and isinstance(ref.get("hadith"), int):
            ref["ref"] = f"book:{ref['book']}:hadith:{ref['hadith']}"
        elif "section" in ref:
            ref["ref"] = f"section:{ref['section']}"
        elif "page" in ref and "line" in ref:
            ref["ref"] = f"page:{ref['page']}:line:{ref['line']}"
        elif "page" in ref:
            ref["ref"] = f"page:{ref['page']}"
        else:
            ref["ref"] = match.group(0).strip()
        return ref

    def _render_canonical_ref(self, ref: dict[str, int | str]) -> str | None:
        template = self.canonical_ref_template
        if not template:
            return None
        try:
            rendered = template.format(**ref).strip()
        except (KeyError, IndexError, ValueError):
            return None
        return rendered or None

    @classmethod
    def _has_structured_reference_fields(cls, metadata: DomainMetadata) -> bool:
        values = cls._metadata_tokens(metadata)
        has_reference_pattern = any(
            cls._token_mentions(value, "chapter", "surah", "sura")
            and cls._token_mentions(value, "verse", "ayah", "aya")
            for value in values
        )
        has_parallel_structure = "parallel_text" in values
        has_strong_scripture_tag = bool({"quran", "bible", "scripture"} & values)
        has_scripture_text_type = "religious_text" in values
        has_legal_reference = any(
            cls._token_mentions(value, "statute", "section", "article")
            for value in values
        )
        has_page_line_reference = any(
            cls._token_mentions(value, "page_line", "page-line", "page:line")
            or (
                cls._token_mentions(value, "page")
                and cls._token_mentions(value, "line")
            )
            for value in values
        )
        has_hadith_reference = any(
            cls._token_mentions(value, "hadith")
            and cls._token_mentions(value, "book", "collection")
            for value in values
        )
        return (
            has_reference_pattern
            or has_strong_scripture_tag
            or (has_parallel_structure and has_scripture_text_type)
            or has_legal_reference
            or has_page_line_reference
            or has_hadith_reference
        )

    @classmethod
    def _reference_type(cls, metadata: DomainMetadata, reference_schema: Any) -> str | None:
        if isinstance(reference_schema, dict):
            schema_type = cls._string_value(reference_schema.get("type"), default="")
            if schema_type:
                return schema_type
            fields = reference_schema.get("fields")
            if isinstance(fields, dict) and cls._field_map_has_chapter_and_verse(fields):
                return "chapter_verse"

        values = cls._metadata_tokens(metadata)
        if "surah_number:verse_number" in values or "quran" in values:
            return "surah_ayah"
        if any(
            cls._token_mentions(value, "surah", "sura")
            and cls._token_mentions(value, "verse", "ayah", "aya")
            for value in values
        ):
            return "surah_ayah"
        if any(
            cls._token_mentions(value, "chapter")
            and cls._token_mentions(value, "verse", "ayah", "aya")
            for value in values
        ):
            return "chapter_verse"
        if any(cls._token_mentions(value, "statute", "section", "article") for value in values):
            return "legal_section"
        if any(
            cls._token_mentions(value, "page_line", "page-line", "page:line")
            or (
                cls._token_mentions(value, "page")
                and cls._token_mentions(value, "line")
            )
            for value in values
        ):
            return "page_line"
        if "hadith" in values or any(
            cls._token_mentions(value, "book") and cls._token_mentions(value, "hadith")
            for value in values
        ):
            return "book_hadith"
        return None

    @staticmethod
    def _schema_pattern(reference_schema: Any) -> str | None:
        if not isinstance(reference_schema, dict):
            return None
        for key in ("reference_regex", "pattern", "regex"):
            value = reference_schema.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _canonical_ref_template(reference_schema: Any) -> str | None:
        if not isinstance(reference_schema, dict):
            return None
        value = reference_schema.get("canonical_ref_template")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @staticmethod
    def _field_map_has_chapter_and_verse(fields: dict[Any, Any]) -> bool:
        tokens = {
            str(item).casefold()
            for pair in fields.items()
            for item in pair
            if item is not None
        }
        has_chapter = bool({"chapter", "surah", "sura"} & tokens)
        has_verse = bool({"verse", "ayah", "aya"} & tokens)
        return has_chapter and has_verse

    @staticmethod
    def _relationships(value: Any) -> dict[str, list[str]]:
        if not isinstance(value, dict):
            return {}
        return {
            key: [str(item) for item in items]
            for key, items in value.items()
            if isinstance(key, str) and isinstance(items, list)
        }

    @staticmethod
    def _metadata_tokens(metadata: DomainMetadata) -> set[str]:
        raw_values = [
            metadata.domain,
            metadata.document_type,
            metadata.expected_structure,
            metadata.reference_pattern,
            metadata.script,
            metadata.content_role,
            *metadata.tags,
        ]
        return {value.casefold() for value in raw_values if isinstance(value, str)}

    @staticmethod
    def _token_mentions(value: str, *words: str) -> bool:
        return any(word in value for word in words)

    @staticmethod
    def _page_range(source_location: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(source_location, dict):
            return {}
        page_start = source_location.get("page_start", source_location.get("page"))
        page_end = source_location.get("page_end", source_location.get("page"))
        pages: dict[str, Any] = {}
        if page_start is not None:
            pages["page_start"] = page_start
        if page_end is not None:
            pages["page_end"] = page_end
        return pages

    @staticmethod
    def _safe_nonnegative_int(value: Any, *, default: int) -> int:
        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            return max(value, 0)
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return default

    @staticmethod
    def _optional_nonnegative_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return max(value, 0)
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    @staticmethod
    def _bool_value(value: Any, *, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        return default

    @staticmethod
    def _string_value(value: Any, *, default: str) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return default
