from __future__ import annotations

import re
from dataclasses import dataclass, field
from string import Formatter
from typing import Any


@dataclass(frozen=True)
class ReferenceAnchor:
    kind: str
    regex: str
    unit_role: str | None = None
    context_source: str | None = None
    policy: str | None = None
    verified: bool = False

    @property
    def pattern(self) -> re.Pattern[str]:
        return re.compile(self.regex, flags=re.IGNORECASE)

    @property
    def group_names(self) -> frozenset[str]:
        return frozenset(self.pattern.groupindex)


@dataclass(frozen=True)
class ExecutableReferenceContract:
    schema_type: str | None
    canonical_ref_template: str | None
    required_groups: frozenset[str]
    anchors: tuple[ReferenceAnchor, ...]
    required_scripts: frozenset[str] = field(default_factory=frozenset)
    optional_scripts: frozenset[str] = field(default_factory=frozenset)
    required_scripts_by_unit_role: dict[str, frozenset[str]] = field(default_factory=dict)
    optional_scripts_by_unit_role: dict[str, frozenset[str]] = field(default_factory=dict)

    @property
    def verified(self) -> bool:
        return any(anchor.verified for anchor in self.anchors)

    def required_scripts_for_role(self, role: str | None) -> frozenset[str]:
        return _scripts_for_role(self.required_scripts, self.required_scripts_by_unit_role, role)

    def optional_scripts_for_role(self, role: str | None) -> frozenset[str]:
        return _scripts_for_role(self.optional_scripts, self.optional_scripts_by_unit_role, role)


def build_executable_reference_contract(custom_json: dict[str, Any]) -> ExecutableReferenceContract:
    reference_schema = _dict_value(custom_json.get("reference_schema"))
    domain_structure = _dict_value(custom_json.get("domain_structure"))
    quality_policy = _dict_value(custom_json.get("quality_policy"))

    return ExecutableReferenceContract(
        schema_type=_string_value(reference_schema.get("type")),
        canonical_ref_template=_string_value(reference_schema.get("canonical_ref_template")),
        required_groups=frozenset(declared_required_groups(custom_json)),
        anchors=tuple(_declared_anchors(domain_structure)),
        required_scripts=_script_set(quality_policy.get("required_scripts")),
        optional_scripts=_script_set(quality_policy.get("optional_scripts")),
        required_scripts_by_unit_role=_script_map(
            quality_policy.get("required_scripts_by_unit_role")
        ),
        optional_scripts_by_unit_role=_script_map(
            quality_policy.get("optional_scripts_by_unit_role")
        ),
    )


def declared_required_groups(custom_json: dict[str, Any]) -> set[str]:
    reference_schema = _dict_value(custom_json.get("reference_schema"))
    groups: set[str] = set()

    fields = reference_schema.get("fields")
    if isinstance(fields, dict):
        groups.update(
            str(key).strip() for key in fields if isinstance(key, str) and key.strip()
        )

    template = _string_value(reference_schema.get("canonical_ref_template"))
    if template:
        groups.update(_template_fields(template))

    return groups


def canonical_reference_from_groups(groups: dict[str, str], template: str | None) -> str | None:
    if not template:
        return None
    try:
        rendered = template.format(**groups).strip()
    except (KeyError, IndexError, ValueError):
        return None
    return rendered or None


def _declared_anchors(domain_structure: dict[str, Any]) -> list[ReferenceAnchor]:
    anchors: list[ReferenceAnchor] = []
    for key, value in domain_structure.items():
        payload = _dict_value(value)
        regex = _string_value(payload.get("regex"))
        if not isinstance(key, str) or not regex:
            continue
        anchors.append(
            ReferenceAnchor(
                kind=key,
                regex=regex,
                unit_role=_string_value(payload.get("unit")),
                context_source=_string_value(payload.get("context_source")),
                policy=_string_value(payload.get("policy")),
                verified=payload.get("verified") is True,
            )
        )
    return anchors


def _template_fields(template: str) -> set[str]:
    return {
        field_name.split(".", 1)[0].split("[", 1)[0]
        for _, field_name, _, _ in Formatter().parse(template)
        if field_name
    }


def _scripts_for_role(
    base_scripts: frozenset[str],
    role_scripts: dict[str, frozenset[str]],
    role: str | None,
) -> frozenset[str]:
    scripts = set(base_scripts)
    for fallback in ("*", "all", "default", "reference_unit"):
        scripts.update(role_scripts.get(fallback, frozenset()))
    role_key = role.strip().casefold() if isinstance(role, str) else None
    if role_key:
        scripts.update(role_scripts.get(role_key, frozenset()))
    return frozenset(scripts)


def _script_set(value: Any) -> frozenset[str]:
    if not isinstance(value, list):
        return frozenset()
    return frozenset(
        str(item).strip().casefold()
        for item in value
        if isinstance(item, str) and item.strip()
    )


def _script_map(value: Any) -> dict[str, frozenset[str]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, frozenset[str]] = {}
    for key, scripts in value.items():
        if isinstance(key, str) and key.strip():
            result[key.strip().casefold()] = _script_set(scripts)
    return result


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _string_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
