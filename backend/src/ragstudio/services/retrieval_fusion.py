from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any

from ragstudio.services.retrieval_evidence import EvidenceCandidate


class RetrievalFusion:
    def fuse(
        self,
        ranked_lists: list[list[EvidenceCandidate]],
        *,
        limit: int,
    ) -> list[EvidenceCandidate]:
        by_key: dict[str, EvidenceCandidate] = {}
        scores: dict[str, float] = {}
        tools: dict[str, list[str]] = {}

        for ranked in ranked_lists:
            for rank, candidate in enumerate(ranked, start=1):
                key = _candidate_key(candidate)
                existing = by_key.get(key)
                if existing is None or _direct_priority(candidate) > _direct_priority(existing):
                    by_key[key] = candidate
                scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank)
                tool_list = tools.setdefault(key, [])
                if candidate.tool not in tool_list:
                    tool_list.append(candidate.tool)

        fused: list[EvidenceCandidate] = []
        for key, candidate in by_key.items():
            direct_boost, reason = _direct_boost(candidate)
            score_basis = (
                candidate.final_score if candidate.final_score > 0 else candidate.base_score
            )
            reasons = [*candidate.reasons]
            if reason and reason not in reasons:
                reasons.append(reason)
            fused.append(
                replace(
                    candidate,
                    metadata={**candidate.metadata, "retrieval_passes": tools[key]},
                    boost_score=candidate.boost_score + direct_boost,
                    final_score=scores[key] + direct_boost + score_basis,
                    reasons=reasons,
                )
            )

        return sorted(
            fused,
            key=lambda candidate: (
                _direct_priority(candidate),
                candidate.final_score,
                -candidate.tool_rank,
            ),
            reverse=True,
        )[:limit]


def _candidate_key(candidate: EvidenceCandidate) -> str:
    if candidate.chunk_id:
        return f"chunk:{candidate.chunk_id}"
    runtime_source_id = candidate.metadata.get("runtime_source_id")
    if isinstance(runtime_source_id, str) and runtime_source_id:
        return f"runtime:{runtime_source_id}"
    fingerprint = hashlib.sha1(candidate.text.strip().casefold().encode("utf-8")).hexdigest()
    return f"text:{candidate.document_id or 'unknown'}:{fingerprint}"


def _direct_priority(candidate: EvidenceCandidate) -> int:
    features = _features(candidate)
    if features.get("reference_hypothesis"):
        return 5
    if features.get("reference_exact"):
        return 100
    if features.get("arabic_exact"):
        return 90
    if features.get("target_phrase"):
        return 80
    if candidate.tool in {"reference_exact", "reference"}:
        return 70
    if candidate.tool in {"arabic_lexical", "lexical"}:
        return 60
    if candidate.tool == "pgvector":
        return 20
    return 10


def _direct_boost(candidate: EvidenceCandidate) -> tuple[float, str | None]:
    features = _features(candidate)
    if features.get("reference_exact"):
        return 100.0, "exact_reference_match"
    if features.get("arabic_exact"):
        return 90.0, "direct_arabic_match"
    if features.get("target_phrase"):
        return 80.0, "target_phrase_match"
    return 0.0, None


def _features(candidate: EvidenceCandidate) -> dict[str, Any]:
    if candidate.match_features:
        return candidate.match_features
    value = candidate.metadata.get("match_features")
    return value if isinstance(value, dict) else {}
