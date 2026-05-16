from __future__ import annotations

from typing import Any

from ragstudio.services.retrieval_evidence import EvidenceCandidate


class EvidenceFirstAnswerService:
    def answer_confirmed_hypothesis(
        self,
        query: str,
        evidence: list[EvidenceCandidate],
        *,
        verification: Any,
    ) -> tuple[str, dict[str, Any]]:
        label = getattr(verification, "evidence_label", None) or "S1"
        matched_terms = getattr(verification, "matched_terms", None) or []
        matched_term = str(matched_terms[0]) if matched_terms else "the requested term"
        reference = getattr(verification, "reference", None)
        surah = getattr(verification, "surah", None)
        surah_number = getattr(verification, "surah_number", None)
        ayah = getattr(verification, "ayah", None)
        if surah and surah_number and ayah:
            answer = (
                f"The word {matched_term} is mentioned in Surah {surah}, "
                f"{surah_number}:{ayah}. [{label}]"
            )
        elif reference and (surah_reference := _surah_reference_label(reference)):
            answer = f"The word {matched_term} is mentioned in {surah_reference}. [{label}]"
        elif reference:
            answer = f"The word {matched_term} is mentioned at {reference}. [{label}]"
        else:
            answer = f"The word {matched_term} is confirmed in the retrieved evidence. [{label}]"
        return (
            answer,
            {
                "answer_mode": "confirmed_hypothesis",
                "generated_without_llm": True,
                "source_count": len(evidence),
                "confirmation_status": getattr(verification, "status", "confirmed"),
                "confirmed_reference": reference,
            },
        )

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


def _surah_reference_label(reference: str) -> str | None:
    parts = reference.split(":", maxsplit=1)
    if len(parts) != 2:
        return None
    surah, ayah = parts
    if not (surah.isdigit() and ayah.isdigit()):
        return None
    return f"Surah {int(surah)}, verse {int(ayah)}"


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
