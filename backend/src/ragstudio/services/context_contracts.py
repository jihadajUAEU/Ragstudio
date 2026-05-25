from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_CONTEXT_RELATIONSHIPS = frozenset({"reading_order", "parent", "sibling", "linked"})


@dataclass(frozen=True, slots=True)
class ContextExpansionPolicy:
    relationships: frozenset[str] = DEFAULT_CONTEXT_RELATIONSHIPS
    max_reference_distance: int = 1


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
    return ContextExpansionPolicy(
        relationships=frozenset(relationships) or DEFAULT_CONTEXT_RELATIONSHIPS,
        max_reference_distance=max_reference_distance,
    )
