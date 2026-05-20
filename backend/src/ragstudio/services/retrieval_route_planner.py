from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ragstudio.services.domain_profile_registry import (
    DomainProfile,
    DomainProfileRegistry,
    LayoutHint,
    MaterializationHint,
)
from ragstudio.services.evidence_unit_contract import MaterializationPolicy, QualityActionPolicy

RetrievalLane = Literal[
    "postgres_canonical",
    "lexical_reference",
    "vector",
    "graph",
    "raganything_runtime",
]


@dataclass(frozen=True, slots=True)
class RetrievalRouteRequest:
    domain_id: str | None = None
    layout_hint: LayoutHint | str | None = None
    materialization_hint: MaterializationHint | str | None = None
    quality_action_policy: QualityActionPolicy | None = None
    materialization_policy: MaterializationPolicy | None = None
    top_k: int | None = None


@dataclass(frozen=True, slots=True)
class RetrievalRoutePlan:
    domain_profile_id: str
    source_of_truth: str
    lanes: tuple[RetrievalLane, ...]
    top_k: int
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "domain_profile_id": self.domain_profile_id,
            "source_of_truth": self.source_of_truth,
            "lanes": list(self.lanes),
            "top_k": self.top_k,
            "reasons": list(self.reasons),
        }


class RetrievalRoutePlanner:
    def __init__(self, registry: DomainProfileRegistry | None = None) -> None:
        self.registry = registry or DomainProfileRegistry()

    def plan(self, request: RetrievalRouteRequest) -> RetrievalRoutePlan:
        profile = self.registry.resolve(
            domain_id=request.domain_id,
            layout_hint=request.layout_hint,
            materialization_hint=request.materialization_hint,
        )
        materialization_policy = request.materialization_policy or MaterializationPolicy()
        quality_policy = request.quality_action_policy or QualityActionPolicy()
        lanes: list[RetrievalLane] = ["postgres_canonical"]
        reasons = ["postgres_canonical_evidence_is_source_of_truth"]

        for lane in profile.retrieval_priority:
            normalized_lane = _normalize_lane(lane)
            if normalized_lane is None or normalized_lane in lanes:
                continue
            if normalized_lane == "vector" and not quality_policy.index_vector:
                reasons.append("vector_lane_blocked_by_quality_policy")
                continue
            if normalized_lane == "graph" and not quality_policy.project_graph:
                reasons.append("graph_lane_blocked_by_quality_policy")
                continue
            if normalized_lane == "raganything_runtime" and not _allow_runtime_lane(
                profile=profile,
                materialization_hint=request.materialization_hint,
                materialization_policy=materialization_policy,
            ):
                reasons.append("raganything_runtime_lane_blocked_by_materialization_policy")
                continue
            lanes.append(normalized_lane)

        if request.layout_hint in {"table", "figure", "equation"} and (
            materialization_policy.allow_raganything_runtime_lane
            and "raganything_runtime" not in lanes
        ):
            lanes.append("raganything_runtime")
            reasons.append("layout_hint_prefers_raganything_runtime_lane")

        top_k = request.top_k if request.top_k is not None else profile.default_top_k
        return RetrievalRoutePlan(
            domain_profile_id=profile.id,
            source_of_truth=materialization_policy.source_of_truth,
            lanes=tuple(lanes),
            top_k=top_k,
            reasons=tuple(reasons),
        )


def _normalize_lane(value: str) -> RetrievalLane | None:
    if value == "postgres_canonical":
        return "postgres_canonical"
    if value == "lexical_reference":
        return "lexical_reference"
    if value == "vector":
        return "vector"
    if value == "graph":
        return "graph"
    if value == "raganything_runtime":
        return "raganything_runtime"
    return None


def _allow_runtime_lane(
    *,
    profile: DomainProfile,
    materialization_hint: MaterializationHint | str | None,
    materialization_policy: MaterializationPolicy,
) -> bool:
    if not materialization_policy.allow_raganything_runtime_lane:
        return False
    if materialization_policy.action in {"runtime_lane", "full"}:
        return True
    if materialization_hint in {"runtime", "full"} and profile.supports_materialization(
        materialization_hint
    ):
        return True
    return False
