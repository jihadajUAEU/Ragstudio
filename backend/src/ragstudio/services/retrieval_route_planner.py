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
    "metadata",
    "vector",
    "graph",
    "raganything_runtime",
    "reranker",
]
RetrievalLaneStatus = Literal["planned", "required", "skipped", "degraded"]
RetrievalLaneResultStatus = Literal["ran", "skipped", "degraded", "failed", "timed_out"]


@dataclass(frozen=True, slots=True)
class RetrievalReadiness:
    state: str = "unknown"
    reason: str | None = None
    safe_to_run: bool = True
    checked_at: str | None = None
    scope: dict[str, object] | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "state": self.state,
            "safe_to_run": self.safe_to_run,
        }
        if self.reason:
            payload["reason"] = self.reason
        if self.checked_at:
            payload["checked_at"] = self.checked_at
        if self.scope:
            payload["scope"] = self.scope
        return payload


@dataclass(frozen=True, slots=True)
class RetrievalLanePlan:
    lane: RetrievalLane
    status: RetrievalLaneStatus
    reason: str
    candidate_limit: int
    timeout_ms: int
    document_ids: tuple[str, ...] = ()
    requires_runtime_ready: bool = False
    requires_graph_ready: bool = False
    requires_index_vector: bool = False
    requires_project_graph: bool = False
    requires_runtime_materialization: bool = False
    hydrate_to_canonical: bool = True
    critical: bool = False
    partial_timeout_policy: str = "return_degraded_candidates"
    lane_score_policy: str = "default"

    def as_dict(self) -> dict[str, object]:
        return {
            "lane": self.lane,
            "status": self.status,
            "reason": self.reason,
            "candidate_limit": self.candidate_limit,
            "timeout_ms": self.timeout_ms,
            "document_ids": list(self.document_ids),
            "requires_runtime_ready": self.requires_runtime_ready,
            "requires_graph_ready": self.requires_graph_ready,
            "requires_index_vector": self.requires_index_vector,
            "requires_project_graph": self.requires_project_graph,
            "requires_runtime_materialization": self.requires_runtime_materialization,
            "hydrate_to_canonical": self.hydrate_to_canonical,
            "critical": self.critical,
            "partial_timeout_policy": self.partial_timeout_policy,
            "lane_score_policy": self.lane_score_policy,
        }


@dataclass(frozen=True, slots=True)
class RetrievalLaneResult:
    lane: RetrievalLane
    status: RetrievalLaneResultStatus
    reason: str
    candidate_count: int
    candidate_ids: tuple[str, ...] = ()
    canonical_chunk_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    latency_ms: float = 0.0
    timed_out: bool = False
    partial: bool = False
    warning_flags: tuple[str, ...] = ()
    error_type: str | None = None
    score_basis: dict[str, object] | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "stage": "retrieval_lane_result",
            "lane": self.lane,
            "status": self.status,
            "reason": self.reason,
            "candidate_count": self.candidate_count,
            "candidate_ids": list(self.candidate_ids),
            "canonical_chunk_ids": list(self.canonical_chunk_ids),
            "document_ids": list(self.document_ids),
            "latency_ms": self.latency_ms,
            "timed_out": self.timed_out,
            "partial": self.partial,
            "warning_flags": list(self.warning_flags),
        }
        if self.error_type:
            payload["error_type"] = self.error_type
        if self.score_basis:
            payload["score_basis"] = self.score_basis
        return payload


@dataclass(frozen=True, slots=True)
class RetrievalRouteRequest:
    query: str = ""
    document_ids: tuple[str, ...] = ()
    scope_policy: str = "allow_profile_wide"
    runtime_profile_id: str | None = None
    variant_id: str | None = None
    query_intent: str | None = None
    retrieval_strategy: str | None = None
    direct_evidence_required: bool = False
    graph_context_required: bool = False
    domain_id: str | None = None
    layout_hint: LayoutHint | str | None = None
    materialization_hint: MaterializationHint | str | None = None
    quality_action_policy: QualityActionPolicy | None = None
    materialization_policy: MaterializationPolicy | None = None
    runtime_readiness: RetrievalReadiness | dict[str, object] | None = None
    graph_readiness: RetrievalReadiness | dict[str, object] | None = None
    reranker_readiness: RetrievalReadiness | dict[str, object] | None = None
    top_k: int | None = None
    response_budget_ms: int | None = None
    lane_time_budget_ms: int | None = None


@dataclass(frozen=True, slots=True)
class RetrievalRoutePlan:
    route_plan_version: str
    domain_profile_id: str
    source_of_truth: str
    lanes: tuple[RetrievalLanePlan, ...]
    candidate_limit: int
    response_budget_ms: int | None
    lane_time_budget_ms: int
    readiness: dict[str, dict[str, object]]
    reasons: tuple[str, ...]

    @property
    def top_k(self) -> int:
        return self.candidate_limit

    def lane_for(self, lane: RetrievalLane) -> RetrievalLanePlan:
        for lane_plan in self.lanes:
            if lane_plan.lane == lane:
                return lane_plan
        raise KeyError(f"Route plan has no lane: {lane}")

    def planned_lanes(self) -> tuple[RetrievalLane, ...]:
        return tuple(lane.lane for lane in self.lanes if lane.status in {"planned", "required"})

    def as_dict(self) -> dict[str, object]:
        return {
            "route_plan_version": self.route_plan_version,
            "domain_profile_id": self.domain_profile_id,
            "source_of_truth": self.source_of_truth,
            "lanes": [lane.as_dict() for lane in self.lanes],
            "planned_lanes": list(self.planned_lanes()),
            "candidate_limit": self.candidate_limit,
            "top_k": self.candidate_limit,
            "response_budget_ms": self.response_budget_ms,
            "lane_time_budget_ms": self.lane_time_budget_ms,
            "readiness": self.readiness,
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
        candidate_limit = request.top_k if request.top_k is not None else profile.default_top_k
        lane_timeout = request.lane_time_budget_ms or _lane_timeout_ms(request.response_budget_ms)
        runtime_readiness = _readiness(request.runtime_readiness)
        graph_readiness = _readiness(request.graph_readiness)
        reranker_readiness = _readiness(request.reranker_readiness)
        lane_plans: list[RetrievalLanePlan] = []
        reasons = ["postgres_canonical_evidence_is_source_of_truth"]

        for lane in _lane_order(profile):
            lane_plan, lane_reasons = _build_lane_plan(
                lane=lane,
                profile=profile,
                request=request,
                candidate_limit=candidate_limit,
                timeout_ms=lane_timeout,
                runtime_readiness=runtime_readiness,
                graph_readiness=graph_readiness,
                reranker_readiness=reranker_readiness,
            )
            lane_plans.append(lane_plan)
            reasons.extend(lane_reasons)

        return RetrievalRoutePlan(
            route_plan_version="2026-05-21",
            domain_profile_id=profile.id,
            source_of_truth=materialization_policy.source_of_truth,
            lanes=tuple(lane_plans),
            candidate_limit=candidate_limit,
            response_budget_ms=request.response_budget_ms,
            lane_time_budget_ms=lane_timeout,
            readiness={
                "runtime": runtime_readiness.as_dict(),
                "graph": graph_readiness.as_dict(),
                "reranker": reranker_readiness.as_dict(),
            },
            reasons=tuple(dict.fromkeys(reasons)),
        )


def _normalize_lane(value: str) -> RetrievalLane | None:
    if value == "postgres_canonical":
        return "postgres_canonical"
    if value == "lexical_reference":
        return "lexical_reference"
    if value == "metadata":
        return "metadata"
    if value == "vector":
        return "vector"
    if value == "graph":
        return "graph"
    if value == "raganything_runtime":
        return "raganything_runtime"
    if value == "reranker":
        return "reranker"
    return None


def _lane_order(profile: DomainProfile) -> tuple[RetrievalLane, ...]:
    lanes: list[RetrievalLane] = ["postgres_canonical"]
    for lane in profile.retrieval_priority:
        normalized = _normalize_lane(lane)
        if normalized and normalized not in lanes:
            lanes.append(normalized)
    if "metadata" not in lanes:
        insert_at = 2 if "lexical_reference" in lanes else 1
        lanes.insert(insert_at, "metadata")
    if "reranker" not in lanes:
        lanes.append("reranker")
    return tuple(lanes)


def _readiness(value: RetrievalReadiness | dict[str, object] | None) -> RetrievalReadiness:
    if isinstance(value, RetrievalReadiness):
        return value
    if isinstance(value, dict):
        state = str(value.get("state") or "unknown")
        return RetrievalReadiness(
            state=state,
            reason=str(value.get("reason")) if value.get("reason") else None,
            safe_to_run=bool(value.get("safe_to_run", state not in {"disabled", "unavailable"})),
            checked_at=str(value.get("checked_at")) if value.get("checked_at") else None,
            scope=value.get("scope") if isinstance(value.get("scope"), dict) else None,
        )
    return RetrievalReadiness()


def _lane_timeout_ms(response_budget_ms: int | None) -> int:
    if response_budget_ms is None:
        return 8000
    return max(250, min(int(response_budget_ms * 0.35), 8000))


def _build_lane_plan(
    *,
    lane: RetrievalLane,
    profile: DomainProfile,
    request: RetrievalRouteRequest,
    candidate_limit: int,
    timeout_ms: int,
    runtime_readiness: RetrievalReadiness,
    graph_readiness: RetrievalReadiness,
    reranker_readiness: RetrievalReadiness,
) -> tuple[RetrievalLanePlan, list[str]]:
    quality_policy = request.quality_action_policy or QualityActionPolicy()
    materialization_policy = request.materialization_policy or MaterializationPolicy()
    reasons: list[str] = []
    status: RetrievalLaneStatus = "planned"
    reason = "planned_by_route"

    if lane == "postgres_canonical":
        status = "required"
        reason = "canonical_source_of_truth"
    elif lane == "lexical_reference":
        reason = "reference_anchored_lexical_retrieval"
    elif lane == "metadata":
        reason = "canonical_metadata_retrieval"
    elif lane == "vector" and not quality_policy.index_vector:
        status = "skipped"
        reason = "vector_lane_blocked_by_quality_policy"
    elif lane == "graph":
        if not quality_policy.project_graph:
            status = "skipped"
            reason = "graph_lane_blocked_by_quality_policy"
        elif graph_readiness.state == "stale":
            status = "skipped"
            reason = "graph_projection_stale"
        elif (
            graph_readiness.state in {"disabled", "unavailable"}
            or not graph_readiness.safe_to_run
        ):
            status = "skipped"
            reason = graph_readiness.reason or "graph_unavailable"
    elif lane == "raganything_runtime":
        if (
            runtime_readiness.state in {"disabled", "unavailable"}
            or not runtime_readiness.safe_to_run
        ):
            status = "skipped"
            reason = "runtime_unavailable"
        elif not _allow_runtime_lane(
            profile=profile,
            materialization_hint=request.materialization_hint,
            materialization_policy=materialization_policy,
        ):
            status = "skipped"
            reason = "raganything_runtime_lane_blocked_by_materialization_policy"
    elif lane == "reranker":
        if reranker_readiness.state == "disabled":
            status = "skipped"
            reason = "reranker_disabled"
        elif reranker_readiness.state == "unavailable" or not reranker_readiness.safe_to_run:
            status = "skipped"
            reason = "reranker_unavailable"

    if status == "skipped":
        reasons.append(reason)

    return (
        RetrievalLanePlan(
            lane=lane,
            status=status,
            reason=reason,
            candidate_limit=candidate_limit,
            timeout_ms=timeout_ms,
            document_ids=tuple(request.document_ids),
            requires_runtime_ready=lane == "raganything_runtime",
            requires_graph_ready=lane == "graph",
            requires_index_vector=lane == "vector",
            requires_project_graph=lane == "graph",
            requires_runtime_materialization=lane == "raganything_runtime",
            hydrate_to_canonical=lane
            in {"lexical_reference", "metadata", "vector", "graph", "raganything_runtime"},
            critical=lane == "postgres_canonical",
            partial_timeout_policy=(
                "fail_query" if lane == "postgres_canonical" else "return_degraded_candidates"
            ),
            lane_score_policy=_lane_score_policy(lane),
        ),
        reasons,
    )


def _lane_score_policy(lane: RetrievalLane) -> str:
    if lane == "lexical_reference":
        return "direct_evidence_first"
    if lane == "metadata":
        return "metadata_filter_score"
    if lane == "graph":
        return "seed_expansion"
    if lane == "reranker":
        return "rank_delta"
    return "default"


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
