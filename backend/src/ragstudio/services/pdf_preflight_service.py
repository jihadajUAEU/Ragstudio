from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ragstudio.services.script_detection import SCRIPT_PATTERNS


@dataclass(frozen=True)
class PdfPreflightIssue:
    code: str
    message: str
    page: int | None = None
    reference: str | None = None


@dataclass(frozen=True)
class PdfPreflightResult:
    status: str
    inspected_pages: int
    inspected_page_numbers: list[int]
    extracted_text_chars: int
    arabic_unit_count: int
    missing_arabic_unit_count: int
    reference_unit_count: int = 0
    passed_reference_script_ratio: float | None = None
    issues: list[PdfPreflightIssue] = field(default_factory=list)


class PdfPreflightService:
    def inspect(
        self,
        path: Path,
        contract: dict[str, Any] | None,
        *,
        mode: Literal["sample", "full_validation"] = "sample",
    ) -> PdfPreflightResult:
        try:
            import fitz  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - dependency is runtime-required
            raise RuntimeError("PyMuPDF is required for PDF preflight inspection.") from exc

        issues: list[PdfPreflightIssue] = []
        extracted_text_chars = 0
        arabic_unit_count = 0
        missing_arabic_unit_count = 0
        reference_unit_count = 0
        reference_units_missing_expected_scripts = 0
        expected_scripts = _expected_scripts_from_contract(contract)
        strict_preflight = _strict_preflight_enabled(contract)
        min_reference_script_pass_ratio = _min_reference_script_pass_ratio(contract)

        with fitz.open(path) as document:
            page_numbers = _page_numbers_for_mode(document.page_count, contract, mode)
            for page_number in page_numbers:
                page = document[page_number - 1]
                page_text = _page_text(page)
                extracted_text_chars += len(page_text)
                reference_units = _reference_units(page_text, contract)

                if strict_preflight and not page_text.strip():
                    issues.append(
                        PdfPreflightIssue(
                            code="pdf_text_extraction_empty",
                            message="No extractable text was detected on an inspected page.",
                            page=page_number,
                        )
                    )
                elif (
                    strict_preflight
                    and _expects_reference_units(contract)
                    and not reference_units
                ):
                    issues.append(
                        PdfPreflightIssue(
                            code="reference_unit_missing",
                            message=(
                                "Expected reference-bearing units were not detected "
                                "in extracted PDF text."
                            ),
                            page=page_number,
                        )
                    )

                for reference, unit_text in reference_units:
                    reference_unit_count += 1
                    missing_scripts = _missing_expected_scripts(unit_text, expected_scripts)
                    if missing_scripts:
                        reference_units_missing_expected_scripts += 1
                    if "arabic" in expected_scripts and "arabic" not in missing_scripts:
                        arabic_unit_count += 1
                    if "arabic" in missing_scripts:
                        missing_arabic_unit_count += 1
                    for script in sorted(missing_scripts):
                        issues.append(
                            PdfPreflightIssue(
                                code="reference_unit_missing_expected_script",
                                message=(
                                    "Reference-bearing unit is expected to contain "
                                    f"{script.capitalize()} script, but it was not detected."
                                ),
                                page=page_number,
                                reference=reference,
                            )
                        )

        passed_reference_script_ratio = _passed_reference_script_ratio(
            reference_unit_count,
            reference_units_missing_expected_scripts,
        )
        status = "passed"
        if strict_preflight and _has_blocking_issues(
            issues,
            passed_reference_script_ratio=passed_reference_script_ratio,
            min_reference_script_pass_ratio=min_reference_script_pass_ratio,
        ):
            status = "failed"
        return PdfPreflightResult(
            status=status,
            inspected_pages=len(page_numbers),
            inspected_page_numbers=page_numbers,
            extracted_text_chars=extracted_text_chars,
            arabic_unit_count=arabic_unit_count,
            missing_arabic_unit_count=missing_arabic_unit_count,
            reference_unit_count=reference_unit_count,
            passed_reference_script_ratio=passed_reference_script_ratio,
            issues=issues,
        )


def _expected_scripts_from_contract(contract: dict[str, Any] | None) -> set[str]:
    if not isinstance(contract, dict):
        return set()
    preprocessing = contract.get("preprocessing")
    if isinstance(preprocessing, dict):
        scripts = _normalized_scripts(preprocessing.get("expected_scripts"))
        if scripts:
            return scripts
    vision_analysis = contract.get("vision_analysis")
    if isinstance(vision_analysis, dict):
        return _normalized_scripts(vision_analysis.get("expected_scripts"))
    return set()


def _normalized_scripts(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {
        str(item).strip().casefold()
        for item in value
        if isinstance(item, str) and str(item).strip().casefold() in SCRIPT_PATTERNS
    }


def _strict_preflight_enabled(contract: dict[str, Any] | None) -> bool:
    if not isinstance(contract, dict):
        return False
    preprocessing = contract.get("preprocessing")
    return (
        isinstance(preprocessing, dict)
        and preprocessing.get("strict_pdf_text_preflight") is True
    )


def _expects_reference_units(contract: dict[str, Any] | None) -> bool:
    if not isinstance(contract, dict):
        return False
    reference_contract = contract.get("reference_contract")
    if not (
        isinstance(reference_contract, dict)
        and reference_contract.get("verified") is True
    ):
        return False
    vision_analysis = contract.get("vision_analysis")
    if isinstance(vision_analysis, dict):
        observed_pattern = str(
            vision_analysis.get("observed_unit_pattern")
            or vision_analysis.get("unit_pattern")
            or ""
        ).casefold()
        if "reference" in observed_pattern:
            return True
    return bool(reference_contract.get("schema_type"))


def _min_reference_script_pass_ratio(contract: dict[str, Any] | None) -> float:
    if not isinstance(contract, dict):
        return 1.0
    preprocessing = contract.get("preprocessing")
    if not isinstance(preprocessing, dict):
        return 1.0
    value = preprocessing.get("min_reference_script_pass_ratio")
    if isinstance(value, bool):
        return 1.0
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(ratio, 1.0))


def _passed_reference_script_ratio(
    reference_unit_count: int,
    reference_units_missing_expected_scripts: int,
) -> float | None:
    if reference_unit_count <= 0:
        return None
    passed_count = reference_unit_count - reference_units_missing_expected_scripts
    return passed_count / reference_unit_count


def _has_blocking_issues(
    issues: list[PdfPreflightIssue],
    *,
    passed_reference_script_ratio: float | None,
    min_reference_script_pass_ratio: float,
) -> bool:
    for issue in issues:
        if issue.code == "pdf_text_extraction_empty":
            return True
        if issue.code == "reference_unit_missing" and passed_reference_script_ratio is None:
            return True
    if passed_reference_script_ratio is None:
        return bool(issues)
    return passed_reference_script_ratio < min_reference_script_pass_ratio


def _page_numbers_for_mode(
    page_count: int,
    contract: dict[str, Any] | None,
    mode: Literal["sample", "full_validation"],
) -> list[int]:
    if mode == "full_validation":
        return list(range(1, page_count + 1))

    sample_pages: list[int] = []
    if isinstance(contract, dict):
        preprocessing = contract.get("preprocessing")
        if isinstance(preprocessing, dict):
            raw_pages = preprocessing.get("sample_pages")
            if isinstance(raw_pages, list):
                sample_pages = [
                    page
                    for page in raw_pages
                    if isinstance(page, int) and 1 <= page <= page_count
                ]
        vision_analysis = contract.get("vision_analysis")
        if not sample_pages and isinstance(vision_analysis, dict):
            raw_pages = vision_analysis.get("sample_pages")
            if isinstance(raw_pages, list):
                sample_pages.extend(
                    page
                    for page in raw_pages
                    if isinstance(page, int) and 1 <= page <= page_count
                )
    if sample_pages:
        representative_pages = _representative_page_numbers(page_count) if page_count > 20 else []
        return list(dict.fromkeys([*sample_pages, *representative_pages]))
    if page_count == 0:
        return []
    return _representative_page_numbers(page_count)


def _representative_page_numbers(page_count: int) -> list[int]:
    if page_count == 0:
        return []
    if page_count <= 3:
        return list(range(1, page_count + 1))
    representative_pages = [1, max(1, (page_count + 1) // 2), page_count]
    return list(dict.fromkeys(representative_pages))


def _page_text(page: Any) -> str:
    blocks = page.get_text("blocks")
    ordered_blocks: list[tuple[float, float, str]] = []
    for block in blocks:
        if len(block) < 5:
            continue
        text = block[4]
        if not isinstance(text, str) or not text.strip():
            continue
        ordered_blocks.append((float(block[1]), float(block[0]), text.strip()))
    ordered_blocks.sort(key=lambda item: (item[0], item[1]))
    return "\n".join(text for _, _, text in ordered_blocks)


def _reference_units(
    page_text: str,
    contract: dict[str, Any] | None = None,
) -> list[tuple[str, str]]:
    matches = _reference_matches_from_contract(page_text, contract)
    matches.sort(key=lambda item: item.start())

    units: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(page_text)
        units.append((match.group(0), page_text[start:end].strip()))
    return units


def _overlaps_existing_span(
    span: tuple[int, int],
    occupied_spans: list[tuple[int, int]],
) -> bool:
    start, end = span
    return any(
        start < existing_end and end > existing_start
        for existing_start, existing_end in occupied_spans
    )


def _reference_matches_from_contract(
    page_text: str,
    contract: dict[str, Any] | None,
) -> list[re.Match[str]]:
    if not isinstance(contract, dict):
        return []
    reference_contract = contract.get("reference_contract")
    if not (
        isinstance(reference_contract, dict)
        and reference_contract.get("verified") is True
    ):
        return []

    matches: list[re.Match[str]] = []
    occupied_spans: list[tuple[int, int]] = []
    for pattern in _reference_patterns_from_contract(reference_contract):
        for match in pattern.finditer(page_text):
            span = match.span()
            if _overlaps_existing_span(span, occupied_spans):
                continue
            matches.append(match)
            occupied_spans.append(span)

    for match in _contextual_unit_matches(page_text, reference_contract):
        span = match.span()
        if _overlaps_existing_span(span, occupied_spans):
            continue
        matches.append(match)
        occupied_spans.append(span)
    return matches


def _reference_patterns_from_contract(
    reference_contract: dict[str, Any],
) -> list[re.Pattern[str]]:
    patterns: list[re.Pattern[str]] = []
    anchors = _anchor_list(reference_contract)
    strategy = _string_value(reference_contract.get("strategy"))
    has_context_anchor = _anchor_by_kind(reference_contract, "context_anchor") is not None
    for anchor in anchors:
        kind = _string_value(anchor.get("kind"))
        if kind == "context_anchor":
            continue
        if kind == "unit_anchor" and strategy == "contextual_unit" and has_context_anchor:
            continue
        pattern = _compiled_reference_pattern(anchor.get("regex"))
        if pattern is not None:
            patterns.append(pattern)

    if not patterns:
        for key in ("primary_anchor_regex", "unit_anchor_regex", "inline_reference_regex"):
            if (
                key == "unit_anchor_regex"
                and strategy == "contextual_unit"
                and reference_contract.get("context_anchor_regex")
            ):
                continue
            pattern = _compiled_reference_pattern(reference_contract.get(key))
            if pattern is not None:
                patterns.append(pattern)
    return _dedupe_patterns(patterns)


def _contextual_unit_matches(
    page_text: str,
    reference_contract: dict[str, Any],
) -> list[re.Match[str]]:
    context_anchor = _anchor_by_kind(reference_contract, "context_anchor")
    unit_anchor = _anchor_by_kind(reference_contract, "unit_anchor")
    if (
        reference_contract.get("strategy") != "contextual_unit"
        and (context_anchor is None or unit_anchor is None)
    ):
        return []
    context_regex = (
        context_anchor.get("regex")
        if context_anchor
        else reference_contract.get("context_anchor_regex")
    )
    unit_regex = (
        unit_anchor.get("regex")
        if unit_anchor
        else reference_contract.get("unit_anchor_regex")
    )
    context_pattern = _compiled_reference_pattern(
        context_regex
    )
    unit_pattern = _compiled_reference_pattern(unit_regex)
    if context_pattern is None or unit_pattern is None:
        return []

    context_matches = list(context_pattern.finditer(page_text))
    if not context_matches:
        return []

    matches: list[re.Match[str]] = []
    context_index = -1
    for unit_match in unit_pattern.finditer(page_text):
        while (
            context_index + 1 < len(context_matches)
            and context_matches[context_index + 1].start() <= unit_match.start()
        ):
            context_index += 1
        if context_index < 0:
            continue
        if context_matches[context_index].end() <= unit_match.start():
            matches.append(unit_match)
    return matches


def _anchor_list(reference_contract: dict[str, Any]) -> list[dict[str, Any]]:
    anchors = reference_contract.get("anchors")
    if not isinstance(anchors, list):
        return []
    return [anchor for anchor in anchors if isinstance(anchor, dict)]


def _anchor_by_kind(
    reference_contract: dict[str, Any],
    kind: str,
) -> dict[str, Any] | None:
    for anchor in _anchor_list(reference_contract):
        if anchor.get("kind") == kind:
            return anchor
    return None


def _dedupe_patterns(patterns: list[re.Pattern[str]]) -> list[re.Pattern[str]]:
    deduped: list[re.Pattern[str]] = []
    seen: set[tuple[str, int]] = set()
    for pattern in patterns:
        key = (pattern.pattern, pattern.flags)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(pattern)
    return deduped


def _compiled_reference_pattern(value: Any) -> re.Pattern[str] | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return re.compile(value, flags=re.IGNORECASE)
    except re.error:
        return None


def _string_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _missing_expected_scripts(text: str, expected_scripts: set[str]) -> set[str]:
    return {
        script
        for script in expected_scripts
        if not SCRIPT_PATTERNS.get(script, re.compile(r"$^")).search(text or "")
    }
