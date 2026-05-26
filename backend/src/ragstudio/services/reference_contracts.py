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
    canonical_ref_template_valid: bool
    required_groups: frozenset[str]
    anchors: tuple[ReferenceAnchor, ...]
    required_scripts: frozenset[str] = field(default_factory=frozenset)
    optional_scripts: frozenset[str] = field(default_factory=frozenset)
    required_scripts_by_unit_role: dict[str, frozenset[str]] = field(default_factory=dict)
    optional_scripts_by_unit_role: dict[str, frozenset[str]] = field(default_factory=dict)

    @property
    def verified(self) -> bool:
        return (
            self.canonical_ref_template_valid
            and (
                self._verified_primary_anchor_satisfies_required_groups()
                or self._verified_context_unit_anchors_satisfy_required_groups()
            )
        )

    @property
    def declared_executable_anchor_group_names(self) -> frozenset[str]:
        return self.anchor_group_names(
            "primary_anchor",
            "context_anchor",
            "unit_anchor",
        )

    @property
    def executable_anchor_group_names(self) -> frozenset[str]:
        primary_groups = self._verified_primary_anchor_group_names()
        if primary_groups is not None:
            return primary_groups
        context_unit_groups = self._verified_context_unit_anchor_group_names()
        return context_unit_groups or frozenset()

    @property
    def missing_required_groups(self) -> frozenset[str]:
        return self.required_groups - self.executable_anchor_group_names

    @property
    def missing_declared_executable_anchor_groups(self) -> frozenset[str]:
        return self.required_groups - self.declared_executable_anchor_group_names

    def anchor_group_names(
        self,
        *kinds: str,
        require_verified: bool = False,
    ) -> frozenset[str]:
        kind_set = {_normalized_key(kind) for kind in kinds if kind}
        groups: set[str] = set()
        for anchor in self.anchors:
            if kind_set and _normalized_key(anchor.kind) not in kind_set:
                continue
            if require_verified and not anchor.verified:
                continue
            groups.update(anchor.group_names)
        return frozenset(groups)

    def required_scripts_for_role(self, role: str | None) -> frozenset[str]:
        return _scripts_for_role(self.required_scripts, self.required_scripts_by_unit_role, role)

    def optional_scripts_for_role(self, role: str | None) -> frozenset[str]:
        return _scripts_for_role(self.optional_scripts, self.optional_scripts_by_unit_role, role)

    def _verified_primary_anchor_satisfies_required_groups(self) -> bool:
        return self._verified_primary_anchor_group_names() is not None

    def _verified_context_unit_anchors_satisfy_required_groups(self) -> bool:
        return self._verified_context_unit_anchor_group_names() is not None

    def _verified_primary_anchor_group_names(self) -> frozenset[str] | None:
        for anchor in self._anchors_by_kind("primary_anchor", require_verified=True):
            if self.required_groups.issubset(anchor.group_names):
                return anchor.group_names
        return None

    def _verified_context_unit_anchor_group_names(self) -> frozenset[str] | None:
        context_anchors = self._anchors_by_kind("context_anchor", require_verified=True)
        unit_anchors = self._anchors_by_kind("unit_anchor", require_verified=True)
        if not context_anchors or not unit_anchors:
            return None
        groups = self.anchor_group_names(
            "context_anchor",
            "unit_anchor",
            require_verified=True,
        )
        if self.required_groups.issubset(groups):
            return groups
        return None

    def _anchors_by_kind(
        self,
        kind: str,
        *,
        require_verified: bool = False,
    ) -> tuple[ReferenceAnchor, ...]:
        normalized_kind = _normalized_key(kind)
        return tuple(
            anchor
            for anchor in self.anchors
            if _normalized_key(anchor.kind) == normalized_kind
            and (not require_verified or anchor.verified)
        )


def build_executable_reference_contract(custom_json: dict[str, Any]) -> ExecutableReferenceContract:
    reference_schema = _dict_value(custom_json.get("reference_schema"))
    domain_structure = _dict_value(custom_json.get("domain_structure"))
    quality_policy = _dict_value(custom_json.get("quality_policy"))
    canonical_ref_template = _string_value(reference_schema.get("canonical_ref_template"))

    return ExecutableReferenceContract(
        schema_type=_string_value(reference_schema.get("type")),
        canonical_ref_template=canonical_ref_template,
        canonical_ref_template_valid=_template_is_valid(canonical_ref_template),
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

    template = _string_value(reference_schema.get("canonical_ref_template"))
    if template:
        template_groups = _safe_template_fields(template)
        if template_groups is not None:
            return template_groups

    for key in ("identity_fields", "required_fields"):
        groups = _string_list(reference_schema.get(key))
        if groups:
            return set(groups)

    fields = reference_schema.get("fields")
    if isinstance(fields, dict):
        return {
            str(key).strip()
            for key in fields
            if isinstance(key, str) and key.strip()
        }

    return set()


def canonical_reference_from_groups(groups: dict[str, str], template: str | None) -> str | None:
    if not template:
        return None
    try:
        rendered = template.format(**groups).strip()
    except (KeyError, IndexError, ValueError):
        return None
    return rendered or None


def metadata_has_reference_hint(metadata: dict[str, Any]) -> bool:
    custom_json = _dict_value(metadata.get("custom_json"))
    if isinstance(custom_json.get("reference_schema"), dict):
        return True
    if isinstance(custom_json.get("domain_structure"), dict):
        return True
    if isinstance(metadata.get("reference_contract"), dict):
        return True
    index_contract = _dict_value(metadata.get("index_contract"))
    return isinstance(index_contract.get("reference_contract"), dict)


def metadata_has_verified_reference_contract(metadata: dict[str, Any]) -> bool:
    for payload in _reference_contract_payloads(metadata):
        if payload.get("verified") is True and payload.get("canonical_units") is True:
            return True
    custom_json = _dict_value(metadata.get("custom_json"))
    if not _custom_json_reference_contract_verified(custom_json):
        return False
    contract = build_executable_reference_contract(custom_json)
    reference_resolution = _dict_value(custom_json.get("reference_resolution"))
    return bool(
        contract.verified
        and reference_resolution.get("enabled") is True
        and reference_resolution.get("build_canonical_units") is True
    )


def metadata_list_has_reference_hint(
    domain_metadata: list[dict[str, Any]],
) -> bool:
    return any(
        metadata_has_reference_hint(metadata)
        for metadata in domain_metadata
        if isinstance(metadata, dict)
    )


def metadata_list_has_verified_reference_contract(
    domain_metadata: list[dict[str, Any]],
) -> bool:
    return any(
        metadata_has_verified_reference_contract(metadata)
        for metadata in domain_metadata
        if isinstance(metadata, dict)
    )


def metadata_declares_reference_contract(metadata: dict[str, Any]) -> bool:
    return metadata_has_reference_hint(metadata)


def metadata_list_declares_reference_contract(
    domain_metadata: list[dict[str, Any]],
) -> bool:
    return metadata_list_has_reference_hint(domain_metadata)


def metadata_reference_contracts(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    for payload in _reference_contract_payloads(metadata):
        contracts.append({"reference_contract": payload})

    custom_json = _dict_value(metadata.get("custom_json"))
    has_verified_custom_contract = _custom_json_reference_contract_verified(custom_json)
    if isinstance(custom_json.get("reference_schema"), dict) and has_verified_custom_contract:
        executable = build_executable_reference_contract(custom_json)
        reference_resolution = _dict_value(custom_json.get("reference_resolution"))
        contracts.append(
            {
                "reference_contract": {
                    "schema_type": executable.schema_type,
                    "canonical_ref_template": executable.canonical_ref_template,
                    "required_groups": sorted(executable.required_groups),
                    "verified": executable.verified,
                    "canonical_units": reference_resolution.get(
                        "build_canonical_units"
                    )
                    is True,
                    "anchors": [
                        {
                            "kind": anchor.kind,
                            "regex": anchor.regex,
                            "verified": anchor.verified,
                        }
                        for anchor in executable.anchors
                    ],
                }
            }
        )
    return contracts


def _custom_json_reference_contract_verified(custom_json: dict[str, Any]) -> bool:
    validation = _dict_value(custom_json.get("reference_contract_validation"))
    execution = _dict_value(custom_json.get("reference_contract_execution"))
    reference_resolution = _dict_value(custom_json.get("reference_resolution"))
    return bool(
        (
            validation.get("status") == "verified"
            or (
                not validation
                and execution.get("status") == "verified"
            )
        )
        and reference_resolution.get("enabled") is True
        and reference_resolution.get("build_canonical_units") is True
    )


def metadata_list_reference_contracts(
    domain_metadata: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for metadata in domain_metadata:
        if not isinstance(metadata, dict):
            continue
        for contract in metadata_reference_contracts(metadata):
            key = str(sorted(contract.get("reference_contract", {}).items()))
            if key in seen:
                continue
            seen.add(key)
            contracts.append(contract)
    return contracts


def metadata_declared_scripts(metadata: dict[str, Any]) -> frozenset[str]:
    custom_json = _dict_value(metadata.get("custom_json"))
    contract = build_executable_reference_contract(custom_json)
    scripts: set[str] = set(contract.required_scripts)
    scripts.update(contract.optional_scripts)
    for role_scripts in contract.required_scripts_by_unit_role.values():
        scripts.update(role_scripts)
    for role_scripts in contract.optional_scripts_by_unit_role.values():
        scripts.update(role_scripts)
    value = metadata.get("script")
    if isinstance(value, str) and value.strip():
        scripts.add(value.strip().casefold())
    return frozenset(scripts)


def _reference_contract_payloads(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    direct = metadata.get("reference_contract")
    if isinstance(direct, dict):
        payloads.append(direct)
    index_contract = _dict_value(metadata.get("index_contract"))
    nested = index_contract.get("reference_contract")
    if isinstance(nested, dict):
        payloads.append(nested)
    custom_json = _dict_value(metadata.get("custom_json"))
    custom_nested = custom_json.get("reference_contract")
    if isinstance(custom_nested, dict):
        payloads.append(custom_nested)
    return payloads


def metadata_list_declared_scripts(
    domain_metadata: list[dict[str, Any]],
) -> frozenset[str]:
    scripts: set[str] = set()
    for metadata in domain_metadata:
        if isinstance(metadata, dict):
            scripts.update(metadata_declared_scripts(metadata))
    return frozenset(scripts)


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


def _safe_template_fields(template: str) -> set[str] | None:
    try:
        return _template_fields(template)
    except ValueError:
        return None


def _template_is_valid(template: str | None) -> bool:
    if template is None:
        return True
    return _safe_template_fields(template) is not None


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


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    ]


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _string_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _normalized_key(value: str) -> str:
    return value.strip().casefold()
