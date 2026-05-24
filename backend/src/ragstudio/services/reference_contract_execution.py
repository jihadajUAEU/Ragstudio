from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from ragstudio.services.page_sampler import SampledPage
from ragstudio.services.reference_contracts import canonical_reference_from_groups

ContractStatus = Literal["verified", "unverified"]
ExtractorType = Literal["regex", "contextual_regex"]


@dataclass(frozen=True)
class ContractAcceptance:
    min_matched_units: int = 1
    min_matched_pages: int = 1


@dataclass(frozen=True)
class ContractExtractor:
    type: ExtractorType
    target: str = "page_text"
    pattern: str | None = None
    context_pattern: str | None = None
    unit_pattern: str | None = None


@dataclass(frozen=True)
class GeneratedReferenceContract:
    schema_type: str
    unit: str
    identity_fields: tuple[str, ...]
    canonical_ref_template: str
    extractors: tuple[ContractExtractor, ...]
    acceptance: ContractAcceptance = field(default_factory=ContractAcceptance)


@dataclass(frozen=True)
class ExtractedReferenceUnit:
    canonical_reference: str
    groups: dict[str, str]
    raw: str
    start: int
    extractor_index: int
    provenance: dict[str, object]


@dataclass(frozen=True)
class ContractExecutionReport:
    status: ContractStatus
    schema_type: str
    unit: str
    identity_fields: tuple[str, ...]
    canonical_ref_template: str
    matched_units: int
    matched_pages: list[int]
    units: list[ExtractedReferenceUnit]
    rejection_reason: str | None = None


@dataclass(frozen=True)
class _ExtractorExecution:
    units: list[ExtractedReferenceUnit]
    matched_pages: set[int]
    rejection_reason: str | None


def execute_reference_contract(
    contract: GeneratedReferenceContract,
    pages: list[SampledPage],
) -> ContractExecutionReport:
    executions: list[_ExtractorExecution] = []
    for index, extractor in enumerate(contract.extractors):
        rejection = _extractor_rejection(contract, extractor)
        if rejection is not None:
            executions.append(_ExtractorExecution([], set(), rejection))
            continue

        units = (
            _regex_units(contract, extractor, index, pages)
            if extractor.type == "regex"
            else _contextual_units(contract, extractor, index, pages)
        )
        matched_pages = _matched_pages(units)
        executions.append(
            _ExtractorExecution(
                units=units,
                matched_pages=matched_pages,
                rejection_reason=_acceptance_rejection(contract, units, matched_pages),
            )
        )

    verified = [execution for execution in executions if execution.rejection_reason is None]
    if verified:
        selected = _best_execution(verified)
        return _report(contract, selected.units, selected.matched_pages, None)

    if not executions:
        return _report(contract, [], set(), "missing_extractor")

    if len(executions) == 1:
        selected = executions[0]
        return _report(contract, selected.units, selected.matched_pages, selected.rejection_reason)

    aggregate_units = [
        unit
        for execution in executions
        for unit in execution.units
    ]
    aggregate_pages = set().union(*(execution.matched_pages for execution in executions))
    if _acceptance_rejection(contract, aggregate_units, aggregate_pages) is None:
        return _report(
            contract,
            aggregate_units,
            aggregate_pages,
            "insufficient_extractor_evidence",
        )

    selected = _best_execution(executions)
    return _report(contract, selected.units, selected.matched_pages, selected.rejection_reason)


def _regex_units(
    contract: GeneratedReferenceContract,
    extractor: ContractExtractor,
    extractor_index: int,
    pages: list[SampledPage],
) -> list[ExtractedReferenceUnit]:
    pattern = re.compile(extractor.pattern or "")
    units: list[ExtractedReferenceUnit] = []
    for page in pages:
        for match in pattern.finditer(page.text or ""):
            unit = _unit_from_groups(
                contract,
                match.groupdict(),
                raw=match.group(0),
                start=match.start(),
                extractor_index=extractor_index,
                page_number=page.page_number,
                target=extractor.target,
            )
            if unit is not None:
                units.append(unit)
    return units


def _contextual_units(
    contract: GeneratedReferenceContract,
    extractor: ContractExtractor,
    extractor_index: int,
    pages: list[SampledPage],
) -> list[ExtractedReferenceUnit]:
    context_pattern = re.compile(extractor.context_pattern or "")
    unit_pattern = re.compile(extractor.unit_pattern or "")
    units: list[ExtractedReferenceUnit] = []
    for page in pages:
        current_context: dict[str, str] | None = None
        matches = [("context", match) for match in context_pattern.finditer(page.text or "")]
        matches.extend(("unit", match) for match in unit_pattern.finditer(page.text or ""))
        matches.sort(key=lambda item: item[1].start())
        for kind, match in matches:
            groups = {key: value for key, value in match.groupdict().items() if value}
            if kind == "context":
                current_context = groups
                continue
            if current_context is None:
                continue
            unit = _unit_from_groups(
                contract,
                {**current_context, **groups},
                raw=match.group(0),
                start=match.start(),
                extractor_index=extractor_index,
                page_number=page.page_number,
                target=extractor.target,
            )
            if unit is not None:
                units.append(unit)
    return units


def _unit_from_groups(
    contract: GeneratedReferenceContract,
    groups: dict[str, str],
    *,
    raw: str,
    start: int,
    extractor_index: int,
    page_number: int,
    target: str,
) -> ExtractedReferenceUnit | None:
    if not all(groups.get(field) for field in contract.identity_fields):
        return None
    canonical = canonical_reference_from_groups(groups, contract.canonical_ref_template)
    if canonical is None:
        return None
    return ExtractedReferenceUnit(
        canonical_reference=canonical,
        groups={field: groups[field] for field in contract.identity_fields},
        raw=raw,
        start=start,
        extractor_index=extractor_index,
        provenance={"page": page_number, "target": target},
    )


def _matched_pages(units: list[ExtractedReferenceUnit]) -> set[int]:
    matched_pages: set[int] = set()
    for unit in units:
        page = unit.provenance.get("page")
        if isinstance(page, int):
            matched_pages.add(page)
    return matched_pages


def _acceptance_rejection(
    contract: GeneratedReferenceContract,
    units: list[ExtractedReferenceUnit],
    matched_pages: set[int],
) -> str | None:
    if len(units) < contract.acceptance.min_matched_units:
        return "insufficient_matched_units"
    if len(matched_pages) < contract.acceptance.min_matched_pages:
        return "insufficient_matched_pages"
    return None


def _best_execution(executions: list[_ExtractorExecution]) -> _ExtractorExecution:
    return sorted(
        executions,
        key=lambda execution: (len(execution.units), len(execution.matched_pages)),
        reverse=True,
    )[0]


def _extractor_rejection(
    contract: GeneratedReferenceContract,
    extractor: ContractExtractor,
) -> str | None:
    if extractor.type not in {"regex", "contextual_regex"}:
        return "unsupported_extractor_type"
    patterns = (
        [extractor.pattern]
        if extractor.type == "regex"
        else [extractor.context_pattern, extractor.unit_pattern]
    )
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        if not pattern:
            return "missing_extractor_pattern"
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            return f"invalid_regex:{exc.msg}"
    declared_groups = set().union(*(set(pattern.groupindex) for pattern in compiled))
    if not set(contract.identity_fields).issubset(declared_groups):
        return "identity_fields_missing_from_extractor"
    return None


def _report(
    contract: GeneratedReferenceContract,
    units: list[ExtractedReferenceUnit],
    matched_pages: set[int],
    rejection_reason: str | None,
) -> ContractExecutionReport:
    return ContractExecutionReport(
        status="verified" if rejection_reason is None else "unverified",
        schema_type=contract.schema_type,
        unit=contract.unit,
        identity_fields=contract.identity_fields,
        canonical_ref_template=contract.canonical_ref_template,
        matched_units=len(units),
        matched_pages=sorted(matched_pages),
        units=units,
        rejection_reason=rejection_reason,
    )
