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

    @classmethod
    def from_metadata(cls, metadata: DomainMetadata) -> "ReferenceSemantics":
        custom = metadata.custom_json if isinstance(metadata.custom_json, dict) else {}
        reference_schema = custom.get("reference_schema")
        chunking = custom.get("chunking") if isinstance(custom.get("chunking"), dict) else {}
        retrieval = custom.get("retrieval") if isinstance(custom.get("retrieval"), dict) else {}

        has_reference_schema = isinstance(reference_schema, dict)
        structured_reference = has_reference_schema or cls._has_structured_reference_fields(metadata)
        profile_name = "scripture_reference" if structured_reference else "generic"
        reference_type = cls._reference_type(metadata, reference_schema)

        chunk_unit = cls._string_value(chunking.get("unit"), default="section")
        if chunk_unit == "section" and structured_reference:
            chunk_unit = "verse"

        return cls(
            profile_name=profile_name,
            reference_type=reference_type,
            chunk_unit=chunk_unit,
            include_neighbors=cls._safe_nonnegative_int(chunking.get("include_neighbors"), default=0),
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
        )

    def extract_query_reference(self, query: str) -> dict[str, int | str] | None:
        match = REFERENCE_PATTERN.search(query)
        if match is None:
            return None
        return self._match_to_reference(match)

    def extract_chunk_references(self, text: str) -> list[dict[str, int | str]]:
        references: list[dict[str, int | str]] = []
        seen: set[tuple[int, int]] = set()
        for match in REFERENCE_PATTERN.finditer(text):
            ref = self._match_to_reference(match)
            key = (int(ref["chapter"]), int(ref["verse"]))
            if key in seen:
                continue
            seen.add(key)
            references.append(ref)
        return references

    def derive_reference_metadata(
        self,
        text: str,
        source_location: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        references = self.extract_chunk_references(text)
        if not references:
            return {}

        chapter_values = [int(ref["chapter"]) for ref in references]
        verse_values = [int(ref["verse"]) for ref in references]
        chapter_start = min(chapter_values)
        chapter_end = max(chapter_values)
        same_chapter = chapter_start == chapter_end
        verse_start = min(verse_values) if same_chapter else int(references[0]["verse"])
        verse_end = max(verse_values) if same_chapter else int(references[-1]["verse"])

        metadata: dict[str, Any] = {
            "reference_type": self.reference_type,
            "references": [f"{ref['chapter']}:{ref['verse']}" for ref in references],
            "chapter_start": chapter_start,
            "chapter_end": chapter_end,
            "verse_start": verse_start,
            "verse_end": verse_end,
        }
        metadata.update(self._page_range(source_location))

        if self.include_neighbors > 0 and same_chapter:
            previous_verse = verse_start - self.include_neighbors
            if previous_verse > 0:
                metadata["previous_ref"] = f"{chapter_start}:{previous_verse}"
            metadata["next_ref"] = f"{chapter_end}:{verse_end + self.include_neighbors}"

        return metadata

    def chunk_reference_metadata(
        self,
        text: str,
        source_location: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.derive_reference_metadata(text, source_location)

    @staticmethod
    def _match_to_reference(match: re.Match[str]) -> dict[str, int | str]:
        return {
            "chapter": int(match.group("chapter")),
            "verse": int(match.group("verse")),
            "raw": match.group(0),
        }

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
        return (
            has_reference_pattern
            or has_strong_scripture_tag
            or (has_parallel_structure and has_scripture_text_type)
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
    def _bool_value(value: Any, *, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        return default

    @staticmethod
    def _string_value(value: Any, *, default: str) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return default
