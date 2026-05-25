from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_LAYOUT_RELATIONSHIPS = frozenset(
    {"same_page", "same_reference", "layout_group", "reading_order"}
)


@dataclass(frozen=True, slots=True)
class LayoutExpansionPolicy:
    relationships: frozenset[str] = DEFAULT_LAYOUT_RELATIONSHIPS
    vertical_proximity: float = 150.0
    horizontal_overlap_min: float = 0.0


def layout_policy_from_metadata(metadata: dict[str, Any]) -> LayoutExpansionPolicy:
    contract = metadata.get("layout_contract")
    if not isinstance(contract, dict) or contract.get("verified") is not True:
        return LayoutExpansionPolicy()
    relationships = {
        str(value).strip()
        for value in contract.get("relationships", [])
        if isinstance(value, str) and value.strip()
    }
    vertical_proximity = _float_value(contract.get("vertical_proximity"), default=150.0)
    horizontal_overlap_min = _float_value(contract.get("horizontal_overlap_min"), default=0.0)
    return LayoutExpansionPolicy(
        relationships=frozenset(relationships) or DEFAULT_LAYOUT_RELATIONSHIPS,
        vertical_proximity=vertical_proximity,
        horizontal_overlap_min=horizontal_overlap_min,
    )


def _float_value(value: Any, *, default: float) -> float:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return default
