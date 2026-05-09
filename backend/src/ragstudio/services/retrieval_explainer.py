from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RetrievalExplain:
    query_reference: str | None
    matched_references: list[str]
    relationship_refs: dict[str, str]
    signals: list[dict[str, float | str]]

    def model_dump(self) -> dict[str, Any]:
        return {
            "query_reference": self.query_reference,
            "matched_references": self.matched_references,
            "relationship_refs": self.relationship_refs,
            "signals": self.signals,
        }


def build_retrieval_explain(
    *,
    query_reference: str | None,
    metadata: dict[str, Any],
    score_breakdown: dict[str, float],
) -> RetrievalExplain:
    reference_metadata = metadata.get("reference_metadata")
    if not isinstance(reference_metadata, dict):
        reference_metadata = {}

    references = reference_metadata.get("references")
    relationship_refs = {
        key: value
        for key, value in {
            "previous": reference_metadata.get("previous_ref"),
            "next": reference_metadata.get("next_ref"),
            "chapter": reference_metadata.get("chapter_ref"),
            "page": reference_metadata.get("page_ref"),
        }.items()
        if isinstance(value, str) and value
    }
    signals = [
        {"name": name, "value": value}
        for name, value in sorted(
            score_breakdown.items(), key=lambda item: item[1], reverse=True
        )
        if value > 0
    ]
    return RetrievalExplain(
        query_reference=query_reference,
        matched_references=[ref for ref in references or [] if isinstance(ref, str)],
        relationship_refs=relationship_refs,
        signals=signals,
    )
