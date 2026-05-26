"""Generic reference metadata adapter for model-declared document contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from string import Formatter
from typing import Any

from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.reference_contracts import (
    ReferenceAnchor,
    build_executable_reference_contract,
    canonical_reference_from_groups,
)


def _numeric_identity_ranges(
    references: list[dict[str, int | str]],
) -> dict[str, dict[str, int]]:
    ranges: dict[str, dict[str, int]] = {}
    for reference in references:
        for key, value in reference.items():
            if key == "ref" or not isinstance(value, int) or isinstance(value, bool):
                continue
            current = ranges.setdefault(key, {"start": value, "end": value})
            current["start"] = min(current["start"], value)
            current["end"] = max(current["end"], value)
    return ranges


def _neighbor_reference_from_identity(
    reference: dict[str, int | str],
    *,
    unit_field: str,
    delta: int,
    template: str | None,
) -> str | None:
    value = reference.get(unit_field)
    if not isinstance(value, int):
        return None
    next_value = value + delta
    if next_value <= 0:
        return None
    groups = dict(reference)
    groups[unit_field] = next_value
    return canonical_reference_from_groups(
        {key: str(item) for key, item in groups.items() if key != "ref"},
        template,
    )


def _ordered_identity_fields(
    template: str | None,
    required_groups: frozenset[str],
) -> tuple[str, ...]:
    if template:
        fields: list[str] = []
        for _, field_name, _, _ in Formatter().parse(template):
            if not field_name:
                continue
            field = field_name.split(".", 1)[0].split("[", 1)[0]
            if field and field not in fields:
                fields.append(field)
        if fields:
            return tuple(fields)
    return tuple(sorted(required_groups))


@dataclass(frozen=True)
class ReferenceSemantics:
    profile_name: str = "generic"
    reference_capability: str = "none"
    reference_type: str | None = None
    chunk_unit: str = "section"
    include_neighbors: int = 0
    preserve_parallel_text: bool = False
    exact_reference_top1: bool = False
    boost_same_parent_reference: bool = False
    boost_neighbor_references: bool = False
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
    primary_anchor_pattern: str | None = None
    primary_anchor_unit: str | None = None
    context_anchor_pattern: str | None = None
    unit_anchor_pattern: str | None = None
    inline_reference_pattern: str | None = None
    inline_reference_policy: str = "starts_unit"

    required_reference_groups: frozenset[str] = field(default_factory=frozenset)
    reference_identity_fields: tuple[str, ...] = ()

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
        domain_structure_value = custom.get("domain_structure")
        domain_structure: dict[str, Any] = (
            domain_structure_value if isinstance(domain_structure_value, dict) else {}
        )
        primary_anchor = domain_structure.get("primary_anchor")
        primary_anchor = primary_anchor if isinstance(primary_anchor, dict) else {}
        context_anchor = domain_structure.get("context_anchor")
        context_anchor = context_anchor if isinstance(context_anchor, dict) else {}
        unit_anchor = domain_structure.get("unit_anchor")
        unit_anchor = unit_anchor if isinstance(unit_anchor, dict) else {}
        inline_references = domain_structure.get("inline_references")
        inline_references = inline_references if isinstance(inline_references, dict) else {}
        contract = build_executable_reference_contract(custom)
        schema_pattern = cls._schema_pattern(reference_schema)
        canonical_ref_template = contract.canonical_ref_template or cls._canonical_ref_template(
            reference_schema
        )

        has_reference_schema = isinstance(reference_schema, dict)
        has_structured_hint = has_reference_schema or bool(contract.anchors)
        reference_capability = "none"
        if has_structured_hint:
            reference_capability = "hint"
        if (
            contract.verified
            and cls._contract_state_verified(custom)
            and cls._bool_value(reference_resolution.get("enabled"), default=False)
            and cls._bool_value(
                reference_resolution.get("build_canonical_units"),
                default=False,
            )
        ):
            reference_capability = "verified"
        profile_name = (
            "verified_reference"
            if reference_capability == "verified"
            else "reference_hint"
            if reference_capability == "hint"
            else "generic"
        )
        reference_type = contract.schema_type

        verified_reference = reference_capability == "verified"
        primary_contract_anchor = (
            cls._verified_anchor_for_groups(
                contract.anchors,
                "primary_anchor",
                contract.required_groups,
            )
            if verified_reference
            else None
        )
        context_contract_anchor = (
            cls._verified_context_anchor_for_groups(
                contract.anchors,
                contract.required_groups,
            )
            if verified_reference
            else None
        )
        unit_contract_anchor = (
            cls._verified_unit_anchor_for_groups(
                contract.anchors,
                contract.required_groups,
            )
            if verified_reference
            else None
        )
        inline_contract_anchor = (
            cls._anchor_by_kind(contract.anchors, "inline_references")
            if verified_reference
            else None
        )
        primary_anchor_unit = (
            primary_contract_anchor.unit_role
            if primary_contract_anchor is not None
            else cls._string_value(primary_anchor.get("unit"), default=None)
        )
        unit_anchor_unit = unit_contract_anchor.unit_role if unit_contract_anchor else None
        first_anchor_unit = next(
            (anchor.unit_role for anchor in contract.anchors if anchor.unit_role),
            None,
        )
        chunk_unit = cls._string_value(
            chunking.get("unit"),
            default=unit_anchor_unit or primary_anchor_unit or first_anchor_unit or "section",
        ) or "section"
        verified_primary_anchor_pattern = (
            primary_contract_anchor.regex if primary_contract_anchor is not None else None
        )
        contextual_anchor_verified = (
            context_contract_anchor is not None and unit_contract_anchor is not None
        )
        inline_reference_policy = cls._string_value(
            inline_references.get("policy")
            or (inline_contract_anchor.policy if inline_contract_anchor else None),
            default="cross_reference_only"
            if verified_primary_anchor_pattern or contextual_anchor_verified
            else "starts_unit",
        )
        inline_reference_pattern = cls._string_value(
            inline_contract_anchor.regex
            if inline_contract_anchor is not None and inline_contract_anchor.verified
            else None,
            default=None,
        )
        context_anchor_pattern = (
            context_contract_anchor.regex if context_contract_anchor is not None else None
        )
        unit_anchor_pattern = (
            unit_contract_anchor.regex if unit_contract_anchor is not None else None
        )
        has_verified_anchor = (
            verified_primary_anchor_pattern is not None
            or (
                contextual_anchor_verified
                and context_anchor_pattern is not None
                and unit_anchor_pattern is not None
            )
        )
        reference_identity_fields = _ordered_identity_fields(
            canonical_ref_template,
            contract.required_groups,
        )

        return cls(
            profile_name=profile_name,
            reference_capability=reference_capability,
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
                default=verified_reference,
            ),
            boost_same_parent_reference=cls._bool_value(
                retrieval.get("boost_same_parent_reference"),
                default=verified_reference,
            ),
            boost_neighbor_references=cls._bool_value(
                retrieval.get("boost_neighbor_references"),
                default=verified_reference,
            ),
            relationships=cls._relationships(custom.get("relationships")),
            reference_pattern=schema_pattern,
            canonical_ref_template=canonical_ref_template,
            canonical_units_enabled=bool(
                verified_reference
                and has_verified_anchor
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
            )
            or "answerable",
            continuation_policy=cls._string_value(
                reference_resolution.get("continuation_policy"),
                default="until_next_reference",
            )
            or "until_next_reference",
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
            primary_anchor_pattern=verified_primary_anchor_pattern,
            primary_anchor_unit=primary_anchor_unit,
            context_anchor_pattern=context_anchor_pattern if contextual_anchor_verified else None,
            unit_anchor_pattern=unit_anchor_pattern if contextual_anchor_verified else None,
            inline_reference_pattern=inline_reference_pattern,
            inline_reference_policy=inline_reference_policy or "starts_unit",
            required_reference_groups=contract.required_groups,
            reference_identity_fields=reference_identity_fields,
        )

    @property
    def has_primary_unit_anchor(self) -> bool:
        return bool(
            self.primary_anchor_pattern
            or (self.context_anchor_pattern and self.unit_anchor_pattern)
        )

    @property
    def has_contextual_unit_anchor(self) -> bool:
        return bool(self.context_anchor_pattern and self.unit_anchor_pattern)

    def extract_query_reference(self, query: str) -> dict[str, int | str] | None:
        for pattern in self._compiled_patterns():
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

    def extract_primary_anchor_references(self, text: str) -> list[dict[str, int | str]]:
        contextual_references = self._extract_contextual_unit_references(text)
        if contextual_references:
            return contextual_references
        pattern = self._primary_anchor_regex()
        if pattern is None:
            if self.has_contextual_unit_anchor:
                return []
            return self.extract_chunk_references(text)
        stripped = text.strip()
        if not stripped:
            return []
        references: list[dict[str, int | str]] = []
        seen: set[str] = set()
        for match in pattern.finditer(stripped):
            reference = self._match_to_reference(match)
            key = str(reference["ref"])
            if key in seen:
                continue
            seen.add(key)
            references.append(reference)
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

    def split_primary_anchor_units(self, text: str) -> list[str]:
        contextual_units = self._split_contextual_unit_units(text)
        if contextual_units:
            return contextual_units
        pattern = self._primary_anchor_regex()
        if pattern is None:
            if self.has_contextual_unit_anchor:
                return []
            return self.split_reference_units(text)
        matches = list(pattern.finditer(text))
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
        contextual_references = self._extract_contextual_unit_references(text)
        if contextual_references:
            return self._reference_metadata_from_references(
                contextual_references,
                source_location,
            )
        if self.has_contextual_unit_anchor and not self.primary_anchor_pattern:
            return {}
        all_references = self.extract_chunk_references(text)
        if (
            self.inline_reference_policy == "cross_reference_only"
            and self.has_primary_unit_anchor
        ):
            primary_references = self.extract_primary_anchor_references(text)
            if not primary_references:
                return {}
            primary_labels = {
                str(reference["ref"])
                for reference in primary_references
                if reference.get("ref") is not None
            }
            cross_references = [
                reference
                for reference in all_references
                if str(reference.get("ref")) not in primary_labels
            ]
            return self._reference_metadata_from_references(
                primary_references,
                source_location,
                cross_references=cross_references,
            )

        return self._reference_metadata_from_references(
            all_references,
            source_location,
        )

    def _reference_metadata_from_references(
        self,
        references: list[dict[str, int | str]],
        source_location: dict[str, Any] | None = None,
        *,
        cross_references: list[dict[str, int | str]] | None = None,
    ) -> dict[str, Any]:
        if not references:
            return {}

        metadata: dict[str, Any] = {
            "reference_type": self.reference_type,
            "references": [str(ref["ref"]) for ref in references],
        }
        identity_ranges = _numeric_identity_ranges(references)
        if identity_ranges:
            metadata["identity_ranges"] = identity_ranges
            metadata["reference_identity_range"] = identity_ranges
            if self.reference_identity_fields:
                metadata["reference_identity_fields"] = list(self.reference_identity_fields)
                metadata["reference_unit_field"] = self.reference_identity_fields[-1]
        cross_reference_labels = self._reference_labels(cross_references or [])
        if cross_reference_labels:
            metadata["cross_references"] = cross_reference_labels
        unit_field = self.reference_identity_fields[-1] if self.reference_identity_fields else None
        if self.include_neighbors > 0 and unit_field and len(references) == 1:
            previous_ref = _neighbor_reference_from_identity(
                references[0],
                unit_field=unit_field,
                delta=-self.include_neighbors,
                template=self.canonical_ref_template,
            )
            next_ref = _neighbor_reference_from_identity(
                references[0],
                unit_field=unit_field,
                delta=self.include_neighbors,
                template=self.canonical_ref_template,
            )
            if previous_ref:
                metadata["previous_ref"] = previous_ref
            if next_ref:
                metadata["next_ref"] = next_ref
        for reference_field in ("section", "page", "line"):
            values = [ref[reference_field] for ref in references if reference_field in ref]
            if values:
                metadata[f"{reference_field}s"] = values
        metadata.update(self._page_range(source_location))

        return metadata

    def _reference_labels(self, references: list[dict[str, int | str]]) -> list[str]:
        labels: list[str] = []
        seen: set[str] = set()
        for reference in references:
            label = reference.get("ref")
            if label is None:
                continue
            item = str(label)
            if item in seen:
                continue
            seen.add(item)
            labels.append(item)
        return labels

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

    def _compiled_patterns(self) -> list[re.Pattern[str]]:
        patterns: list[re.Pattern[str]] = []
        seen: set[str] = set()
        for pattern_text in (
            self.primary_anchor_pattern,
            self.inline_reference_pattern,
        ):
            if not pattern_text or pattern_text in seen:
                continue
            seen.add(pattern_text)
            try:
                patterns.append(re.compile(pattern_text, flags=re.IGNORECASE))
            except re.error:
                pass
        return patterns

    def _primary_anchor_regex(self) -> re.Pattern[str] | None:
        if not self.primary_anchor_pattern:
            return None
        try:
            return re.compile(self.primary_anchor_pattern, flags=re.IGNORECASE)
        except re.error:
            return None

    def _context_anchor_regex(self) -> re.Pattern[str] | None:
        if not self.context_anchor_pattern:
            return None
        try:
            return re.compile(self.context_anchor_pattern, flags=re.IGNORECASE)
        except re.error:
            return None

    def _unit_anchor_regex(self) -> re.Pattern[str] | None:
        if not self.unit_anchor_pattern:
            return None
        try:
            return re.compile(self.unit_anchor_pattern, flags=re.IGNORECASE)
        except re.error:
            return None

    def _extract_contextual_unit_references(self, text: str) -> list[dict[str, int | str]]:
        context_pattern = self._context_anchor_regex()
        unit_pattern = self._unit_anchor_regex()
        if context_pattern is None or unit_pattern is None:
            return []
        context_matches = list(context_pattern.finditer(text))
        unit_matches = [
            match
            for match in unit_pattern.finditer(text)
            if not self._overlaps_context_anchor(match, context_matches)
        ]
        if not context_matches or not unit_matches:
            return []
        references: list[dict[str, int | str]] = []
        seen: set[str] = set()
        current_context: dict[str, str] = {}
        events = [("context", match) for match in context_matches]
        events.extend(("unit", match) for match in unit_matches)
        events.sort(key=lambda item: item[1].start())
        for event_type, match in events:
            groups = {key: value for key, value in match.groupdict().items() if value}
            if event_type == "context":
                current_context.update(groups)
                continue
            merged = {**current_context, **groups}
            if self.required_reference_groups:
                if not self.required_reference_groups.issubset(merged):
                    continue
            elif not merged:
                continue
            reference = self._reference_from_groups(match.group(0), merged)
            key = str(reference["ref"])
            if key in seen:
                continue
            seen.add(key)
            references.append(reference)
        return references

    def _split_contextual_unit_units(self, text: str) -> list[str]:
        context_pattern = self._context_anchor_regex()
        unit_pattern = self._unit_anchor_regex()
        if context_pattern is None or unit_pattern is None:
            return []
        context_matches = list(context_pattern.finditer(text))
        unit_matches = [
            match
            for match in unit_pattern.finditer(text)
            if not self._overlaps_context_anchor(match, context_matches)
        ]
        if not context_matches or not unit_matches:
            return []
        units: list[str] = []
        leading = text[: unit_matches[0].start()].strip()
        for index, match in enumerate(unit_matches):
            start = match.start()
            end_candidates = []
            if index + 1 < len(unit_matches):
                end_candidates.append(unit_matches[index + 1].start())
            next_context = self._next_context_match(context_matches, start)
            if next_context is not None:
                end_candidates.append(next_context.start())
            end = min(end_candidates) if end_candidates else len(text)
            unit = text[start:end].strip()
            if index == 0 and leading and context_pattern.search(leading):
                unit = f"{leading}\n\n{unit}".strip()
            elif not context_pattern.search(unit):
                context_prefix = self._context_prefix_for_unit(
                    text,
                    context_matches=context_matches,
                    unit_matches=unit_matches,
                    unit_index=index,
                )
                if context_prefix:
                    unit = f"{context_prefix}\n{unit}".strip()
            if unit:
                units.append(unit)
        return units

    def _context_prefix_for_unit(
        self,
        text: str,
        *,
        context_matches: list[re.Match[str]],
        unit_matches: list[re.Match[str]],
        unit_index: int,
    ) -> str:
        unit_start = unit_matches[unit_index].start()
        context_match = self._nearest_context_match(context_matches, unit_start)
        if context_match is None:
            return ""
        if unit_index > 0 and context_match.start() <= unit_matches[unit_index - 1].start():
            return context_match.group(0).strip()
        return text[context_match.start() : unit_start].strip()

    def _next_context_match(
        self,
        matches: list[re.Match[str]],
        position: int,
    ) -> re.Match[str] | None:
        for match in matches:
            if match.start() > position:
                return match
        return None

    def _nearest_context_match(
        self,
        matches: list[re.Match[str]],
        position: int,
    ) -> re.Match[str] | None:
        current: re.Match[str] | None = None
        for match in matches:
            if match.start() > position:
                break
            current = match
        return current

    @staticmethod
    def _overlaps_context_anchor(
        match: re.Match[str],
        context_matches: list[re.Match[str]],
    ) -> bool:
        return any(
            match.start() < context.end() and context.start() < match.end()
            for context in context_matches
        )

    def _reference_from_groups(
        self,
        raw: str,
        groups: dict[str, str],
    ) -> dict[str, int | str]:
        ref: dict[str, int | str] = {"raw": raw}
        for key, value in groups.items():
            ref[key] = int(value) if value.isdigit() else value
        templated_ref = self._render_canonical_ref(ref)
        if templated_ref:
            ref["ref"] = templated_ref
        else:
            ref["ref"] = raw.strip()
        ref["canonical"] = str(ref["ref"])
        return ref

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

    @classmethod
    def _anchor_by_kind(
        cls,
        anchors: tuple[ReferenceAnchor, ...],
        kind: str,
    ) -> ReferenceAnchor | None:
        normalized_kind = kind.casefold()
        return next(
            (
                anchor
                for anchor in anchors
                if anchor.kind.casefold() == normalized_kind
            ),
            None,
        )

    @classmethod
    def _verified_anchor_for_groups(
        cls,
        anchors: tuple[ReferenceAnchor, ...],
        kind: str,
        required_groups: frozenset[str],
    ) -> ReferenceAnchor | None:
        normalized_kind = kind.casefold()
        for anchor in anchors:
            if anchor.kind.casefold() != normalized_kind or not anchor.verified:
                continue
            if required_groups and not required_groups.issubset(anchor.group_names):
                continue
            return anchor
        return None

    @classmethod
    def _verified_context_anchor_for_groups(
        cls,
        anchors: tuple[ReferenceAnchor, ...],
        required_groups: frozenset[str],
    ) -> ReferenceAnchor | None:
        anchor = cls._verified_anchor_for_groups(anchors, "context_anchor", frozenset())
        if anchor is None:
            return None
        unit_anchor = cls._verified_anchor_for_groups(anchors, "unit_anchor", frozenset())
        if unit_anchor is None:
            return None
        groups = anchor.group_names | unit_anchor.group_names
        if required_groups and not required_groups.issubset(groups):
            return None
        return anchor

    @classmethod
    def _verified_unit_anchor_for_groups(
        cls,
        anchors: tuple[ReferenceAnchor, ...],
        required_groups: frozenset[str],
    ) -> ReferenceAnchor | None:
        context_anchor = cls._verified_anchor_for_groups(
            anchors,
            "context_anchor",
            frozenset(),
        )
        anchor = cls._verified_anchor_for_groups(anchors, "unit_anchor", frozenset())
        if context_anchor is None or anchor is None:
            return None
        groups = context_anchor.group_names | anchor.group_names
        if required_groups and not required_groups.issubset(groups):
            return None
        return anchor

    @staticmethod
    def _relationships(value: Any) -> dict[str, list[str]]:
        if not isinstance(value, dict):
            return {}
        return {
            key: [str(item) for item in items]
            for key, items in value.items()
            if isinstance(key, str) and isinstance(items, list)
        }

    @classmethod
    def _contract_state_verified(cls, custom_json: dict[str, Any]) -> bool:
        validation = custom_json.get("reference_contract_validation")
        validation = validation if isinstance(validation, dict) else {}
        execution = custom_json.get("reference_contract_execution")
        execution = execution if isinstance(execution, dict) else {}
        return validation.get("status") == "verified" or (
            not validation and execution.get("status") == "verified"
        )

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
    def _string_value(value: Any, *, default: str | None) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return default
