from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Literal

from ragstudio.services.metadata_json_schema import validate_custom_json
from ragstudio.services.page_sampler import SampledPage
from ragstudio.services.reference_contracts import canonical_reference_from_groups

ValidationStatus = Literal["verified", "unverified"]
ValidationStrategy = Literal["single_anchor", "contextual_unit"]


@dataclass(frozen=True)
class ReferenceContractCandidate:
    source: str
    schema_type: str
    primary_anchor_regex: str | None = None
    context_anchor_regex: str | None = None
    unit_anchor_regex: str | None = None
    inline_reference_regex: str | None = None
    unit: str | None = None
    required_groups: frozenset[str] = field(default_factory=frozenset)
    context_required_groups: frozenset[str] = field(default_factory=frozenset)
    unit_required_groups: frozenset[str] = field(default_factory=frozenset)
    canonical_ref_template: str | None = None


@dataclass(frozen=True)
class ReferenceContractCandidateResult:
    source: str
    schema_type: str
    primary_anchor_regex: str | None
    context_anchor_regex: str | None
    unit_anchor_regex: str | None
    inline_reference_regex: str | None
    unit: str | None
    strategy: ValidationStrategy | None
    valid_regex: bool
    required_groups_present: bool
    matched_units: int
    matched_pages: list[int] = field(default_factory=list)
    examples: list[dict[str, object]] = field(default_factory=list)
    rejection_reason: str | None = None


@dataclass(frozen=True)
class ReferenceContractValidationResult:
    status: ValidationStatus
    selected: ReferenceContractCandidateResult | None
    candidates: list[ReferenceContractCandidateResult]

    def to_payload(self) -> dict[str, object]:
        selected = self.selected
        return {
            "status": self.status,
            "selected_source": selected.source if selected else None,
            "selected_strategy": selected.strategy if selected else None,
            "selected_primary_anchor_regex": (
                selected.primary_anchor_regex if selected else None
            ),
            "selected_context_anchor_regex": (
                selected.context_anchor_regex if selected else None
            ),
            "selected_unit_anchor_regex": selected.unit_anchor_regex if selected else None,
            "matched_units": selected.matched_units if selected else 0,
            "matched_pages": selected.matched_pages if selected else [],
            "candidates": [asdict(candidate) for candidate in self.candidates],
        }


class ReferenceContractValidator:
    def validate(
        self,
        pages: list[SampledPage],
        candidates: list[ReferenceContractCandidate],
    ) -> ReferenceContractValidationResult:
        results = [self._validate_candidate(pages, candidate) for candidate in candidates]
        selected = self._select_candidate(results)
        return ReferenceContractValidationResult(
            status="verified" if selected is not None else "unverified",
            selected=selected,
            candidates=results,
        )

    def _validate_candidate(
        self,
        pages: list[SampledPage],
        candidate: ReferenceContractCandidate,
    ) -> ReferenceContractCandidateResult:
        if candidate.primary_anchor_regex:
            return self._validate_single_anchor_candidate(pages, candidate)
        if candidate.context_anchor_regex and candidate.unit_anchor_regex:
            return self._validate_contextual_unit_candidate(pages, candidate)
        return self._rejected(candidate, "missing_reference_anchor_regex")

    def _validate_single_anchor_candidate(
        self,
        pages: list[SampledPage],
        candidate: ReferenceContractCandidate,
    ) -> ReferenceContractCandidateResult:
        if not candidate.primary_anchor_regex:
            return self._rejected(candidate, "missing_primary_anchor_regex")
        schema_rejection = self._anchor_schema_rejection(
            candidate.primary_anchor_regex,
            "primary_anchor",
        )
        if schema_rejection is not None:
            return self._rejected(candidate, schema_rejection)
        try:
            pattern = re.compile(candidate.primary_anchor_regex)
        except re.error as exc:
            return self._rejected(candidate, f"invalid_regex:{exc.msg}")
        inline_reference_regex = self._safe_optional_anchor_regex(
            candidate.inline_reference_regex,
            "inline_references",
        )

        required_groups = candidate.required_groups
        required_groups_present = required_groups.issubset(set(pattern.groupindex))
        matched_pages: list[int] = []
        examples: list[dict[str, object]] = []
        matched_units = 0
        for page in pages:
            page_text = page.text or ""
            page_matches = list(pattern.finditer(page_text))
            if page_matches:
                matched_pages.append(page.page_number)
            matched_units += len(page_matches)
            for match in page_matches:
                if len(examples) >= 6:
                    break
                groups = self._match_groups(match)
                reference = canonical_reference_from_groups(
                    groups,
                    candidate.canonical_ref_template,
                )
                examples.append(
                    {
                        "page": page.page_number,
                        "reference": reference or match.group(0),
                        "groups": groups,
                        "raw": match.group(0),
                        "start": match.start(),
                    }
                )

        return ReferenceContractCandidateResult(
            source=candidate.source,
            schema_type=candidate.schema_type,
            primary_anchor_regex=candidate.primary_anchor_regex,
            context_anchor_regex=candidate.context_anchor_regex,
            unit_anchor_regex=candidate.unit_anchor_regex,
            inline_reference_regex=inline_reference_regex,
            unit=candidate.unit,
            strategy="single_anchor",
            valid_regex=True,
            required_groups_present=required_groups_present,
            matched_units=matched_units,
            matched_pages=matched_pages,
            examples=examples,
            rejection_reason=None
            if required_groups_present and matched_units > 0
            else "no_sample_matches",
        )

    def _validate_contextual_unit_candidate(
        self,
        pages: list[SampledPage],
        candidate: ReferenceContractCandidate,
    ) -> ReferenceContractCandidateResult:
        context_rejection = self._anchor_schema_rejection(
            candidate.context_anchor_regex or "",
            "context_anchor",
        )
        if context_rejection is not None:
            return self._rejected(candidate, context_rejection)
        unit_rejection = self._anchor_schema_rejection(
            candidate.unit_anchor_regex or "",
            "unit_anchor",
        )
        if unit_rejection is not None:
            return self._rejected(candidate, unit_rejection)
        try:
            context_pattern = re.compile(candidate.context_anchor_regex or "")
            unit_pattern = re.compile(candidate.unit_anchor_regex or "")
        except re.error as exc:
            return self._rejected(candidate, f"invalid_regex:{exc.msg}")
        inline_reference_regex = self._safe_optional_anchor_regex(
            candidate.inline_reference_regex,
            "inline_references",
        )

        context_required_groups = candidate.context_required_groups
        unit_required_groups = candidate.unit_required_groups
        required_groups_present = context_required_groups.issubset(
            set(context_pattern.groupindex)
        ) and unit_required_groups.issubset(set(unit_pattern.groupindex))
        matched_pages: list[int] = []
        examples: list[dict[str, object]] = []
        matched_units = 0

        for page in pages:
            current_context_groups: dict[str, str] | None = None
            page_matched = False
            matches = [
                ("context", match) for match in context_pattern.finditer(page.text or "")
            ]
            matches.extend(("unit", match) for match in unit_pattern.finditer(page.text or ""))
            matches.sort(key=lambda item: item[1].start())
            for match_kind, match in matches:
                groups = self._match_groups(match)
                if match_kind == "context":
                    if self._has_groups(groups, context_required_groups):
                        current_context_groups = groups
                    continue
                if current_context_groups is None or not self._has_groups(
                    groups,
                    unit_required_groups,
                ):
                    continue
                merged_groups = {**current_context_groups, **groups}
                matched_units += 1
                page_matched = True
                if len(examples) < 6:
                    reference = canonical_reference_from_groups(
                        merged_groups,
                        candidate.canonical_ref_template,
                    )
                    examples.append(
                        {
                            "page": page.page_number,
                            "reference": reference or match.group(0),
                            "context": self._example_group_value(
                                current_context_groups,
                                context_required_groups,
                            ),
                            "unit": self._example_group_value(
                                groups,
                                unit_required_groups,
                            ),
                            "context_groups": current_context_groups,
                            "unit_groups": groups,
                            "groups": merged_groups,
                            "raw": match.group(0),
                            "start": match.start(),
                        }
                    )
            if page_matched:
                matched_pages.append(page.page_number)

        return ReferenceContractCandidateResult(
            source=candidate.source,
            schema_type=candidate.schema_type,
            primary_anchor_regex=candidate.primary_anchor_regex,
            context_anchor_regex=candidate.context_anchor_regex,
            unit_anchor_regex=candidate.unit_anchor_regex,
            inline_reference_regex=inline_reference_regex,
            unit=candidate.unit,
            strategy="contextual_unit",
            valid_regex=True,
            required_groups_present=required_groups_present,
            matched_units=matched_units,
            matched_pages=matched_pages,
            examples=examples,
            rejection_reason=None
            if required_groups_present and matched_units > 0
            else "no_sample_matches",
        )

    def _select_candidate(
        self,
        results: list[ReferenceContractCandidateResult],
    ) -> ReferenceContractCandidateResult | None:
        eligible = [
            result
            for result in results
            if result.valid_regex
            and result.required_groups_present
            and result.matched_units > 0
        ]
        if not eligible:
            return None
        return sorted(
            eligible,
            key=lambda result: (result.matched_units, len(result.matched_pages)),
            reverse=True,
        )[0]

    def _rejected(
        self,
        candidate: ReferenceContractCandidate,
        reason: str,
    ) -> ReferenceContractCandidateResult:
        return ReferenceContractCandidateResult(
            source=candidate.source,
            schema_type=candidate.schema_type,
            primary_anchor_regex=candidate.primary_anchor_regex,
            context_anchor_regex=candidate.context_anchor_regex,
            unit_anchor_regex=candidate.unit_anchor_regex,
            inline_reference_regex=candidate.inline_reference_regex,
            unit=candidate.unit,
            strategy=None,
            valid_regex=False,
            required_groups_present=False,
            matched_units=0,
            rejection_reason=reason,
        )

    def _anchor_schema_rejection(self, regex: str, anchor_key: str) -> str | None:
        try:
            validate_custom_json({"domain_structure": {anchor_key: {"regex": regex}}})
        except ValueError as exc:
            return f"unsupported_regex:{exc}"
        return None

    def _safe_optional_anchor_regex(
        self,
        regex: str | None,
        anchor_key: str,
    ) -> str | None:
        if not regex:
            return None
        return None if self._anchor_schema_rejection(regex, anchor_key) else regex

    def _match_groups(self, match: re.Match[str]) -> dict[str, str]:
        return {
            key: value
            for key, value in match.groupdict().items()
            if value is not None
        }

    def _has_groups(
        self,
        groups: dict[str, str],
        required_groups: frozenset[str],
    ) -> bool:
        return all(groups.get(group) for group in required_groups)

    def _example_group_value(
        self,
        groups: dict[str, str],
        required_groups: frozenset[str],
    ) -> str | dict[str, str]:
        if len(required_groups) == 1:
            group = next(iter(required_groups))
            return groups.get(group, "")
        return groups
