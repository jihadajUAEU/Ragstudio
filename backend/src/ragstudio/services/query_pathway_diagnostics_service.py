from __future__ import annotations

from typing import Any, Literal

PathwayStatus = Literal["success", "warning", "failed", "skipped", "unknown"]


class QueryPathwayDiagnosticsService:
    def build(
        self,
        *,
        status: str,
        error: str | None,
        error_type: str | None,
        timings: dict[str, Any],
        chunk_traces: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        token_metadata: dict[str, Any],
        query_config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        context = _DiagnosticContext(
            run_status=status,
            error=error,
            error_type=error_type,
            timings=timings,
            traces=chunk_traces,
            sources=sources,
            token_metadata=token_metadata,
            query_config=query_config,
        )
        return [
            _retrieval_route_plan(context),
            _retrieval_lanes(context),
            _layout_neighbor_expansion(context),
            _context_window(context),
            _reranker(context),
            _planner(context),
            _llm_planning(context),
            _metadata_retrieval(context),
            _native_retrieval(context),
            _seed_fusion(context),
            _graph_expansion(context),
            _graph_hydration(context),
            _final_fusion(context),
            _hypothesis_verification(context),
            _context_assembly(context),
            _answer_generation(context),
            _grounding_validation(context),
        ]


class _DiagnosticContext:
    def __init__(
        self,
        *,
        run_status: str,
        error: str | None,
        error_type: str | None,
        timings: dict[str, Any],
        traces: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        token_metadata: dict[str, Any],
        query_config: dict[str, Any],
    ):
        self.run_status = run_status
        self.error = error
        self.error_type = error_type
        self.timings = timings
        self.traces = traces
        self.sources = sources
        self.token_metadata = token_metadata
        self.query_config = query_config

    def trace(self, stage: str) -> dict[str, Any] | None:
        return next((trace for trace in self.traces if trace.get("stage") == stage), None)


def _retrieval_route_plan(context: _DiagnosticContext) -> dict[str, Any]:
    trace = context.trace("retrieval_route_plan")
    output = _join_parts(
        [
            _field("domain", _text(trace, "domain_profile_id") or _text(trace, "domain_id")),
            _field("layout", _text(trace, "layout_hint")),
            _field("materialization", _text(trace, "materialization_hint")),
            _field("source", _text(trace, "source_of_truth")),
        ]
    )
    return _row(
        "retrieval_route_plan",
        "Retrieval route plan",
        "query + domain metadata + runtime profile",
        "Resolve the retrieval route across domain, layout, and context lanes",
        output or "not recorded",
        _status_from_text(_text(trace, "status") or ("success" if trace else None)),
        _number(context.timings, "route_plan_ms"),
        None,
        trace_present=trace is not None,
    )


def _retrieval_lanes(context: _DiagnosticContext) -> dict[str, Any]:
    lane_traces = _lane_traces(context)
    visible_lanes = [
        trace for trace in lane_traces if _text(trace, "lane") not in {"context_window", "reranker"}
    ]
    output = "; ".join(
        f"{_text(trace, 'lane') or 'lane'} {_text(trace, 'status') or 'unknown'}: "
        f"{int(_number(trace, 'candidate_count') or 0)} candidates"
        for trace in visible_lanes
    )
    return _row(
        "retrieval_lanes",
        "Retrieval lanes",
        "route plan + selected documents",
        "Run planned canonical, metadata, vector, runtime, and graph lanes",
        output or "no retrieval lanes recorded",
        "success" if visible_lanes else "unknown",
        _number(context.timings, "retrieval_ms"),
        None,
        trace_present=bool(visible_lanes),
    )


def _layout_neighbor_expansion(context: _DiagnosticContext) -> dict[str, Any]:
    trace = context.trace("layout_neighbor_expansion")
    layout_groups = _string_list(trace.get("layout_group_ids") if trace else None)
    reading_order = "yes" if trace and trace.get("reading_order_neighbors") is True else "no"
    output = _join_parts(
        [
            f"{int(_number(trace, 'candidate_count') or 0)} candidates" if trace else "",
            _field("layout groups", ", ".join(layout_groups) if layout_groups else None),
            _field("reading order neighbors", reading_order if trace else None),
        ]
    )
    return _row(
        "layout_neighbor_expansion",
        "Layout neighbor expansion",
        "seed evidence + source layout metadata",
        "Add same-page, same-layout-group, and reading-order neighbors",
        output or "not recorded",
        _status_from_text(_text(trace, "status") or ("success" if trace else None)),
        _number(context.timings, "layout_neighbor_ms"),
        None,
        trace_present=trace is not None,
    )


def _context_window(context: _DiagnosticContext) -> dict[str, Any]:
    trace = _lane_trace(context, "context_window")
    reasons = _reason_counts(_record(trace.get("relationship_reasons") if trace else None))
    reason_text = "; ".join(f"{key}: {value}" for key, value in reasons.items())
    output = _join_parts(
        [
            f"{int(_number(trace, 'candidate_count') or 0)} candidates" if trace else "",
            reason_text,
        ]
    )
    return _row(
        "context_window",
        "Context window",
        "direct evidence + chunk relationships",
        "Hydrate parent, sibling, previous, next, and linked context",
        output or "not recorded",
        _status_from_text(_text(trace, "status") or ("success" if trace else None)),
        _number(context.timings, "context_window_ms"),
        None,
        trace_present=trace is not None,
    )


def _reranker(context: _DiagnosticContext) -> dict[str, Any]:
    trace = _lane_trace(context, "reranker")
    rank_deltas = _record(trace.get("rank_deltas") if trace else None) or {}
    output = _join_parts(
        [
            f"{int(_number(trace, 'candidate_count') or 0)} candidates" if trace else "",
            _field("rank changes", len(rank_deltas) if trace else None),
        ]
    )
    return _row(
        "reranker",
        "Reranker",
        "fused evidence candidates",
        "Reorder evidence candidates and record rank deltas",
        output or "not recorded",
        _status_from_text(_text(trace, "status") or ("success" if trace else None)),
        _number(trace, "latency_ms") or _number(context.timings, "rerank_ms"),
        None,
        trace_present=trace is not None,
    )


def _planner(context: _DiagnosticContext) -> dict[str, Any]:
    trace = context.trace("planner")
    output = _join_parts(
        [
            _field("strategy", _text(trace, "retrieval_strategy")),
            _field("intent", _text(trace, "intent")),
            _field("limit", _number(trace, "candidate_limit")),
        ]
    )
    return _row(
        "planner",
        "Planner",
        "query + selected documents",
        "Build retrieval plan and pathway stages",
        output or "not recorded",
        _status_from_trace(trace, success_values={"valid", "ok", "recorded"}),
        _number(context.timings, "planner_ms"),
        None,
        trace_present=trace is not None,
    )


def _llm_planning(context: _DiagnosticContext) -> dict[str, Any]:
    trace = context.trace("query_hypothesis")
    target_terms = _target_terms(trace.get("target_terms") if trace else None)
    possible_references = _string_list(trace.get("possible_references") if trace else None)
    output = _join_parts(
        [
            _field("target_terms", ", ".join(target_terms) if target_terms else None),
            _field(
                "possible_references",
                ", ".join(possible_references) if possible_references else None,
            ),
        ]
    )
    return _row(
        "llm_planning",
        "LLM planning",
        "query + selected document metadata",
        "Generate target terms and possible references",
        output or "not recorded",
        _status_from_text(
            _text(trace, "status") or _text(context.timings, "query_hypothesis_status")
        ),
        _number(context.timings, "query_hypothesis_ms"),
        _int_number(context.timings, "query_hypothesis_timeout_ms"),
        trace_present=trace is not None or "query_hypothesis_ms" in context.timings,
        near_budget_suggestion="Increase planner timeout only if plans are frequently missing.",
    )


def _metadata_retrieval(context: _DiagnosticContext) -> dict[str, Any]:
    retrieval = context.trace("retrieval")
    metadata_trace = _record(retrieval.get("metadata_trace") if retrieval else None)
    passes = metadata_trace.get("passes") if metadata_trace else None
    pass_rows = passes if isinstance(passes, list) else []
    output = (
        ", ".join(
            f"{_text(item, 'name') or 'pass'}: {_number(item, 'candidate_count') or 0}"
            for item in pass_rows
            if isinstance(item, dict)
        )
        or "no metadata passes"
    )
    status: PathwayStatus = "skipped" if not pass_rows else "success"
    if context.timings.get("metadata_degraded"):
        status = "warning"
    return _row(
        "metadata_retrieval",
        "Metadata retrieval",
        "retrieval plan + selected documents",
        "Run metadata, lexical, and exact-reference passes",
        output,
        status,
        _number(context.timings, "metadata_ms"),
        None,
        trace_present=retrieval is not None or "metadata_ms" in context.timings,
    )


def _native_retrieval(context: _DiagnosticContext) -> dict[str, Any]:
    retrieval = context.trace("retrieval")
    native_status = _text(retrieval, "native_status")
    native_error = _text(context.timings, "native_error")
    candidate_count = _number(retrieval, "native_candidates")
    status = _status_from_text(native_status or ("degraded" if native_error else None))
    if context.timings.get("native_degraded"):
        status = "warning"
    output = native_error or _field("candidates", candidate_count) or "not recorded"
    return _row(
        "native_retrieval",
        "Native retrieval",
        "query + native runtime scope",
        "Search native RAG runtime",
        output,
        status,
        _number(context.timings, "native_stage_ms"),
        _int_number(context.query_config, "native_query_timeout_ms"),
        trace_present=retrieval is not None or "native_stage_ms" in context.timings,
        degraded_diagnosis="Timed out or degraded; metadata fallback used.",
        degraded_suggestion="Check native runtime latency.",
    )


def _seed_fusion(context: _DiagnosticContext) -> dict[str, Any]:
    trace = context.trace("seed_fusion")
    status = _status_from_trace(trace)
    if status == "unknown" and trace is not None:
        status = "success"
    return _row(
        "seed_fusion",
        "Seed fusion",
        "metadata and native candidates",
        "Merge initial candidates before graph expansion",
        _field("seed candidates", _number(trace, "seed_candidates")) or "not recorded",
        status,
        _number(context.timings, "initial_fusion_ms"),
        None,
        trace_present=trace is not None or "initial_fusion_ms" in context.timings,
    )


def _graph_expansion(context: _DiagnosticContext) -> dict[str, Any]:
    trace = context.trace("graph_expansion")
    disabled = context.query_config.get("graph_expansion_enabled") is False
    status = "skipped" if disabled else _status_from_text(_text(trace, "status"))
    if context.timings.get("graph_degraded"):
        status = "warning"
    return _row(
        "graph_expansion",
        "Graph expansion",
        "seed candidates",
        "Expand candidate context through graph relationships",
        _field("expanded candidates", _number(trace, "expanded_candidates"))
        or _text(trace, "reason")
        or "not recorded",
        status,
        _number(context.timings, "graph_ms"),
        None,
        trace_present=trace is not None or disabled or "graph_ms" in context.timings,
        skipped_diagnosis="Skipped by query configuration.",
        degraded_suggestion="Disable graph for fast mode if graph context is not needed.",
    )


def _graph_hydration(context: _DiagnosticContext) -> dict[str, Any]:
    trace = context.trace("graph_hydration")
    status = _status_from_text(_text(trace, "status"))
    if status == "unknown" and trace is not None:
        status = "success"
    if context.timings.get("graph_hydration_degraded"):
        status = "warning"
    return _row(
        "graph_hydration",
        "Graph hydration",
        "graph candidates",
        "Hydrate graph candidates into source chunks",
        _field("hydrated chunks", _number(trace, "unique_hydrated_chunks")) or "not recorded",
        status,
        _number(context.timings, "graph_hydration_ms"),
        None,
        trace_present=trace is not None or "graph_hydration_ms" in context.timings,
    )


def _final_fusion(context: _DiagnosticContext) -> dict[str, Any]:
    trace = context.trace("final_fusion")
    top_reference = _top_reference(context.sources)
    status = _status_from_trace(trace)
    if status == "unknown" and trace is not None:
        status = "success"
    output = _join_parts(
        [
            _field("fused candidates", _number(trace, "fused_candidates")),
            _field("top reference", top_reference),
        ]
    )
    return _row(
        "final_fusion",
        "Final fusion",
        "metadata, native, and graph candidates",
        "Score and order final evidence candidates",
        output or "not recorded",
        status,
        _number(context.timings, "final_fusion_ms"),
        None,
        trace_present=trace is not None or "final_fusion_ms" in context.timings,
    )


def _hypothesis_verification(context: _DiagnosticContext) -> dict[str, Any]:
    trace = context.trace("hypothesis_verification")
    results = trace.get("possible_reference_results") if trace else None
    result_text = _reference_results(results)
    return _row(
        "hypothesis_verification",
        "Hypothesis verification",
        "final evidence + planner hypotheses",
        "Verify possible references and target terms against evidence",
        result_text or _text(trace, "reason") or "not recorded",
        _status_from_text(_text(trace, "status")),
        None,
        None,
        trace_present=trace is not None,
    )


def _context_assembly(context: _DiagnosticContext) -> dict[str, Any]:
    trace = context.trace("context_assembly")
    status = _status_from_trace(trace)
    if status == "unknown" and trace is not None:
        status = "success"
    assembled_context = _record(trace.get("assembled_context") if trace else None) or {}
    evidence_ids = _string_list(assembled_context.get("evidence_ids"))
    output = _join_parts(
        [
            _field(
                "included",
                int(included) if (included := _number(trace, "included_candidates")) is not None else None,
            ),
            _field(
                "dropped",
                int(dropped) if (dropped := _number(trace, "dropped_candidates")) is not None else None,
            ),
            _field("evidence", ", ".join(evidence_ids) if evidence_ids else None),
            _field("grounding", _text(assembled_context, "grounding_status")),
        ]
    )
    return _row(
        "context_assembly",
        "Context assembly",
        "reranked final candidates",
        "Assemble evidence context for answer generation",
        output or "not recorded",
        status,
        _number(context.timings, "context_assembly_ms"),
        None,
        trace_present=trace is not None or "context_assembly_ms" in context.timings,
    )


def _answer_generation(context: _DiagnosticContext) -> dict[str, Any]:
    fallback_reason = _text(context.token_metadata, "fallback_reason")
    llm_status = _text(context.token_metadata, "llm_answer_status")
    output = (
        _field("fallback", fallback_reason)
        if context.timings.get("answer_fallback")
        else _field("llm_answer_status", llm_status) or "answer returned"
    )
    status = _status_from_text(llm_status)
    if context.timings.get("answer_fallback"):
        status = "warning"
    if status == "unknown" and context.run_status in {"succeeded", "success"}:
        status = "success"
    if context.run_status == "failed" and context.error:
        status = "failed"
        output = f"{context.error_type or 'error'}: {context.error}"
    return _row(
        "answer_generation",
        "Answer generation",
        "assembled evidence context",
        "Generate final answer wording or evidence-first fallback",
        output,
        status,
        _number(context.timings, "answer_ms"),
        _int_number(context.timings, "answer_timeout_ms")
        or _int_number(context.query_config, "answer_budget_ms"),
        trace_present=(
            "answer_ms" in context.timings
            or bool(context.token_metadata)
            or bool(context.error)
        ),
        degraded_diagnosis="Timed out; evidence-first answer used.",
        degraded_suggestion="Use full mode if natural LLM wording is required.",
        near_budget_suggestion="Use full mode if natural LLM wording is required.",
    )


def _grounding_validation(context: _DiagnosticContext) -> dict[str, Any]:
    trace = context.trace("grounding_validation")
    failures = trace.get("failures") if trace else None
    cited = trace.get("cited_labels") if trace else None
    failure_count = len(failures) if isinstance(failures, list) else 0
    cited_count = len(cited) if isinstance(cited, list) else 0
    output = f"{failure_count} failures" if failure_count else f"{cited_count} cited labels"
    return _row(
        "grounding_validation",
        "Grounding validation",
        "answer + final evidence",
        "Validate answer citations and expected references",
        output,
        _status_from_text(_text(trace, "status")),
        None,
        None,
        trace_present=trace is not None,
    )


def _row(
    stage: str,
    label: str,
    input_text: str,
    action: str,
    output: str,
    status: PathwayStatus,
    time_ms: float | None,
    budget_ms: int | None,
    *,
    trace_present: bool,
    skipped_diagnosis: str = "Skipped by query configuration.",
    degraded_diagnosis: str = "Stage degraded or used fallback.",
    degraded_suggestion: str = "Inspect raw pathway data.",
    near_budget_suggestion: str = "Inspect provider latency or adjust the configured budget.",
) -> dict[str, Any]:
    if not trace_present:
        status = "unknown"
    diagnosis, suggested_action = _diagnosis(
        status,
        time_ms=time_ms,
        budget_ms=budget_ms,
        skipped_diagnosis=skipped_diagnosis,
        degraded_diagnosis=degraded_diagnosis,
        degraded_suggestion=degraded_suggestion,
        near_budget_suggestion=near_budget_suggestion,
    )
    return {
        "stage": stage,
        "label": label,
        "input": input_text,
        "action": action,
        "output": output or "not recorded",
        "status": status,
        "time_ms": round(time_ms, 3) if time_ms is not None else None,
        "budget_ms": budget_ms,
        "diagnosis": diagnosis,
        "suggested_action": suggested_action,
    }


def _diagnosis(
    status: PathwayStatus,
    *,
    time_ms: float | None,
    budget_ms: int | None,
    skipped_diagnosis: str,
    degraded_diagnosis: str,
    degraded_suggestion: str,
    near_budget_suggestion: str,
) -> tuple[str, str]:
    if status == "unknown":
        return "Missing trace or timing data.", "Inspect raw pathway data."
    if status == "failed":
        return "Stage failed.", "Inspect error details and raw pathway data."
    if status == "skipped":
        return skipped_diagnosis, "None"
    if status == "warning":
        return degraded_diagnosis, degraded_suggestion
    if time_ms is not None and budget_ms is not None and budget_ms > 0:
        percent = round((time_ms / budget_ms) * 100)
        if percent >= 100:
            return (
                f"Timed out or exceeded budget. Used {percent}% of budget.",
                near_budget_suggestion,
            )
        if percent >= 80:
            return f"Near budget. Used {percent}% of budget.", near_budget_suggestion
        return f"Healthy. Used {percent}% of budget.", "None"
    return "Healthy.", "None"


def _status_from_trace(
    trace: dict[str, Any] | None,
    *,
    success_values: set[str] | None = None,
) -> PathwayStatus:
    if trace is None:
        return "unknown"
    return _status_from_text(
        _text(trace, "status") or _text(trace, "query_hypothesis_status"),
        success_values=success_values,
    )


def _status_from_text(
    value: str | None,
    *,
    success_values: set[str] | None = None,
) -> PathwayStatus:
    if value is None:
        return "unknown"
    normalized = value.strip().casefold()
    success = {"ok", "ran", "success", "succeeded", "valid", "confirmed", "grounded"}
    if success_values:
        success |= success_values
    if normalized in success:
        return "success"
    if normalized in {"timeout", "degraded", "fallback", "not_found", "warning"}:
        return "warning"
    if normalized in {"failed", "error", "rejected"}:
        return "failed"
    if normalized in {"skipped", "not_applicable", "disabled"}:
        return "skipped"
    return "unknown"


def _target_terms(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    terms: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            terms.append(item.strip())
            continue
        if isinstance(item, dict):
            surface = item.get("surface")
            if isinstance(surface, str) and surface.strip():
                terms.append(surface.strip())
    return list(dict.fromkeys(terms))


def _reference_results(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        reference = _text(item, "reference")
        status = _text(item, "status")
        if reference and status:
            parts.append(f"{reference} {status}")
    return ", ".join(parts)


def _top_reference(sources: list[dict[str, Any]]) -> str | None:
    first = sources[0] if sources else None
    if not isinstance(first, dict):
        return None
    metadata = _record(first.get("metadata")) or {}
    source_location = _record(first.get("source_location")) or {}
    return (
        _text(metadata, "canonical_reference")
        or _text(source_location, "reference")
        or _text(first, "source_location")
    )


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _field(label: str, value: Any) -> str:
    if value is None or value == "":
        return ""
    return f"{label}: {value}"


def _join_parts(parts: list[str]) -> str:
    return "; ".join(part for part in parts if part)


def _lane_traces(context: _DiagnosticContext) -> list[dict[str, Any]]:
    return [
        trace
        for trace in context.traces
        if isinstance(trace, dict) and trace.get("stage") == "retrieval_lane_result"
    ]


def _lane_trace(context: _DiagnosticContext, lane: str) -> dict[str, Any] | None:
    return next((trace for trace in _lane_traces(context) if trace.get("lane") == lane), None)


def _reason_counts(reasons: dict[str, Any] | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not reasons:
        return counts
    for reason in reasons.values():
        key = str(reason).strip()
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


def _record(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _text(record: dict[str, Any] | None, key: str) -> str | None:
    if not isinstance(record, dict):
        return None
    value = record.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _number(record: dict[str, Any] | None, key: str) -> float | None:
    if not isinstance(record, dict):
        return None
    value = record.get(key)
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, int | float) else None


def _int_number(record: dict[str, Any] | None, key: str) -> int | None:
    value = _number(record, key)
    return int(value) if value is not None else None
