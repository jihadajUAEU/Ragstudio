from __future__ import annotations

from dataclasses import field, fields, is_dataclass, make_dataclass
from typing import Any

from ragstudio.services.domain_classifier import DomainClassifier
from ragstudio.services.evidence_unit_contract import MaterializationPolicy, QualityActionPolicy
from ragstudio.services.retrieval_route_planner import RetrievalRouteRequest


class ScopeAccessViolationError(ValueError):
    pass


def build_retrieval_route_request(
    *,
    query: str,
    document_ids: list[str],
    runtime_profile_id: str | None,
    variant_id: str | None,
    query_intent: str,
    retrieval_strategy: str,
    query_understanding: Any,
    domain_metadata: list[dict[str, Any]],
    query_config: dict[str, Any],
    runtime_readiness: dict[str, object] | None = None,
    reranker_readiness: dict[str, object] | None = None,
) -> RetrievalRouteRequest:
    scope_policy = str(query_config.get("scope_policy") or "allow_profile_wide")
    scoped_document_ids = tuple(document_ids)
    if not scoped_document_ids and scope_policy == "strict_document_scope":
        raise ScopeAccessViolationError("strict document scope requires selected document_ids")

    classification = DomainClassifier().classify(domain_metadata)
    limit = _positive_int(query_config.get("limit"), default=8)
    graph_readiness = _graph_readiness(query_config)
    quality_action_policy = _quality_action_policy(domain_metadata, query_config)
    payload = {
        "query": query,
        "document_ids": scoped_document_ids,
        "scope_policy": scope_policy,
        "runtime_profile_id": runtime_profile_id,
        "variant_id": variant_id,
        "query_intent": query_intent,
        "retrieval_strategy": retrieval_strategy,
        "direct_evidence_required": bool(
            getattr(query_understanding, "direct_evidence_required", False)
        ),
        "graph_context_required": bool(
            getattr(query_understanding, "graph_context_required", False)
        ),
        "domain_id": classification.domain_profile_id,
        "layout_hint": classification.layout_hint,
        "materialization_hint": (
            _materialization_hint(query_config) or classification.materialization_hint
        ),
        "quality_action_policy": quality_action_policy,
        "materialization_policy": _materialization_policy(domain_metadata, query_config),
        "runtime_readiness": runtime_readiness or {"state": "ready"},
        "graph_readiness": graph_readiness,
        "reranker_readiness": reranker_readiness or _reranker_readiness(query_config),
        "top_k": max(limit * 2, 20),
        "response_budget_ms": _int_or_none(query_config.get("response_budget_ms")),
        "lane_time_budget_ms": _int_or_none(query_config.get("lane_time_budget_ms")),
    }
    return _build_compatible_route_request(payload)


def _build_compatible_route_request(payload: dict[str, object]) -> RetrievalRouteRequest:
    request_type = _route_request_type()
    request_fields = _dataclass_field_names(request_type)
    supported_payload = {key: value for key, value in payload.items() if key in request_fields}
    return request_type(**supported_payload)


def _route_request_type() -> type[RetrievalRouteRequest]:
    available_fields = _dataclass_field_names(RetrievalRouteRequest)
    missing_fields = [
        ("query", str, field(default="")),
        ("document_ids", tuple[str, ...], field(default=())),
        ("scope_policy", str, field(default="allow_profile_wide")),
        ("runtime_profile_id", str | None, field(default=None)),
        ("variant_id", str | None, field(default=None)),
        ("query_intent", str | None, field(default=None)),
        ("retrieval_strategy", str | None, field(default=None)),
        ("direct_evidence_required", bool, field(default=False)),
        ("graph_context_required", bool, field(default=False)),
        ("runtime_readiness", dict[str, object] | None, field(default=None)),
        ("graph_readiness", dict[str, object] | None, field(default=None)),
        ("reranker_readiness", dict[str, object] | None, field(default=None)),
        ("response_budget_ms", int | None, field(default=None)),
        ("lane_time_budget_ms", int | None, field(default=None)),
        ("scope_metadata", dict[str, object] | None, field(default=None)),
    ]
    fields_to_add = [item for item in missing_fields if item[0] not in available_fields]
    if not fields_to_add:
        return RetrievalRouteRequest
    return make_dataclass(
        "_CompatibleRetrievalRouteRequest",
        fields_to_add,
        bases=(RetrievalRouteRequest,),
        frozen=True,
        slots=True,
        module=__name__,
    )


def _dataclass_field_names(dataclass_type: type[Any]) -> set[str]:
    if not is_dataclass(dataclass_type):
        return set()
    return {item.name for item in fields(dataclass_type)}


def _materialization_hint(query_config: dict[str, Any]) -> str | None:
    retrieval_mode = str(query_config.get("retrieval_mode") or "").casefold()
    if retrieval_mode == "metadata":
        return "canonical_only"
    if query_config.get("graph_expansion_enabled") is False:
        return "vector"
    return None


def _graph_readiness(query_config: dict[str, Any]) -> dict[str, object]:
    graph_readiness = query_config.get("graph_readiness")
    if isinstance(graph_readiness, dict):
        return graph_readiness
    graph_enabled = bool(query_config.get("graph_expansion_enabled", True))
    if graph_enabled:
        return {"state": "ready"}
    return {"state": "disabled", "reason": "graph_expansion_disabled"}


def _reranker_readiness(query_config: dict[str, Any]) -> dict[str, object]:
    if query_config.get("enable_rerank") is False:
        return {"state": "disabled", "reason": "query_config_disabled"}
    return {"state": "ready"}


def _quality_action_policy(
    domain_metadata: list[dict[str, Any]],
    query_config: dict[str, Any],
) -> QualityActionPolicy:
    policies = _policy_dicts(domain_metadata, query_config, "quality_action_policy")
    baseline_gate = _baseline_gate(query_config)
    baseline_allows_vector = _baseline_allows_vector(baseline_gate)
    if not policies:
        if not baseline_allows_vector:
            return QualityActionPolicy(
                index_vector=False,
                reasons=(_baseline_vector_reason(baseline_gate),),
            )
        return QualityActionPolicy()

    action = "block" if any(policy.get("action") == "block" for policy in policies) else "allow"
    persist_chunk = all(bool(policy.get("persist_chunk", True)) for policy in policies)
    index_vector = all(bool(policy.get("index_vector", True)) for policy in policies)
    project_graph = all(bool(policy.get("project_graph", True)) for policy in policies)
    reasons = _policy_reasons(policies)
    if not baseline_allows_vector:
        index_vector = False
        reasons = (*reasons, _baseline_vector_reason(baseline_gate))
    return QualityActionPolicy(
        action=action,
        persist_chunk=persist_chunk,
        index_vector=index_vector,
        project_graph=project_graph,
        reasons=reasons,
    )


def _materialization_policy(
    domain_metadata: list[dict[str, Any]],
    query_config: dict[str, Any],
) -> MaterializationPolicy:
    policies = _policy_dicts(domain_metadata, query_config, "materialization_policy")
    if not policies:
        return MaterializationPolicy()
    allow_runtime = all(
        bool(policy.get("allow_raganything_runtime_lane", True)) for policy in policies
    )
    action = "persist_only" if not allow_runtime else "full"
    for policy in policies:
        candidate_action = policy.get("action")
        if isinstance(candidate_action, str) and candidate_action:
            action = candidate_action
            break
    source_of_truth = "postgres_canonical_evidence"
    for policy in policies:
        candidate_source = policy.get("source_of_truth")
        if isinstance(candidate_source, str) and candidate_source:
            source_of_truth = candidate_source
            break
    return MaterializationPolicy(
        action=action,
        source_of_truth=source_of_truth,
        allow_raganything_runtime_lane=allow_runtime,
        reasons=_policy_reasons(policies),
    )


def _policy_dicts(
    domain_metadata: list[dict[str, Any]],
    query_config: dict[str, Any],
    key: str,
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    configured = query_config.get(key)
    if isinstance(configured, dict):
        values.append(configured)
    for metadata in domain_metadata:
        value = metadata.get(key)
        if isinstance(value, dict):
            values.append(value)
    return values


def _policy_reasons(policies: list[dict[str, Any]]) -> tuple[str, ...]:
    reasons: list[str] = []
    for policy in policies:
        raw_reasons = policy.get("reasons")
        if isinstance(raw_reasons, list | tuple):
            for reason in raw_reasons:
                if isinstance(reason, str) and reason and reason not in reasons:
                    reasons.append(reason)
    return tuple(reasons)


def _baseline_gate(query_config: dict[str, Any]) -> object:
    if "vector_baseline_gate" in query_config:
        return query_config.get("vector_baseline_gate")
    if "retrieval_quality_gate" in query_config:
        return query_config.get("retrieval_quality_gate")
    return None


def _baseline_allows_vector(baseline_gate: object) -> bool:
    if baseline_gate is True:
        return True
    if isinstance(baseline_gate, dict):
        if baseline_gate.get("passed") is True:
            return True
        regression_flags = [
            "direct_hit_regressed",
            "mrr_regressed",
            "ndcg_regressed",
            "recall_regressed",
            "latency_budget_regressed",
        ]
        present_flags = [flag for flag in regression_flags if flag in baseline_gate]
        return bool(present_flags) and not any(
            bool(baseline_gate.get(flag)) for flag in present_flags
        )
    return False


def _baseline_vector_reason(baseline_gate: object) -> str:
    if baseline_gate is None:
        return "vector_lane_skipped_baseline_gate_missing"
    if baseline_gate is False:
        return "vector_lane_skipped_baseline_gate_failed"
    if isinstance(baseline_gate, dict):
        if any(
            bool(baseline_gate.get(flag))
            for flag in (
                "direct_hit_regressed",
                "mrr_regressed",
                "ndcg_regressed",
                "recall_regressed",
                "latency_budget_regressed",
            )
        ):
            return "vector_lane_skipped_baseline_regressed"
        return "vector_lane_skipped_baseline_gate_failed"
    return "vector_lane_skipped_baseline_gate_failed"


def _positive_int(value: object, *, default: int) -> int:
    parsed = _int_or_none(value)
    if parsed is None or parsed <= 0:
        return default
    return parsed


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
