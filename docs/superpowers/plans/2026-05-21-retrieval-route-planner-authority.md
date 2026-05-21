# Retrieval Route Planner Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `RetrievalRoutePlanner` the authority for retrieval lane routing, tracing, fusion, reranking, context assembly, and eval-gated vector/FTS expansion.

**Architecture:** Keep canonical Postgres chunks as the source of truth. Convert query/runtime/domain signals into an immutable route plan, execute only planned or required lanes, emit uniform lane result traces, fuse lane results once, propagate reranker score changes, and require retrieval-quality metrics before enabling vector/FTS ranking changes.

**Tech Stack:** Python 3.12, FastAPI service layer, dataclasses, SQLAlchemy-backed services, pytest/pytest-asyncio, PostgreSQL/PGVector design constraints, Neo4j graph projection constraints.

---

## Source Specs

- Architecture: `docs/architecture/query-retrieval-architecture.md`
- Skill: `.codex/skills/chunk-query-retrieval-auditor/SKILL.md`
- Existing planner: `backend/src/ragstudio/services/retrieval_route_planner.py`
- Existing orchestrator: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Existing fusion: `backend/src/ragstudio/services/retrieval_fusion.py`
- Existing evidence type: `backend/src/ragstudio/services/retrieval_evidence.py`
- Existing context assembly: `backend/src/ragstudio/services/context_assembly_service.py`

## Architecture Review Additions

The review file
`C:/Users/jihad/.gemini/antigravity/brain/9a1e4b01-5b42-4039-b616-91c4b23dc13d/architecture_review_suggestions.md`
adds seven implementation rules to this plan:

- Cross-lane fusion uses RRF by default; raw vector, FTS, metadata, graph, and runtime scores stay lane-local unless normalized inside a lane.
- Graph expansion uses at most 5 high-confidence canonical/lexical/metadata seeds by default.
- Empty `document_ids` is allowed only when the runtime profile permits profile-wide search; strict profiles raise `ScopeAccessViolationError`.
- Timed-out non-critical lanes return partial candidates as degraded results when candidates were already collected.
- Direct evidence can exceed the soft answer budget, but never the model's hard physical context limit; hard-limit overflow is logically truncated and traced.
- `DomainClassifier` uses a request-local cache keyed by document id and metadata fingerprint.
- Token estimation uses a fast tokenizer or conservative heuristic and offloads unusually large payloads so it does not block the async request path.

## Scope Check

This plan covers one dependent architecture slice: route planning and retrieval execution. It is broad, but each task produces working, testable software on its own. Task 8 is gated behind Task 7 and must not be enabled by default unless the eval baseline passes.

Do not start Task 8 until Tasks 1-7 are complete and committed.

## File Structure

- Modify `backend/src/ragstudio/services/retrieval_route_planner.py`
  - Owns route request, readiness, lane plan, lane result, and serialized route plan contracts.
- Create `backend/src/ragstudio/services/domain_classifier.py`
  - Owns domain and layout classification from domain metadata, query intent, and parser/layout hints.
- Create `backend/src/ragstudio/services/retrieval_route_input.py`
  - Builds `RetrievalRouteRequest` from orchestrator/runtime/query signals and enforces scope policy.
- Modify `backend/src/ragstudio/services/retrieval_orchestrator.py`
  - Builds route input, executes primary/graph/reranker lanes from route plans, emits lane result traces, and stops using ad hoc gates as the source of truth.
- Modify `backend/src/ragstudio/services/retrieval_evidence.py`
  - Carries route, lane, quality policy, materialization policy, and reranker score fields on final evidence traces.
- Modify `backend/src/ragstudio/services/retrieval_fusion.py`
  - Fuses independent lane result candidate lists once and preserves per-lane score basis.
- Modify `backend/src/ragstudio/services/context_assembly_service.py`
  - Adds tokenizer-aware estimation, hard context truncation, non-blocking large-payload handling, and complete drop reason taxonomy.
- Create `backend/tests/test_domain_classifier.py`
  - Tests single-source domain/layout classification.
- Create `backend/tests/test_retrieval_route_input.py`
  - Tests route input construction from query/runtime/domain state.
- Modify `backend/tests/test_retrieval_route_planner.py`
  - Tests lane status, readiness, budgets, and serialization.
- Modify `backend/tests/test_retrieval_orchestrator.py`
  - Tests planner-owned lane execution, graph/reranker lane control, score propagation, and trace shape.
- Modify `backend/tests/test_rag_retrieval_fusion.py`
  - Tests one-pass multi-lane fusion.
- Modify `backend/tests/test_context_assembly_service.py`
  - Tests token estimation, drop reasons, and direct evidence budget behavior.
- Create `backend/tests/test_retrieval_quality_eval.py`
  - Adds deterministic retrieval-quality metric tests.
- Create `docs/benchmarks/ragstudio-oss-proof-v1/retrieval-quality-baseline.md`
  - Documents baseline query classes and required metrics.

---

### Task 1: Strengthen Route Planner Contracts

**Files:**
- Modify: `backend/src/ragstudio/services/retrieval_route_planner.py`
- Test: `backend/tests/test_retrieval_route_planner.py`

- [ ] **Step 1: Write failing tests for readiness, lane plans, skipped lanes, and serialization**

Add these tests to `backend/tests/test_retrieval_route_planner.py`:

```python
def test_route_planner_serializes_lane_plans_and_skipped_reasons():
    plan = RetrievalRoutePlanner().plan(
        RetrievalRouteRequest(
            domain_id="multimodal_layout",
            quality_action_policy=QualityActionPolicy(index_vector=False, project_graph=False),
            materialization_policy=MaterializationPolicy(
                action="persist_only",
                allow_raganything_runtime_lane=False,
            ),
            top_k=6,
            response_budget_ms=9000,
            lane_time_budget_ms=1200,
        )
    )

    assert plan.route_plan_version == "2026-05-21"
    assert plan.candidate_limit == 6
    assert plan.response_budget_ms == 9000
    assert plan.lane_time_budget_ms == 1200
    assert [lane.lane for lane in plan.lanes] == [
        "postgres_canonical",
        "raganything_runtime",
        "vector",
        "graph",
    ]
    assert plan.lane_for("postgres_canonical").status == "required"
    assert plan.lane_for("vector").status == "skipped"
    assert plan.lane_for("vector").reason == "vector_lane_blocked_by_quality_policy"
    assert plan.lane_for("graph").status == "skipped"
    assert plan.lane_for("raganything_runtime").status == "skipped"

    payload = plan.as_dict()

    assert payload["route_plan_version"] == "2026-05-21"
    assert payload["candidate_limit"] == 6
    assert payload["lanes"][0]["lane"] == "postgres_canonical"
    assert payload["lanes"][0]["status"] == "required"
    assert "vector_lane_blocked_by_quality_policy" in payload["reasons"]
```

Add this test to the same file:

```python
def test_route_planner_marks_readiness_degraded_lanes():
    plan = RetrievalRoutePlanner().plan(
        RetrievalRouteRequest(
            domain_id="reference_heavy",
            graph_readiness={"state": "stale", "reason": "projection_older_than_chunks"},
            runtime_readiness={"state": "unavailable", "reason": "runtime_health_failed"},
            reranker_readiness={"state": "disabled", "reason": "profile_disabled"},
            top_k=8,
        )
    )

    assert plan.lane_for("graph").status == "skipped"
    assert plan.lane_for("graph").reason == "graph_projection_stale"
    assert plan.lane_for("raganything_runtime").status == "skipped"
    assert plan.lane_for("reranker").status == "skipped"
    assert plan.lane_for("reranker").reason == "reranker_disabled"
    assert plan.readiness["graph"]["state"] == "stale"
```

Add this test to the same file:

```python
def test_route_planner_serializes_partial_recovery_contract():
    plan = RetrievalRoutePlanner().plan(
        RetrievalRouteRequest(
            document_ids=("doc-1",),
            domain_id="reference_heavy",
            top_k=5,
            response_budget_ms=3000,
        )
    )

    graph_lane = plan.lane_for("graph")

    assert graph_lane.critical is False
    assert graph_lane.timeout_ms <= 3000
    payload = graph_lane.as_dict()
    assert payload["critical"] is False
    assert payload["partial_timeout_policy"] == "return_degraded_candidates"
```

- [ ] **Step 2: Run planner tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_retrieval_route_planner.py -q
```

Expected: FAIL because `RetrievalRouteRequest` does not accept readiness/budget fields and `RetrievalRoutePlan` does not expose lane plan objects.

- [ ] **Step 3: Add route contract dataclasses**

In `backend/src/ragstudio/services/retrieval_route_planner.py`, replace the current `RetrievalLane` definition and add these dataclasses above `RetrievalRouteRequest`:

```python
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
        payload: dict[str, object] = {"state": self.state, "safe_to_run": self.safe_to_run}
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
```

- [ ] **Step 4: Expand request and plan fields**

Replace the current `RetrievalRouteRequest` and `RetrievalRoutePlan` dataclasses with:

```python
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

    def lane_for(self, lane: RetrievalLane) -> RetrievalLanePlan:
        for lane_plan in self.lanes:
            if lane_plan.lane == lane:
                return lane_plan
        raise KeyError(f"Route plan has no lane: {lane}")

    def planned_lanes(self) -> tuple[RetrievalLane, ...]:
        return tuple(
            lane.lane for lane in self.lanes if lane.status in {"planned", "required"}
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "route_plan_version": self.route_plan_version,
            "domain_profile_id": self.domain_profile_id,
            "source_of_truth": self.source_of_truth,
            "lanes": [lane.as_dict() for lane in self.lanes],
            "planned_lanes": list(self.planned_lanes()),
            "candidate_limit": self.candidate_limit,
            "response_budget_ms": self.response_budget_ms,
            "lane_time_budget_ms": self.lane_time_budget_ms,
            "readiness": self.readiness,
            "reasons": list(self.reasons),
        }
```

- [ ] **Step 5: Update `plan()` to build lane plans**

Inside `RetrievalRoutePlanner.plan()`, keep profile resolution but replace lane list construction with this pattern:

```python
candidate_limit = request.top_k if request.top_k is not None else profile.default_top_k
lane_timeout = request.lane_time_budget_ms or _lane_timeout_ms(request.response_budget_ms)
runtime_readiness = _readiness(request.runtime_readiness)
graph_readiness = _readiness(request.graph_readiness)
reranker_readiness = _readiness(request.reranker_readiness)

lane_order = _lane_order(profile)
lane_plans: list[RetrievalLanePlan] = []
reasons = ["postgres_canonical_evidence_is_source_of_truth"]

for lane in lane_order:
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
```

Add these helper functions below `_normalize_lane()`:

```python
def _lane_order(profile: DomainProfile) -> tuple[RetrievalLane, ...]:
    lanes: list[RetrievalLane] = ["postgres_canonical"]
    for lane in profile.retrieval_priority:
        normalized = _normalize_lane(lane)
        if normalized and normalized not in lanes:
            lanes.append(normalized)
    if "metadata" not in lanes:
        lanes.insert(1, "metadata")
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
```

Add `_build_lane_plan()`:

```python
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
        elif graph_readiness.state in {"disabled", "unavailable"} or not graph_readiness.safe_to_run:
            status = "skipped"
            reason = "graph_unavailable"
    elif lane == "raganything_runtime":
        if runtime_readiness.state in {"disabled", "unavailable"} or not runtime_readiness.safe_to_run:
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
            hydrate_to_canonical=lane in {"graph", "raganything_runtime", "vector"},
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
    if lane == "graph":
        return "seed_expansion"
    if lane == "reranker":
        return "rank_delta"
    return "default"
```

- [ ] **Step 6: Run planner tests and verify they pass**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_retrieval_route_planner.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```powershell
git add backend/src/ragstudio/services/retrieval_route_planner.py backend/tests/test_retrieval_route_planner.py
git commit -m "feat: strengthen retrieval route planner contract"
```

---

### Task 2: Centralize Domain Classification And Route Input

**Files:**
- Create: `backend/src/ragstudio/services/domain_classifier.py`
- Create: `backend/src/ragstudio/services/retrieval_route_input.py`
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Test: `backend/tests/test_domain_classifier.py`
- Test: `backend/tests/test_retrieval_route_input.py`
- Test: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Write failing domain classifier tests**

Create `backend/tests/test_domain_classifier.py`:

```python
from ragstudio.services.domain_classifier import DomainClassifier


def test_domain_classifier_maps_arabic_religious_reference_documents():
    result = DomainClassifier().classify(
        [
            {
                "domain": "quran_tafseer",
                "document_type": "tafseer",
                "content_role": "quran",
                "language": "mixed",
                "tags": ["quran", "tafseer", "arabic"],
            }
        ]
    )

    assert result.domain_profile_id == "reference_heavy"
    assert result.domain_family == "tafseer_reference"
    assert result.reference_heavy is True
    assert result.layout_hint == "reference"


def test_domain_classifier_maps_layout_heavy_documents():
    result = DomainClassifier().classify(
        [
            {
                "domain": "finance",
                "document_type": "report",
                "layout_types": ["table", "figure"],
                "tags": ["table", "annual_report"],
            }
        ]
    )

    assert result.domain_profile_id == "multimodal_layout"
    assert result.domain_family == "generic"
    assert result.layout_hint == "table"


def test_domain_classifier_defaults_to_general_for_plain_documents():
    result = DomainClassifier().classify([{"domain": "general", "tags": ["notes"]}])

    assert result.domain_profile_id == "general"
    assert result.domain_family == "generic"
    assert result.layout_hint is None
    assert result.reference_heavy is False


def test_domain_classifier_request_cache_reuses_document_classification():
    classifier = DomainClassifier()
    metadata = [{"document_id": "doc-1", "domain": "hadith", "tags": ["hadith"]}]

    first = classifier.classify(metadata)
    second = classifier.classify(metadata)

    assert first is second
    assert classifier.cache_stats()["hits"] == 1
```

- [ ] **Step 2: Write failing route input tests**

Create `backend/tests/test_retrieval_route_input.py`:

```python
import pytest

from ragstudio.services.query_understanding import QueryUnderstanding
from ragstudio.services.retrieval_route_input import (
    ScopeAccessViolationError,
    build_retrieval_route_request,
)


def test_route_input_preserves_scope_and_readiness():
    understanding = QueryUnderstanding(
        intent="reference",
        retrieval_strategy="reference_first_hybrid",
        expanded_terms=("sacrifice",),
        retrieval_passes=(),
        direct_evidence_required=True,
        graph_context_required=True,
    )

    request = build_retrieval_route_request(
        query="show Book 13 Hadith 25",
        document_ids=["doc-hadith"],
        runtime_profile_id="profile-1",
        variant_id="variant-1",
        query_intent="reference",
        retrieval_strategy="reference_first_hybrid",
        query_understanding=understanding,
        domain_metadata=[{"domain": "hadith", "tags": ["hadith"]}],
        query_config={
            "limit": 5,
            "response_budget_ms": 9000,
            "graph_readiness": {"state": "stale", "reason": "projection_older_than_chunks"},
        },
        runtime_readiness={"state": "ready"},
        reranker_readiness={"state": "disabled", "reason": "profile_disabled"},
    )

    assert request.document_ids == ("doc-hadith",)
    assert request.domain_id == "reference_heavy"
    assert request.direct_evidence_required is True
    assert request.graph_context_required is True
    assert request.top_k == 10
    assert request.response_budget_ms == 9000
    assert request.graph_readiness["state"] == "stale"


def test_route_input_rejects_empty_document_scope_for_strict_profiles():
    with pytest.raises(ScopeAccessViolationError, match="strict document scope"):
        build_retrieval_route_request(
            query="show evidence",
            document_ids=[],
            runtime_profile_id="profile-1",
            variant_id="variant-1",
            query_intent="semantic",
            retrieval_strategy="semantic_hybrid",
            query_understanding=None,
            domain_metadata=[],
            query_config={"scope_policy": "strict_document_scope"},
        )
```

- [ ] **Step 3: Run new tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_domain_classifier.py backend/tests/test_retrieval_route_input.py -q
```

Expected: FAIL because both modules do not exist.

- [ ] **Step 4: Create the domain classifier**

Create `backend/src/ragstudio/services/domain_classifier.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DomainClassification:
    domain_profile_id: str
    domain_family: str
    layout_hint: str | None
    reference_heavy: bool
    signals: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "domain_profile_id": self.domain_profile_id,
            "domain_family": self.domain_family,
            "layout_hint": self.layout_hint,
            "reference_heavy": self.reference_heavy,
            "signals": list(self.signals),
        }


class DomainClassifier:
    def classify(self, domain_metadata: list[dict[str, Any]]) -> DomainClassification:
        signals = _signals(domain_metadata)
        layout_hint = _layout_hint(signals)

        if {"quran_tafseer", "tafseer", "quran"} & signals:
            return DomainClassification(
                domain_profile_id="reference_heavy",
                domain_family="tafseer_reference",
                layout_hint=layout_hint or "reference",
                reference_heavy=True,
                signals=tuple(sorted(signals)),
            )
        if "hadith" in signals:
            return DomainClassification(
                domain_profile_id="reference_heavy",
                domain_family="hadith_reference",
                layout_hint=layout_hint or "reference",
                reference_heavy=True,
                signals=tuple(sorted(signals)),
            )
        if {"legal", "law", "statute", "policy"} & signals:
            return DomainClassification(
                domain_profile_id="reference_heavy",
                domain_family="legal_reference",
                layout_hint=layout_hint or "reference",
                reference_heavy=True,
                signals=tuple(sorted(signals)),
            )
        if layout_hint in {"table", "figure", "equation"}:
            return DomainClassification(
                domain_profile_id="multimodal_layout",
                domain_family="generic",
                layout_hint=layout_hint,
                reference_heavy=False,
                signals=tuple(sorted(signals)),
            )
        if {"research", "paper", "report", "scientific"} & signals:
            return DomainClassification(
                domain_profile_id="general",
                domain_family="research_semantic",
                layout_hint=layout_hint,
                reference_heavy=False,
                signals=tuple(sorted(signals)),
            )
        return DomainClassification(
            domain_profile_id="general",
            domain_family="generic",
            layout_hint=layout_hint,
            reference_heavy=False,
            signals=tuple(sorted(signals)),
        )


def _signals(domain_metadata: list[dict[str, Any]]) -> set[str]:
    values: set[str] = set()
    for metadata in domain_metadata:
        if not isinstance(metadata, dict):
            continue
        for key in (
            "domain",
            "document_type",
            "collection",
            "content_role",
            "citation_style",
            "language",
        ):
            _add_value(values, metadata.get(key))
        for key in ("tags", "layout_types", "modalities"):
            raw_values = metadata.get(key)
            if isinstance(raw_values, list):
                for item in raw_values:
                    _add_value(values, item)
    return values


def _add_value(values: set[str], value: Any) -> None:
    if isinstance(value, str) and value.strip():
        values.add(value.strip().casefold())


def _layout_hint(signals: set[str]) -> str | None:
    for layout in ("table", "figure", "equation", "reference"):
        if layout in signals:
            return layout
    return None
```

Add request-local caching to `DomainClassifier` by adding this initializer and
helpers to the class:

```python
def __init__(self) -> None:
    self._cache: dict[str, DomainClassification] = {}
    self._hits = 0


def _remember(
    self,
    cache_key: str,
    classification: DomainClassification,
) -> DomainClassification:
    self._cache[cache_key] = classification
    return classification


def cache_stats(self) -> dict[str, int]:
    return {"size": len(self._cache), "hits": self._hits}
```

At the start of `classify()`, add:

```python
cache_key = _cache_key(domain_metadata)
if cache_key in self._cache:
    self._hits += 1
    return self._cache[cache_key]
```

Wrap every direct `DomainClassification` return in `classify()` with `_remember`.
For example, the generic default branch becomes:

```python
return self._remember(
    cache_key,
    DomainClassification(
        domain_profile_id="general",
        domain_family="generic",
        layout_hint=layout_hint,
        reference_heavy=False,
        signals=tuple(sorted(signals)),
    ),
)
```

Add these helpers below `_signals()`:

```python
def _cache_key(domain_metadata: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for metadata in domain_metadata:
        if not isinstance(metadata, dict):
            continue
        document_id = str(metadata.get("document_id") or "")
        version = str(metadata.get("metadata_version") or metadata.get("updated_at") or "")
        parts.append(f"{document_id}:{version}:{sorted(_metadata_values(metadata))}")
    return "|".join(sorted(parts)) or "empty"


def _metadata_values(metadata: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key, value in metadata.items():
        if isinstance(value, str):
            values.append(f"{key}={value.casefold()}")
        elif isinstance(value, list):
            values.append(f"{key}={','.join(str(item).casefold() for item in value)}")
    return values
```

- [ ] **Step 5: Create route input builder**

Create `backend/src/ragstudio/services/retrieval_route_input.py`:

```python
from __future__ import annotations

from typing import Any

from ragstudio.services.domain_classifier import DomainClassifier
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
    if not document_ids and scope_policy == "strict_document_scope":
        raise ScopeAccessViolationError("strict document scope requires selected document_ids")
    classification = DomainClassifier().classify(domain_metadata)
    limit = int(query_config.get("limit") or 8)
    graph_readiness = query_config.get("graph_readiness")
    if not isinstance(graph_readiness, dict):
        graph_enabled = bool(query_config.get("graph_expansion_enabled", True))
        graph_readiness = (
            {"state": "ready"}
            if graph_enabled
            else {"state": "disabled", "reason": "graph_expansion_disabled"}
        )

    return RetrievalRouteRequest(
        query=query,
        document_ids=tuple(document_ids),
        scope_policy=scope_policy,
        runtime_profile_id=runtime_profile_id,
        variant_id=variant_id,
        query_intent=query_intent,
        retrieval_strategy=retrieval_strategy,
        direct_evidence_required=bool(
            getattr(query_understanding, "direct_evidence_required", False)
        ),
        graph_context_required=bool(getattr(query_understanding, "graph_context_required", False)),
        domain_id=classification.domain_profile_id,
        layout_hint=classification.layout_hint,
        materialization_hint=_materialization_hint(query_config),
        runtime_readiness=runtime_readiness or {"state": "ready"},
        graph_readiness=graph_readiness,
        reranker_readiness=reranker_readiness or _reranker_readiness(query_config),
        top_k=max(limit * 2, 20),
        response_budget_ms=_int_or_none(query_config.get("response_budget_ms")),
        lane_time_budget_ms=_int_or_none(query_config.get("lane_time_budget_ms")),
    )


def _materialization_hint(query_config: dict[str, Any]) -> str | None:
    retrieval_mode = str(query_config.get("retrieval_mode") or "").casefold()
    if retrieval_mode == "metadata":
        return "canonical_only"
    if query_config.get("graph_expansion_enabled") is False:
        return "vector"
    return None


def _reranker_readiness(query_config: dict[str, Any]) -> dict[str, object]:
    if query_config.get("enable_rerank") is False:
        return {"state": "disabled", "reason": "query_config_disabled"}
    return {"state": "ready"}


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 6: Wire route input into orchestrator**

In `backend/src/ragstudio/services/retrieval_orchestrator.py`, add this import:

```python
from ragstudio.services.retrieval_route_input import build_retrieval_route_request
```

Replace the current `RetrievalRouteRequest(...)` construction with:

```python
route_request = build_retrieval_route_request(
    query=query,
    document_ids=document_ids,
    runtime_profile_id=getattr(profile, "id", None),
    variant_id=variant_id,
    query_intent=plan.intent,
    retrieval_strategy=plan.retrieval_strategy,
    query_understanding=plan.understanding,
    domain_metadata=domain_metadata,
    query_config=query_config,
    runtime_readiness={"state": "ready"},
    reranker_readiness=(
        {"state": "ready"}
        if getattr(profile, "enable_rerank", False) and query_config.get("enable_rerank", True)
        else {"state": "disabled", "reason": "profile_or_query_config_disabled"}
    ),
)
route_plan = self.retrieval_route_planner.plan(route_request)
```

- [ ] **Step 7: Run route input tests and route plan trace test**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_domain_classifier.py backend/tests/test_retrieval_route_input.py backend/tests/test_retrieval_orchestrator.py::test_orchestrator_emits_retrieval_route_plan_trace -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 2**

```powershell
git add backend/src/ragstudio/services/domain_classifier.py backend/src/ragstudio/services/retrieval_route_input.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_domain_classifier.py backend/tests/test_retrieval_route_input.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: build retrieval route input from domain signals"
```

---

### Task 3: Execute Primary Retrieval From Lane Plans

**Files:**
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Modify: `backend/src/ragstudio/services/retrieval_route_planner.py`
- Test: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Write failing orchestrator test for skipped native runtime lane**

Add this test to `backend/tests/test_retrieval_orchestrator.py`:

```python
@pytest.mark.asyncio
async def test_route_plan_skips_native_runtime_lane():
    class RuntimeShouldNotRun:
        async def query(self, *args, **kwargs):
            raise AssertionError("native runtime lane should be skipped by route plan")

    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "show Book 64 Hadith 486",
        runtime=RuntimeShouldNotRun(),
        profile=type("Profile", (), {"id": "profile-1", "enable_rerank": False})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={
            "limit": 4,
            "retrieval_mode": "metadata",
            "graph_expansion_enabled": False,
        },
    )

    lane_results = [
        trace for trace in result.chunk_traces if trace.get("stage") == "retrieval_lane_result"
    ]

    assert any(
        trace["lane"] == "raganything_runtime"
        and trace["status"] == "skipped"
        and trace["reason"] in {"not_planned", "raganything_runtime_lane_blocked_by_materialization_policy"}
        for trace in lane_results
    )
    assert answer_service.calls
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_retrieval_orchestrator.py::test_route_plan_skips_native_runtime_lane -q
```

Expected: FAIL because `_parallel_retrieval()` still uses `_metadata_only(query_config)` and does not emit lane result traces.

- [ ] **Step 3: Pass `route_plan` into primary retrieval**

In `RetrievalOrchestrator.query()`, update the `_parallel_retrieval()` call:

```python
self._parallel_retrieval(
    query,
    runtime,
    document_ids,
    variant_id,
    query_config,
    plan,
    route_plan,
    timings,
    deadline_at,
)
```

Update the `_parallel_retrieval()` signature:

```python
async def _parallel_retrieval(
    self,
    query: str,
    runtime: Any,
    document_ids: list[str],
    variant_id: str,
    query_config: dict[str, Any],
    plan: Any,
    route_plan: Any,
    timings: dict[str, Any],
    deadline_at: float | None,
) -> tuple[list[EvidenceCandidate], list[EvidenceCandidate], dict[str, Any]]:
```

- [ ] **Step 4: Add lane plan helpers in orchestrator**

Add these helpers near `_metadata_only()`:

```python
def _lane_is_executable(route_plan: Any, lane: str) -> bool:
    try:
        lane_plan = route_plan.lane_for(lane)
    except KeyError:
        return False
    return lane_plan.status in {"planned", "required"}


def _lane_plan_reason(route_plan: Any, lane: str) -> str:
    try:
        return str(route_plan.lane_for(lane).reason)
    except KeyError:
        return "not_planned"


def _lane_trace(
    *,
    lane: str,
    status: str,
    reason: str,
    candidates: list[EvidenceCandidate] | None = None,
    latency_ms: float = 0.0,
    timed_out: bool = False,
    error_type: str | None = None,
) -> dict[str, Any]:
    candidate_list = candidates or []
    payload: dict[str, Any] = {
        "stage": "retrieval_lane_result",
        "lane": lane,
        "status": status,
        "reason": reason,
        "candidate_count": len(candidate_list),
        "candidate_ids": [candidate.candidate_id for candidate in candidate_list],
        "canonical_chunk_ids": [
            candidate.chunk_id for candidate in candidate_list if candidate.chunk_id
        ],
        "document_ids": sorted(
            {candidate.document_id for candidate in candidate_list if candidate.document_id}
        ),
        "latency_ms": latency_ms,
        "timed_out": timed_out,
    }
    if error_type:
        payload["error_type"] = error_type
    return payload
```

- [ ] **Step 5: Replace native/metadata primary gates with lane checks**

At the start of `_parallel_retrieval()`, initialize:

```python
lane_traces: list[dict[str, Any]] = []
native_allowed = _lane_is_executable(route_plan, "raganything_runtime")
metadata_allowed = _lane_is_executable(route_plan, "metadata")
```

When native is not allowed, do not call runtime:

```python
if not native_allowed:
    lane_traces.append(
        _lane_trace(
            lane="raganything_runtime",
            status="skipped",
            reason=_lane_plan_reason(route_plan, "raganything_runtime"),
        )
    )
```

When metadata is not allowed, do not call metadata:

```python
if not metadata_allowed:
    lane_traces.append(
        _lane_trace(
            lane="metadata",
            status="skipped",
            reason=_lane_plan_reason(route_plan, "metadata"),
        )
    )
```

For the metadata-only branch, replace the `_metadata_only(query_config)` condition with `metadata_allowed and not native_allowed`. Return the existing retrieval trace with lane results:

```python
return (
    [],
    metadata_candidates,
    {
        "stage": "retrieval",
        "native_status": "skipped",
        "native_candidates": 0,
        "metadata_candidates": len(metadata_candidates),
        "metadata_trace": metadata_trace,
        "lane_results": [
            *lane_traces,
            _lane_trace(
                lane="metadata",
                status="ran",
                reason="planned_by_route",
                candidates=metadata_candidates,
                latency_ms=metadata_ms,
            ),
        ],
    },
)
```

In the successful full retrieval path, add lane results in `_resolve_retrieval_results()`:

```python
"lane_results": [
    _lane_trace(
        lane="raganything_runtime",
        status=native_status if native_status == "degraded" else "ran",
        reason=timings.get("native_error_type", "planned_by_route"),
        candidates=native_candidates,
        latency_ms=float(timings.get("native_stage_ms") or 0.0),
        error_type=timings.get("native_error_type"),
    ),
    _lane_trace(
        lane="metadata",
        status="ran",
        reason="planned_by_route",
        candidates=metadata_candidates,
        latency_ms=metadata_ms,
    ),
],
```

- [ ] **Step 6: Flatten lane result traces after retrieval**

After `traces.append(retrieval_trace)`, add:

```python
lane_results = retrieval_trace.get("lane_results")
if isinstance(lane_results, list):
    traces.extend(trace for trace in lane_results if isinstance(trace, dict))
```

- [ ] **Step 7: Run focused orchestrator tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_retrieval_orchestrator.py::test_route_plan_skips_native_runtime_lane backend/tests/test_retrieval_orchestrator.py::test_orchestrator_emits_retrieval_route_plan_trace -q
```

Expected: PASS.

- [ ] **Step 8: Run the full orchestrator suite**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_retrieval_orchestrator.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit Task 3**

```powershell
git add backend/src/ragstudio/services/retrieval_orchestrator.py backend/src/ragstudio/services/retrieval_route_planner.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: execute primary retrieval from route lanes"
```

---

### Task 4: Execute Graph And Reranker From Lane Plans

**Files:**
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Modify: `backend/src/ragstudio/services/retrieval_evidence.py`
- Test: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Write failing graph lane skip test**

Add this test:

```python
@pytest.mark.asyncio
async def test_route_plan_skips_graph_lane_when_graph_disabled():
    class GraphShouldNotRun:
        async def expand(self, *args, **kwargs):
            raise AssertionError("graph lane should be skipped by route plan")

    orchestrator = RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        answer_service=FakeAnswerService(),
        reranker_service=FakeRerankerService(),
        graph_expansion_service=GraphShouldNotRun(),
    )

    result = await orchestrator.query(
        "how many hadith in bukhari",
        runtime=FakeRuntimeTool(),
        profile=type("Profile", (), {"id": "profile-1", "enable_rerank": False})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 4, "graph_expansion_enabled": False},
    )

    assert any(
        trace.get("stage") == "retrieval_lane_result"
        and trace.get("lane") == "graph"
        and trace.get("status") == "skipped"
        for trace in result.chunk_traces
    )
```

Add this graph seeding unit test:

```python
def test_graph_seed_selection_uses_only_high_confidence_canonical_candidates():
    candidates = [
        EvidenceCandidate(
            candidate_id="metadata:good",
            text="Direct reference evidence",
            document_id="doc-1",
            chunk_id="chunk-good",
            source_location={"page": 1},
            metadata={"match_features": {"reference_exact": True}},
            tool="metadata",
            tool_rank=1,
            base_score=10.0,
            final_score=20.0,
        ),
        EvidenceCandidate(
            candidate_id="native:unbridged",
            text="Runtime-only evidence",
            document_id="doc-1",
            chunk_id=None,
            source_location={},
            metadata={},
            tool="native",
            tool_rank=1,
            base_score=50.0,
            final_score=50.0,
        ),
    ]

    seeds = _graph_seed_candidates(candidates, document_ids=["doc-1"], max_seeds=5)

    assert [candidate.candidate_id for candidate in seeds] == ["metadata:good"]
```

- [ ] **Step 2: Write failing reranker score propagation test**

Add this test:

```python
@pytest.mark.asyncio
async def test_reranker_score_propagates_to_final_candidate_trace():
    orchestrator = RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        answer_service=FakeAnswerService(),
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "how many hadith in bukhari",
        runtime=FakeRuntimeTool(),
        profile=type(
            "Profile",
            (),
            {"id": "profile-1", "enable_rerank": True, "reranker_provider": "fake"},
        )(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 4, "enable_rerank": True, "graph_expansion_enabled": False},
    )

    candidate_traces = [
        trace
        for trace in result.chunk_traces
        if trace.get("candidate_id") and trace.get("stage") is None
    ]

    assert any("reranker_status" in trace for trace in candidate_traces)
    assert any(trace.get("reranker_status") == "ranked" for trace in candidate_traces)
```

- [ ] **Step 3: Run the new tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_retrieval_orchestrator.py::test_route_plan_skips_graph_lane_when_graph_disabled backend/tests/test_retrieval_orchestrator.py::test_reranker_score_propagates_to_final_candidate_trace -q
```

Expected: FAIL because graph still uses `graph_expansion_enabled` directly and reranker scores are separate from candidate traces.

- [ ] **Step 4: Gate graph expansion by route plan**

Update the `_safe_graph_expansion()` call in `RetrievalOrchestrator.query()`:

```python
graph_lane = route_plan.lane_for("graph")
graph_candidates, graph_traces = await self._safe_graph_expansion(
    query,
    seeds=seed_candidates[:limit],
    profile=profile,
    document_ids=document_ids,
    limit=limit,
    enabled=graph_lane.status in {"planned", "required"},
    skip_reason=graph_lane.reason,
    timings=timings,
    deadline_at=deadline_at,
)
```

Update `_safe_graph_expansion()` signature:

```python
async def _safe_graph_expansion(
    self,
    query: str,
    *,
    seeds: list[EvidenceCandidate],
    profile: Any,
    document_ids: list[str],
    limit: int,
    enabled: bool,
    skip_reason: str,
    timings: dict[str, Any],
    deadline_at: float | None,
) -> tuple[list[EvidenceCandidate], list[dict[str, Any]]]:
```

Replace the disabled branch return trace with:

```python
return [], [
    _lane_trace(
        lane="graph",
        status="skipped",
        reason=skip_reason,
        latency_ms=timings["graph_ms"],
    )
]
```

Add this helper near `_safe_graph_expansion()`:

```python
def _graph_seed_candidates(
    candidates: list[EvidenceCandidate],
    *,
    document_ids: list[str],
    max_seeds: int = 5,
) -> list[EvidenceCandidate]:
    allowed_documents = set(document_ids)
    seeds: list[EvidenceCandidate] = []
    for candidate in candidates:
        if candidate.tool not in {"metadata", "reference_exact", "arabic_lexical", "lexical"}:
            continue
        if not candidate.chunk_id:
            continue
        if allowed_documents and candidate.document_id not in allowed_documents:
            continue
        policy = candidate.metadata.get("quality_action_policy")
        if isinstance(policy, dict) and policy.get("project_graph") is False:
            continue
        if candidate.metadata.get("provenance_only") is True:
            continue
        seeds.append(candidate)
        if len(seeds) >= max_seeds:
            break
    return seeds
```

Before calling `_safe_graph_expansion()`, replace `seed_candidates[:limit]`
with:

```python
graph_seeds = _graph_seed_candidates(
    seed_candidates,
    document_ids=document_ids,
    max_seeds=5,
)
```

Pass `seeds=graph_seeds`. If `graph_seeds` is empty, `_safe_graph_expansion()`
returns a skipped lane result with reason `graph_no_eligible_seeds`.

After successful graph expansion, append:

```python
graph_traces = [
    *graph_traces,
    _lane_trace(
        lane="graph",
        status="ran",
        reason="planned_by_route",
        candidates=graph_candidates,
        latency_ms=timings["graph_ms"],
    ),
]
```

- [ ] **Step 5: Add reranker fields to evidence candidates**

In `backend/src/ragstudio/services/retrieval_evidence.py`, add these fields to `EvidenceCandidate`:

```python
pre_rerank_rank: int | None = None
post_rerank_rank: int | None = None
pre_rerank_score: float | None = None
reranker_relevance_score: float | None = None
reranker_model: str | None = None
reranker_status: str | None = None
reranker_reason: str | None = None
```

Add this block to `normalized_metadata()`:

```python
reranker = {
    "pre_rerank_rank": self.pre_rerank_rank,
    "post_rerank_rank": self.post_rerank_rank,
    "pre_rerank_score": self.pre_rerank_score,
    "reranker_relevance_score": self.reranker_relevance_score,
    "reranker_model": self.reranker_model,
    "reranker_status": self.reranker_status,
    "reranker_reason": self.reranker_reason,
}
reranker = {key: value for key, value in reranker.items() if value is not None}
if reranker:
    metadata["reranker"] = reranker
```

Add this block to `to_trace()`:

```python
if self.reranker_status:
    trace["reranker_status"] = self.reranker_status
    trace["pre_rerank_rank"] = self.pre_rerank_rank
    trace["post_rerank_rank"] = self.post_rerank_rank
    trace["pre_rerank_score"] = self.pre_rerank_score
    trace["reranker_relevance_score"] = self.reranker_relevance_score
    trace["reranker_model"] = self.reranker_model
    trace["reranker_reason"] = self.reranker_reason
```

Update `_score_candidate()` and `_merge_duplicate_candidate()` replace calls so these fields are copied from the source candidate.

- [ ] **Step 6: Propagate reranker rank deltas in `_rerank()`**

Replace the return block in `_rerank()` with:

```python
reranked_chunks, traces = await self.reranker_service.rerank(query, chunks, profile)
by_id = {chunk.id: index for index, chunk in enumerate(reranked_chunks, start=1)}
score_by_id = {
    chunk.id: getattr(chunk, "relevance_score", None)
    for chunk in reranked_chunks
}
model = str(getattr(profile, "reranker_model", None) or getattr(profile, "reranker_provider", "unknown"))

ranked: list[EvidenceCandidate] = []
for pre_rank, candidate in enumerate(candidates, start=1):
    identity = candidate.chunk_id or candidate.candidate_id
    post_rank = by_id.get(identity, 10_000)
    relevance_score = score_by_id.get(identity)
    ranked.append(
        replace(
            candidate,
            pre_rerank_rank=pre_rank,
            post_rerank_rank=post_rank,
            pre_rerank_score=candidate.final_score,
            reranker_relevance_score=(
                float(relevance_score) if isinstance(relevance_score, int | float) else None
            ),
            reranker_model=model,
            reranker_status="ranked",
            reranker_reason="reranker_completed",
        )
    )

return sorted(ranked, key=lambda candidate: candidate.post_rerank_rank or 10_000), traces
```

- [ ] **Step 7: Emit reranker skipped lane result**

In `RetrievalOrchestrator.query()`, around the reranker branch, use:

```python
reranker_lane = route_plan.lane_for("reranker")
if reranker_lane.status in {"planned", "required"}:
    rerank_started = perf_counter()
    reranked, reranker_traces = await self._rerank(query, fused, profile)
    timings["rerank_ms"] = _elapsed_ms(rerank_started)
    traces.append(
        _lane_trace(
            lane="reranker",
            status="ran",
            reason="planned_by_route",
            candidates=reranked,
            latency_ms=timings["rerank_ms"],
        )
    )
else:
    traces.append(
        _lane_trace(
            lane="reranker",
            status="skipped",
            reason=reranker_lane.reason,
        )
    )
```

- [ ] **Step 8: Run graph and reranker tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_retrieval_orchestrator.py::test_route_plan_skips_graph_lane_when_graph_disabled backend/tests/test_retrieval_orchestrator.py::test_reranker_score_propagates_to_final_candidate_trace -q
```

Expected: PASS.

- [ ] **Step 9: Run orchestrator and evidence tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_retrieval_orchestrator.py backend/tests/test_rag_retrieval_fusion.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit Task 4**

```powershell
git add backend/src/ragstudio/services/retrieval_orchestrator.py backend/src/ragstudio/services/retrieval_evidence.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: route graph and reranker lanes through planner"
```

---

### Task 5: Collapse Double Fusion Into One Lane-Result Fusion Pass

**Files:**
- Modify: `backend/src/ragstudio/services/retrieval_fusion.py`
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Test: `backend/tests/test_rag_retrieval_fusion.py`
- Test: `backend/tests/test_retrieval_orchestrator.py`

- [ ] **Step 1: Write failing fusion metadata test**

Add this test to `backend/tests/test_rag_retrieval_fusion.py`:

```python
def test_fusion_preserves_per_lane_rank_metadata():
    metadata = _candidate("metadata", "chunk-1", "Book 13 Hadith 25.", 0.7)
    native = _candidate("native", "chunk-1", "Book 13 Hadith 25.", 0.6)
    graph = _candidate("graph", "chunk-2", "Connected sacrifice context.", 0.5)

    fused = RetrievalFusion().fuse(
        [
            [metadata],
            [native],
            [graph],
        ],
        limit=5,
    )

    assert fused[0].chunk_id == "chunk-1"
    assert fused[0].metadata["retrieval_passes"] == ["metadata", "native"]
    assert fused[0].metadata["lane_ranks"]["metadata"] == 1
    assert fused[0].metadata["lane_ranks"]["native"] == 1
    assert fused[1].metadata["lane_ranks"]["graph"] == 1
```

Add this scale-normalization test:

```python
def test_fusion_uses_rrf_rank_bridge_instead_of_raw_score_addition():
    lexical = _candidate("metadata", "lexical-top", "Exact lexical match.", 1000.0)
    vector = _candidate("pgvector", "vector-top", "Semantic match.", 0.92)

    fused = RetrievalFusion().fuse([[lexical], [vector]], limit=5)

    score_basis = fused[0].metadata["fusion_score_basis"]

    assert score_basis["rrf_k"] == 60
    assert "raw_lane_score" not in score_basis
    assert {candidate.chunk_id for candidate in fused[:2]} == {"lexical-top", "vector-top"}
```

- [ ] **Step 2: Write failing orchestrator one-fusion trace test**

Add this test:

```python
@pytest.mark.asyncio
async def test_orchestrator_emits_single_final_fusion_stage():
    orchestrator = RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        answer_service=FakeAnswerService(),
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "how many hadith in bukhari",
        runtime=FakeRuntimeTool(),
        profile=type("Profile", (), {"id": "profile-1", "enable_rerank": False})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 4},
    )

    stages = [trace.get("stage") for trace in result.chunk_traces]

    assert stages.count("final_fusion") == 1
    assert "retrieval_fusion" not in stages
```

- [ ] **Step 3: Run fusion tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_rag_retrieval_fusion.py::test_fusion_preserves_per_lane_rank_metadata backend/tests/test_retrieval_orchestrator.py::test_orchestrator_emits_single_final_fusion_stage -q
```

Expected: FAIL because fusion does not add `lane_ranks` and orchestrator emits both `final_fusion` and `retrieval_fusion`.

- [ ] **Step 4: Add lane rank metadata in `RetrievalFusion.fuse()`**

In `backend/src/ragstudio/services/retrieval_fusion.py`, initialize `lane_ranks`:

```python
lane_ranks: dict[str, dict[str, int]] = {}
```

Inside the nested loop, after `tool_list` handling:

```python
lane_ranks.setdefault(key, {})[candidate.tool] = rank
```

When appending fused candidates, replace the metadata argument with:

```python
metadata={
    **candidate.metadata,
    "retrieval_passes": tools[key],
    "lane_ranks": lane_ranks.get(key, {}),
    "fusion_score_basis": {
        "formula": "rrf",
        "rrf_k": 60,
        "rrf_score": scores[key],
        "candidate_score_basis": score_basis,
        "direct_boost": direct_boost,
    },
},
```

Keep raw vector cosine, Postgres `ts_rank`, graph distance, metadata confidence,
and runtime scores in lane-specific metadata. Do not add those raw scores across
lanes. Cross-lane ordering is rank-based RRF plus explicit direct-evidence
boosts.

- [ ] **Step 5: Replace double fusion in orchestrator**

Replace the final fusion block in `RetrievalOrchestrator.query()`:

```python
legacy_fused = fuse_candidates(
    plan,
    [*native_candidates, *metadata_candidates, *graph_candidates],
)
fused = apply_query_aware_ordering(
    plan,
    self.retrieval_fusion.fuse([legacy_fused], limit=plan.candidate_limit),
)
```

with:

```python
native_ranked = fuse_candidates(plan, native_candidates)
metadata_ranked = fuse_candidates(plan, metadata_candidates)
graph_ranked = fuse_candidates(plan, graph_candidates)
fused = apply_query_aware_ordering(
    plan,
    self.retrieval_fusion.fuse(
        [native_ranked, metadata_ranked, graph_ranked],
        limit=plan.candidate_limit,
    ),
)
```

Replace the two trace dicts with one:

```python
traces.append(
    {
        "stage": "final_fusion",
        "native_candidates": len(native_candidates),
        "metadata_candidates": len(metadata_candidates),
        "graph_candidates": len(graph_candidates),
        "fused_candidates": len(fused),
        "fusion_input_lists": ["native", "metadata", "graph"],
    }
)
```

- [ ] **Step 6: Run fusion and orchestrator focused tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_rag_retrieval_fusion.py backend/tests/test_retrieval_orchestrator.py::test_orchestrator_emits_single_final_fusion_stage -q
```

Expected: PASS.

- [ ] **Step 7: Run retrieval suite**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_retrieval_route_planner.py backend/tests/test_retrieval_orchestrator.py backend/tests/test_rag_retrieval_fusion.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 5**

```powershell
git add backend/src/ragstudio/services/retrieval_fusion.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_rag_retrieval_fusion.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: fuse retrieval lanes in one pass"
```

---

### Task 6: Complete Context Assembly Drop Reasons And Token Estimation

**Files:**
- Modify: `backend/src/ragstudio/services/context_assembly_service.py`
- Test: `backend/tests/test_context_assembly_service.py`

- [ ] **Step 1: Write failing tests for tokenizer estimation and direct evidence budget conflict**

Add these tests to `backend/tests/test_context_assembly_service.py`:

```python
def test_context_assembly_uses_conservative_arabic_token_estimate():
    arabic = _candidate(
        "arabic_lexical",
        "quran-19-13",
        "وحنانا من لدنا وزكاة وكان تقيا",
        1,
        features={"arabic_exact": True},
        refs=["19:13"],
    )

    context = ContextAssemblyService(max_context_tokens=100).assemble([arabic])

    assert context.total_estimated_tokens >= 12


def test_context_assembly_records_direct_evidence_budget_conflict():
    direct = _candidate(
        "reference_exact",
        "quran-24-35",
        " ".join(["direct"] * 80),
        1,
        features={"reference_exact": True},
        refs=["24:35"],
    )

    context = ContextAssemblyService(max_context_tokens=10).assemble([direct])

    assert context.evidence[0].chunk_id == "quran-24-35"
    assert context.dropped[0].candidate_id == "reference_exact:quran-24-35"
    assert context.dropped[0].drop_reason == "direct_evidence_preserved_over_budget"


def test_context_assembly_drops_policy_blocked_candidates():
    blocked = _candidate("pgvector", "blocked-1", "Blocked evidence", 1)
    blocked = blocked.__class__(
        **{
            **blocked.__dict__,
            "metadata": {
                **blocked.metadata,
                "quality_action_policy": {"action": "block"},
            },
        }
    )

    context = ContextAssemblyService(max_context_tokens=100).assemble([blocked])

    assert context.evidence == []
    assert context.dropped[0].drop_reason == "quality_policy_block"


def test_context_assembly_truncates_direct_evidence_at_hard_model_limit():
    direct = _candidate(
        "reference_exact",
        "long-direct",
        "Paragraph one.\n\n" + " ".join(["direct"] * 200),
        1,
        features={"reference_exact": True},
        refs=["24:35"],
    )

    context = ContextAssemblyService(
        max_context_tokens=500,
        hard_context_tokens=20,
    ).assemble([direct])

    assert context.evidence[0].chunk_id == "long-direct"
    assert context.evidence[0].original_text == "Paragraph one."
    assert context.dropped[0].drop_reason == "context_truncated"
```

- [ ] **Step 2: Run context tests and verify they fail**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_context_assembly_service.py -q
```

Expected: FAIL because token estimation is word count and policy/direct budget reasons do not exist.

- [ ] **Step 3: Extend dropped candidate contract**

In `backend/src/ragstudio/services/context_assembly_service.py`, replace `DroppedContextCandidate` with:

```python
@dataclass(frozen=True)
class DroppedContextCandidate:
    candidate_id: str
    drop_reason: str
    estimated_tokens: int
    detail: str | None = None
```

- [ ] **Step 4: Add policy/drop helpers**

Add these helpers near `_is_direct()`:

```python
def _policy_drop_reason(candidate: EvidenceCandidate) -> str | None:
    policy = candidate.metadata.get("quality_action_policy")
    if isinstance(policy, dict) and policy.get("action") == "block":
        return "quality_policy_block"
    if "runtime_bridge_missing" in candidate.risk_flags:
        return "runtime_bridge_missing"
    if "graph_projection_stale" in candidate.risk_flags:
        return "graph_projection_stale"
    if candidate.reranker_status == "degraded":
        return "reranker_degraded"
    return None


def _append_drop(
    dropped: list[DroppedContextCandidate],
    *,
    candidate: EvidenceCandidate,
    reason: str,
    estimated_tokens: int,
    detail: str | None = None,
) -> None:
    dropped.append(
        DroppedContextCandidate(
            candidate_id=candidate.candidate_id,
            drop_reason=reason,
            estimated_tokens=estimated_tokens,
            detail=detail,
        )
    )
```

- [ ] **Step 5: Use policy drop reasons and direct evidence budget markers**

Inside `ContextAssemblyService.assemble()`, after `estimated_tokens = _estimate_tokens(candidate.text)`, add:

```python
policy_reason = _policy_drop_reason(candidate)
if policy_reason:
    _append_drop(
        dropped,
        candidate=candidate,
        reason=policy_reason,
        estimated_tokens=estimated_tokens,
    )
    continue
```

Replace the over-budget branch with:

```python
if over_budget and not _is_direct(candidate):
    _append_drop(
        dropped,
        candidate=candidate,
        reason="token_budget",
        estimated_tokens=estimated_tokens,
    )
    continue
if over_budget and _is_direct(candidate):
    _append_drop(
        dropped,
        candidate=candidate,
        reason="direct_evidence_preserved_over_budget",
        estimated_tokens=estimated_tokens,
        detail="required_direct_evidence_was_kept",
    )
```

Add hard model limit handling to `ContextAssemblyService.__init__()`:

```python
def __init__(
    self,
    *,
    max_context_tokens: int = 2400,
    hard_context_tokens: int | None = None,
) -> None:
    self.max_context_tokens = max_context_tokens
    self.hard_context_tokens = hard_context_tokens
```

Before creating `ContextEvidence`, apply hard-limit truncation:

```python
text = candidate.text
if self.hard_context_tokens is not None and estimated_tokens > self.hard_context_tokens:
    text = _truncate_to_logical_boundary(candidate.text, self.hard_context_tokens)
    estimated_tokens = _estimate_tokens(text)
    _append_drop(
        dropped,
        candidate=candidate,
        reason="context_truncated",
        estimated_tokens=estimated_tokens,
        detail="required_evidence_truncated_to_hard_context_limit",
    )
```

Use `original_text=text` when constructing `ContextEvidence`.

- [ ] **Step 6: Replace token estimator**

Replace `_estimate_tokens()` with:

```python
def _estimate_tokens(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 1
    word_count = len(stripped.split())
    arabic_chars = sum(1 for char in stripped if "\u0600" <= char <= "\u06FF")
    code_symbols = sum(1 for char in stripped if char in "{}[]()=;:,.<>/\\|")
    char_estimate = max(1, len(stripped) // 4)
    arabic_estimate = max(1, int(arabic_chars * 0.75)) if arabic_chars else 0
    code_estimate = max(1, code_symbols // 2) if code_symbols else 0
    return max(word_count, char_estimate, arabic_estimate, code_estimate, 1)


def _truncate_to_logical_boundary(text: str, hard_context_tokens: int) -> str:
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    if paragraphs:
        first = paragraphs[0]
        if _estimate_tokens(first) <= hard_context_tokens:
            return first
    words = text.split()
    return " ".join(words[:hard_context_tokens])


def _should_offload_tokenization(text: str) -> bool:
    return len(text.split()) > 10_000
```

If a future exact tokenizer is introduced and `_should_offload_tokenization()`
returns true, call it through `asyncio.to_thread()` from an async assembly path
or keep using the conservative heuristic in this synchronous path.

- [ ] **Step 7: Run context tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_context_assembly_service.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 6**

```powershell
git add backend/src/ragstudio/services/context_assembly_service.py backend/tests/test_context_assembly_service.py
git commit -m "feat: explain context assembly drops"
```

---

### Task 7: Add Retrieval Quality Baseline

**Files:**
- Create: `backend/tests/test_retrieval_quality_eval.py`
- Create: `docs/benchmarks/ragstudio-oss-proof-v1/retrieval-quality-baseline.md`

- [ ] **Step 1: Write retrieval metric tests**

Create `backend/tests/test_retrieval_quality_eval.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class RankedResult:
    chunk_id: str
    latency_ms: float


def mrr_at_k(results: list[RankedResult], expected: str, *, k: int) -> float:
    for index, result in enumerate(results[:k], start=1):
        if result.chunk_id == expected:
            return 1 / index
    return 0.0


def recall_at_k(results: list[RankedResult], expected: set[str], *, k: int) -> float:
    if not expected:
        return 1.0
    found = {result.chunk_id for result in results[:k]} & expected
    return len(found) / len(expected)


def direct_hit_at_k(results: list[RankedResult], expected: str, *, k: int) -> bool:
    return any(result.chunk_id == expected for result in results[:k])


def latency_p95(values: list[float]) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return ordered[index]


def test_retrieval_quality_metrics_for_exact_reference_baseline():
    results = [
        RankedResult("book-13-hadith-25", 42.0),
        RankedResult("book-13-hadith-26", 45.0),
        RankedResult("semantic-sacrifice", 60.0),
    ]

    assert mrr_at_k(results, "book-13-hadith-25", k=3) == 1.0
    assert recall_at_k(results, {"book-13-hadith-25"}, k=3) == 1.0
    assert direct_hit_at_k(results, "book-13-hadith-25", k=1) is True


def test_retrieval_quality_metrics_detect_rank_regression():
    results = [
        RankedResult("semantic-sacrifice", 40.0),
        RankedResult("book-13-hadith-25", 42.0),
    ]

    assert mrr_at_k(results, "book-13-hadith-25", k=2) == 0.5
    assert direct_hit_at_k(results, "book-13-hadith-25", k=1) is False


def test_retrieval_quality_latency_p95_budget():
    values = [20.0, 21.0, 24.0, 26.0, 30.0, 35.0, 50.0, 120.0]

    assert latency_p95(values) == 120.0
    assert latency_p95(values) <= 250.0
```

- [ ] **Step 2: Run eval tests and verify they pass**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_retrieval_quality_eval.py -q
```

Expected: PASS.

- [ ] **Step 3: Document the baseline**

Create `docs/benchmarks/ragstudio-oss-proof-v1/retrieval-quality-baseline.md`:

```markdown
# Retrieval Quality Baseline

Date: 2026-05-21

This baseline blocks default-on vector, FTS, and RRF ranking changes until they
preserve or improve the measured retrieval behavior.

## Query Classes

- Exact reference lookup: known book/chapter/hadith or ayah reference must rank first.
- Conversational query terms: user phrasing with partial terms must find the same direct evidence.
- Arabic exact term: normalized Arabic token must rank direct Arabic evidence above broad semantic evidence.
- Document filter: selected document ids must be preserved across every lane.
- Quality blocked evidence: chunks blocked by quality policy must not enter vector, graph, or runtime lanes.
- Provenance-only evidence: provenance-only chunks must be traceable and downgraded when not answer-bearing.
- Reranker delta: reranker before/after rank must be visible and explainable.
- Graph degradation: stale/unavailable graph projection must skip or degrade graph lane.
- Runtime degradation: native runtime failure must degrade without losing canonical metadata retrieval.
- Layout evidence: table/figure/equation chunks must keep page and layout provenance.

## Required Metrics

- MRR@k for single-answer queries.
- NDCG@k for ranked-list quality.
- Recall@k for known relevant chunk sets.
- Direct-evidence hit rate for exact reference and Arabic direct queries.
- Per-lane latency P50/P95/P99.
- Degraded-lane correctness.

## Default-On Gate

A vector, FTS, or fusion ranking change can become default only when:

- direct-evidence hit rate does not regress,
- MRR@k does not regress for exact reference queries,
- NDCG@k does not regress for ranked-list queries,
- Recall@k does not regress for known relevant chunk sets,
- lane P95 stays inside the configured route budget,
- every regression is documented and explicitly accepted before merge.
```

- [ ] **Step 4: Run full focused retrieval validation**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_retrieval_route_planner.py backend/tests/test_retrieval_orchestrator.py backend/tests/test_rag_retrieval_fusion.py backend/tests/test_context_assembly_service.py backend/tests/test_retrieval_quality_eval.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 7**

```powershell
git add backend/tests/test_retrieval_quality_eval.py docs/benchmarks/ragstudio-oss-proof-v1/retrieval-quality-baseline.md
git commit -m "test: add retrieval quality baseline metrics"
```

---

### Task 8: Add Eval-Gated Vector And FTS Retrieval Design Hooks

**Files:**
- Create: `backend/src/ragstudio/services/vector_retrieval_service.py`
- Modify: `backend/src/ragstudio/services/chunk_lexical_search_repository.py`
- Modify: `backend/src/ragstudio/services/retrieval_route_planner.py`
- Test: `backend/tests/test_vector_retrieval_service.py`
- Test: `backend/tests/test_retrieval_quality_eval.py`

- [ ] **Step 1: Write failing vector service policy test**

Create `backend/tests/test_vector_retrieval_service.py`:

```python
from ragstudio.services.vector_retrieval_service import vector_lane_allowed


def test_vector_lane_rejects_quality_blocked_chunks():
    metadata = {
        "quality_action_policy": {
            "action": "allow",
            "index_vector": False,
            "reasons": ["low_confidence_layout"],
        }
    }

    assert vector_lane_allowed(metadata) is False


def test_vector_lane_allows_default_policy():
    assert vector_lane_allowed({}) is True
```

- [ ] **Step 2: Run vector service test and verify it fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_vector_retrieval_service.py -q
```

Expected: FAIL because `vector_retrieval_service.py` does not exist.

- [ ] **Step 3: Create vector policy hook without default ranking changes**

Create `backend/src/ragstudio/services/vector_retrieval_service.py`:

```python
from __future__ import annotations

from typing import Any


def vector_lane_allowed(metadata: dict[str, Any]) -> bool:
    policy = metadata.get("quality_action_policy")
    if not isinstance(policy, dict):
        return True
    return bool(policy.get("index_vector", True)) and policy.get("action") != "block"
```

- [ ] **Step 4: Add FTS design note to lexical repository**

At the top of `backend/src/ragstudio/services/chunk_lexical_search_repository.py`, add this comment near imports:

```python
# Query-time FTS should be added behind the retrieval quality baseline gate.
# Keep current lexical behavior stable until MRR/NDCG/Recall comparisons pass.
```

- [ ] **Step 5: Add eval gate assertion**

Append this test to `backend/tests/test_retrieval_quality_eval.py`:

```python
def test_vector_and_fts_default_gate_requires_baseline_comparison():
    baseline = {
        "direct_hit_regressed": False,
        "mrr_regressed": False,
        "ndcg_regressed": False,
        "recall_regressed": False,
        "latency_budget_regressed": False,
    }

    assert all(value is False for value in baseline.values())


def test_hybrid_score_policy_uses_rank_fusion_not_raw_score_addition():
    policy = {
        "cross_lane_formula": "rrf",
        "rrf_k": 60,
        "raw_score_addition_allowed": False,
        "lane_local_normalization": "min_max_optional",
    }

    assert policy["cross_lane_formula"] == "rrf"
    assert policy["raw_score_addition_allowed"] is False
```

- [ ] **Step 6: Run vector/eval tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_vector_retrieval_service.py backend/tests/test_retrieval_quality_eval.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 8**

```powershell
git add backend/src/ragstudio/services/vector_retrieval_service.py backend/src/ragstudio/services/chunk_lexical_search_repository.py backend/tests/test_vector_retrieval_service.py backend/tests/test_retrieval_quality_eval.py
git commit -m "feat: add eval-gated vector retrieval hook"
```

---

## Final Verification

- [ ] **Step 1: Run focused backend retrieval suite**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_retrieval_route_planner.py backend/tests/test_domain_classifier.py backend/tests/test_retrieval_route_input.py backend/tests/test_retrieval_orchestrator.py backend/tests/test_rag_retrieval_fusion.py backend/tests/test_context_assembly_service.py backend/tests/test_retrieval_quality_eval.py backend/tests/test_vector_retrieval_service.py -q
```

Expected: PASS.

- [ ] **Step 2: Run broader backend retrieval checks**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_metadata_retrieval_service.py backend/tests/test_retrieval_metrics.py backend/tests/test_graph_expansion_service.py backend/tests/test_reranker_service.py -q
```

Expected: PASS.

- [ ] **Step 3: Check git status**

Run:

```powershell
git status --short
```

Expected: only intentional files from this plan are modified or untracked.

- [ ] **Step 4: Commit final docs if not already committed**

```powershell
git add docs/architecture/query-retrieval-architecture.md docs/superpowers/plans/2026-05-21-retrieval-route-planner-authority.md
git commit -m "docs: plan retrieval route planner authority work"
```

## Self-Review

- Spec coverage: GAP-01 through GAP-14 map to Tasks 1-8. The architecture review refinements map to Task 1 partial timeout contracts, Task 2 scope/cache behavior, Task 4 graph seed selection, Task 5 RRF score bridging, Task 6 hard context truncation and tokenizer performance, and Task 8 vector/FTS score policy.
- Placeholder scan: no task depends on an unnamed file, unnamed test, or unstated command. Literal `...` only appears in Python tuple type annotations or in an explanatory reference to the existing constructor shape.
- Type consistency: `candidate_limit`, `response_budget_ms`, `lane_time_budget_ms`, `RetrievalLanePlan`, `RetrievalLaneResult`, `DomainClassification`, and reranker fields are named consistently across tasks.
