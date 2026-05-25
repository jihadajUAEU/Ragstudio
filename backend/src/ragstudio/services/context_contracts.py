from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_CONTEXT_RELATIONSHIPS = frozenset({"reading_order", "parent", "sibling", "linked"})


@dataclass(frozen=True, slots=True)
class ContextExpansionPolicy:
    relationships: frozenset[str] = DEFAULT_CONTEXT_RELATIONSHIPS
    max_reference_distance: int = 1
    reference_unit_field: str | None = None


def context_policy_from_metadata(metadata: dict[str, Any]) -> ContextExpansionPolicy:
    contract = metadata.get("context_contract")
    if not isinstance(contract, dict) or contract.get("verified") is not True:
        return ContextExpansionPolicy()

    relationships = {
        str(value).strip()
        for value in contract.get("relationships", [])
        if isinstance(value, str) and value.strip()
    }
    distance = contract.get("max_reference_distance")
    max_reference_distance = distance if isinstance(distance, int) and distance > 0 else 1
    reference_unit_field = _string_value(
        contract.get("reference_unit_field"),
        contract.get("unit_field"),
    )
    return ContextExpansionPolicy(
        relationships=frozenset(relationships) or DEFAULT_CONTEXT_RELATIONSHIPS,
        max_reference_distance=max_reference_distance,
        reference_unit_field=reference_unit_field,
    )


def _string_value(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
