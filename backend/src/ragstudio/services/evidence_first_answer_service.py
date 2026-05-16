from __future__ import annotations

from typing import Any

from ragstudio.services.retrieval_evidence import EvidenceCandidate


class EvidenceFirstAnswerService:
    def answer(
        self,
        query: str,
        evidence: list[EvidenceCandidate],
        *,
        reason: str,
        llm_timeout_ms: int | None,
    ) -> tuple[str, dict[str, Any]]:
        if not evidence:
            return (
                "Evidence-first result\n\nNo grounded evidence was available for this query.",
                {
                    "answer_mode": "evidence_first",
                    "generated_without_llm": True,
                    "source_count": 0,
                    "fallback_reason": reason,
                    "llm_timeout_ms": llm_timeout_ms,
                },
            )

        lines = [
            "Evidence-first result",
            "",
            f"Question: {query.strip()}",
            "",
            "Grounded evidence:",
        ]
        for index, candidate in enumerate(evidence[:5], start=1):
            label = f"S{index}"
            reference = _reference_label(candidate)
            relationship = _relationship_label(candidate.metadata)
            snippet = _compact_text(candidate.text, limit=520)
            header_parts = [f"[{label}]", reference]
            if relationship:
                header_parts.append(relationship)
            lines.append(f"{' '.join(part for part in header_parts if part)}\n{snippet}")

        lines.extend(
            [
                "",
                "The LLM wording did not finish within the fast response budget, "
                "so this result is assembled directly from the retrieved evidence.",
            ]
        )
        return (
            "\n\n".join(lines),
            {
                "answer_mode": "evidence_first",
                "generated_without_llm": True,
                "source_count": len(evidence),
                "fallback_reason": reason,
                "llm_timeout_ms": llm_timeout_ms,
            },
        )


def _reference_label(candidate: EvidenceCandidate) -> str:
    reference = candidate.canonical_reference
    if not reference:
        raw_reference = candidate.source_location.get("reference")
        reference = raw_reference if isinstance(raw_reference, str) else None
    if reference:
        return f"reference={reference}"
    if candidate.chunk_id:
        return f"chunk={candidate.chunk_id}"
    return "chunk=unknown"


def _relationship_label(metadata: dict[str, Any]) -> str:
    relationship = metadata.get("graph_relationship")
    if not isinstance(relationship, dict):
        return ""
    relationship_type = relationship.get("type")
    path = relationship.get("path")
    parts = []
    if isinstance(relationship_type, str) and relationship_type:
        parts.append(f"graph={relationship_type}")
    if isinstance(path, str) and path:
        parts.append(f"path={path}")
    return " ".join(parts)


def _compact_text(text: str, *, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1].rstrip()}..."
