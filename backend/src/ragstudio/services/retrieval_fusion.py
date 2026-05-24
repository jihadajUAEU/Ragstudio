from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any

from ragstudio.services.retrieval_evidence import (
    EvidenceCandidate,
    _hydrate_parser_warning_metadata,
    _merge_duplicate_candidate,
)
from ragstudio.services.retrieval_policy import DEFAULT_RETRIEVAL_POLICY, FusionScorePolicy

RRF_K = DEFAULT_RETRIEVAL_POLICY.fusion.rrf_k


class RetrievalFusion:
    def __init__(self, policy: FusionScorePolicy | None = None) -> None:
        self.policy = policy or DEFAULT_RETRIEVAL_POLICY.fusion

    def fuse(
        self,
        ranked_lists: list[list[EvidenceCandidate]],
        *,
        limit: int,
    ) -> list[EvidenceCandidate]:
        ranked_lists = _hydrate_ranked_lists(ranked_lists)
        by_key: dict[str, EvidenceCandidate] = {}
        scores: dict[str, float] = {}
        tools: dict[str, list[str]] = {}
        lane_ranks: dict[str, dict[str, int]] = {}

        for ranked in ranked_lists:
            for rank, candidate in enumerate(ranked, start=1):
                key = _candidate_key(candidate)
                existing = by_key.get(key)
                if existing is None:
                    by_key[key] = candidate
                else:
                    winner, loser = _duplicate_winner(existing, candidate, self.policy)
                    by_key[key] = _merge_duplicate_candidate(winner, loser)
                scores[key] = scores.get(key, 0.0) + 1.0 / (self.policy.rrf_k + rank)
                tool_list = tools.setdefault(key, [])
                if candidate.tool not in tool_list:
                    tool_list.append(candidate.tool)
                lane_ranks.setdefault(key, {}).setdefault(candidate.tool, rank)

        fused: list[EvidenceCandidate] = []
        for key, candidate in by_key.items():
            direct_boost, reason = _direct_boost(candidate, self.policy)
            score_basis = (
                candidate.final_score if candidate.final_score > 0 else candidate.base_score
            )
            reasons = [*candidate.reasons]
            if reason and reason not in reasons:
                reasons.append(reason)
            fused.append(
                replace(
                    candidate,
                    metadata={
                        **candidate.metadata,
                        "retrieval_passes": tools[key],
                        "lane_ranks": lane_ranks.get(key, {}),
                        "fusion_score_basis": {
                            "formula": "rrf",
                            "rrf_k": self.policy.rrf_k,
                            "policy_version": DEFAULT_RETRIEVAL_POLICY.policy_version,
                            "rrf_score": scores[key],
                            "candidate_score_basis": score_basis,
                            "direct_boost": direct_boost,
                        },
                    },
                    boost_score=candidate.boost_score + direct_boost,
                    final_score=scores[key] + direct_boost,
                    reasons=reasons,
                )
            )

        return sorted(
            fused,
            key=lambda candidate: (
                _direct_priority(candidate, self.policy),
                candidate.final_score,
                _lane_priority(candidate, self.policy),
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


def _hydrate_ranked_lists(
    ranked_lists: list[list[EvidenceCandidate]],
) -> list[list[EvidenceCandidate]]:
    flattened = [candidate for ranked in ranked_lists for candidate in ranked]
    hydrated = _hydrate_parser_warning_metadata(flattened)
    by_candidate_id = {candidate.candidate_id: candidate for candidate in hydrated}
    return [
        [by_candidate_id.get(candidate.candidate_id, candidate) for candidate in ranked]
        for ranked in ranked_lists
    ]


def _direct_priority(candidate: EvidenceCandidate, policy: FusionScorePolicy) -> int:
    features = _features(candidate)
    if features.get("reference_hypothesis"):
        return policy.direct_priority["reference_hypothesis"]
    if features.get("reference_exact"):
        return policy.direct_priority["reference_exact"]
    if features.get("arabic_exact"):
        return policy.direct_priority["arabic_exact"]
    if features.get("target_phrase"):
        return policy.direct_priority["target_phrase"]
    if candidate.tool in {"reference_exact", "reference"}:
        return policy.direct_priority["reference_tool"]
    if candidate.tool in {"arabic_lexical", "lexical"}:
        return policy.direct_priority["lexical_tool"]
    if candidate.tool == "pgvector":
        return policy.direct_priority["pgvector"]
    return policy.direct_priority["default"]


def _lane_priority(candidate: EvidenceCandidate, policy: FusionScorePolicy) -> int:
    if candidate.tool in {"metadata", "reference_exact"}:
        return policy.lane_priority["metadata"]
    if candidate.tool in {"arabic_lexical", "lexical"}:
        return policy.lane_priority["lexical"]
    if candidate.tool == "graph":
        return policy.lane_priority["graph"]
    if candidate.tool == "pgvector":
        return policy.lane_priority["pgvector"]
    if candidate.tool == "native":
        return policy.lane_priority["native"]
    return policy.lane_priority["default"]


def _duplicate_winner(
    first: EvidenceCandidate,
    second: EvidenceCandidate,
    policy: FusionScorePolicy,
) -> tuple[EvidenceCandidate, EvidenceCandidate]:
    first_key = (
        _direct_priority(first, policy),
        first.final_score or first.base_score,
        _lane_priority(first, policy),
        -first.tool_rank,
    )
    second_key = (
        _direct_priority(second, policy),
        second.final_score or second.base_score,
        _lane_priority(second, policy),
        -second.tool_rank,
    )
    if second_key > first_key:
        return second, first
    return first, second


def _direct_boost(
    candidate: EvidenceCandidate,
    policy: FusionScorePolicy,
) -> tuple[float, str | None]:
    features = _features(candidate)
    if features.get("reference_exact"):
        return policy.direct_boost["reference_exact"], "exact_reference_match"
    if features.get("arabic_exact"):
        return policy.direct_boost["arabic_exact"], "direct_arabic_match"
    if features.get("target_phrase"):
        return policy.direct_boost["target_phrase"], "target_phrase_match"
    return 0.0, None


def _features(candidate: EvidenceCandidate) -> dict[str, Any]:
    if candidate.match_features:
        return candidate.match_features
    value = candidate.metadata.get("match_features")
    return value if isinstance(value, dict) else {}
