from __future__ import annotations

import re
from string import Formatter
from typing import Any

from ragstudio.services.reference_contracts import canonical_reference_from_groups

_REFERENCE_GROUP_VALUE = r"[A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)*"


def parse_query_references(query: str, contracts: list[dict[str, Any]]) -> list[str]:
    references: list[str] = []
    for contract in contracts:
        reference_contract = _reference_contract(contract)
        if not reference_contract or reference_contract.get("verified") is not True:
            continue
        template = _string_value(reference_contract.get("canonical_ref_template"))
        anchors = _anchors(reference_contract)
        references.extend(_template_references(query, reference_contract, template))
        references.extend(_single_anchor_references(query, anchors, template))
        references.extend(_contextual_references(query, anchors, template))
    return list(dict.fromkeys(references))


def _single_anchor_references(
    query: str,
    anchors: list[dict[str, Any]],
    template: str | None,
) -> list[str]:
    references: list[str] = []
    for anchor in anchors:
        if anchor.get("kind") not in {"primary_anchor", "inline_references"}:
            continue
        pattern = _compiled_pattern(anchor.get("regex"))
        if pattern is None:
            continue
        for match in pattern.finditer(query):
            reference = _reference_from_match(match, template)
            if reference:
                references.append(reference)
    return references


def _contextual_references(
    query: str,
    anchors: list[dict[str, Any]],
    template: str | None,
) -> list[str]:
    context_patterns = [
        pattern
        for anchor in anchors
        if anchor.get("kind") == "context_anchor"
        for pattern in [_compiled_pattern(anchor.get("regex"))]
        if pattern is not None
    ]
    unit_patterns = [
        pattern
        for anchor in anchors
        if anchor.get("kind") == "unit_anchor"
        for pattern in [_compiled_pattern(anchor.get("regex"))]
        if pattern is not None
    ]
    if not context_patterns or not unit_patterns:
        return []

    events: list[tuple[int, str, re.Match[str]]] = []
    for pattern in context_patterns:
        events.extend((match.start(), "context", match) for match in pattern.finditer(query))
    for pattern in unit_patterns:
        events.extend((match.start(), "unit", match) for match in pattern.finditer(query))
    events.sort(key=lambda item: item[0])

    references: list[str] = []
    current_context: dict[str, str] = {}
    for _position, event_type, match in events:
        groups = {key: value for key, value in match.groupdict().items() if value}
        if event_type == "context":
            current_context.update(groups)
            continue
        merged = {**current_context, **groups}
        reference = canonical_reference_from_groups(merged, template)
        if reference:
            references.append(reference)
    return references


def _template_references(
    query: str,
    reference_contract: dict[str, Any],
    template: str | None,
) -> list[str]:
    pattern = _canonical_template_pattern(template)
    if pattern is None:
        return []
    required_groups = set(_string_list(reference_contract.get("required_groups")))
    references: list[str] = []
    for match in pattern.finditer(query):
        groups = {key: value for key, value in match.groupdict().items() if value}
        if required_groups and not required_groups.issubset(groups):
            continue
        reference = canonical_reference_from_groups(groups, template)
        if reference:
            references.append(reference)
    return references


def _reference_contract(contract: dict[str, Any]) -> dict[str, Any]:
    reference_contract = contract.get("reference_contract")
    if isinstance(reference_contract, dict):
        return reference_contract
    return contract


def _anchors(reference_contract: dict[str, Any]) -> list[dict[str, Any]]:
    anchors = reference_contract.get("anchors")
    if isinstance(anchors, list):
        return [anchor for anchor in anchors if isinstance(anchor, dict)]

    result: list[dict[str, Any]] = []
    patterns = reference_contract.get("patterns")
    if isinstance(patterns, list):
        for pattern in patterns:
            regex = _string_value(pattern)
            if regex:
                result.append({"kind": "primary_anchor", "regex": regex, "verified": True})
    for kind, key in (
        ("primary_anchor", "primary_anchor_regex"),
        ("context_anchor", "context_anchor_regex"),
        ("unit_anchor", "unit_anchor_regex"),
        ("inline_references", "inline_reference_regex"),
    ):
        regex = _string_value(reference_contract.get(key))
        if regex:
            result.append({"kind": kind, "regex": regex, "verified": True})
    return result


def _reference_from_match(match: re.Match[str], template: str | None) -> str | None:
    groups = {key: value for key, value in match.groupdict().items() if value}
    return canonical_reference_from_groups(groups, template) or match.group(0).strip()


def _compiled_pattern(value: Any) -> re.Pattern[str] | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return re.compile(value, flags=re.IGNORECASE)
    except re.error:
        return None


def _canonical_template_pattern(template: str | None) -> re.Pattern[str] | None:
    if not template:
        return None
    parts: list[str] = [r"(?<![A-Za-z0-9_])"]
    seen_groups: set[str] = set()
    try:
        parsed = list(Formatter().parse(template))
    except ValueError:
        return None
    for literal, field_name, _format_spec, _conversion in parsed:
        parts.append(re.escape(literal))
        if not field_name:
            continue
        group_name = field_name.split(".", 1)[0].split("[", 1)[0]
        if not re.fullmatch(r"[A-Za-z]\w*", group_name) or group_name in seen_groups:
            return None
        seen_groups.add(group_name)
        parts.append(rf"(?P<{group_name}>{_REFERENCE_GROUP_VALUE})")
    if not seen_groups:
        return None
    parts.append(r"(?![A-Za-z0-9_])")
    try:
        return re.compile("".join(parts), flags=re.IGNORECASE)
    except re.error:
        return None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list | tuple | set):
        return [
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip()
        ]
    return []


def _string_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
