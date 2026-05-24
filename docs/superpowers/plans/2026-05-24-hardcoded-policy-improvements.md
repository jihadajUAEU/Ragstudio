# Hardcoded Policy Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Ragstudio's important hardcoded defaults, regex policy, prompts, retrieval scores, and thresholds into named, testable policy modules without changing current behavior.

**Architecture:** Keep existing behavior as the compatibility baseline first, then route services through explicit policy objects and shared registries. The first pass is behavior-preserving: every moved constant keeps the current value, trace payloads expose the policy version/name, and tests lock the existing output before later tuning work.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy async ORM, pytest, TypeScript, React, Vitest, OpenAPI generated bindings.

---

## Scope Check

This plan covers one architecture cleanup theme: hardcoded product policy becomes named, versioned, and testable. It intentionally avoids changing retrieval quality, prompt wording, redaction coverage, or UI design in the first implementation pass. Any later tuning of weights or prompts should be a separate eval-backed plan.

The plan is split into independently committable tasks:

1. Runtime default registry.
2. Retrieval scoring policy objects.
3. Prompt template registry.
4. Shared redaction registry.
5. Frontend/API default synchronization.
6. Operational and evaluation policy registry.
7. Reference and query regex registry.
8. Domain, API, proof, and query policy classification.
9. Documentation and verification.
10. Structured-reference enforcement follow-up.

## File Structure

- Create: `backend/src/ragstudio/services/runtime_defaults.py`
  - Owns one canonical set of persisted runtime default values and validation ranges.
- Modify: `backend/src/ragstudio/schemas/settings.py`
  - Imports runtime defaults instead of redefining values inline.
- Modify: `backend/src/ragstudio/db/models.py`
  - Uses the runtime default constants for ORM defaults.
- Modify: `backend/src/ragstudio/db/engine.py`
  - Uses the runtime default constants when repairing or adding profile columns.
- Modify: `backend/src/ragstudio/services/settings_service.py`
  - Uses the runtime default registry when filling missing profile values.
- Modify: `backend/src/ragstudio/services/runtime_profile_service.py`
  - Uses the same default registry for runtime object construction.
- Test: `backend/tests/test_settings.py`
- Test: `backend/tests/test_runtime_profile_service.py`

- Create: `backend/src/ragstudio/services/retrieval_policy.py`
  - Owns hybrid scoring weights, direct-match boosts, fusion priority, layout neighbor scores, context window scores, and route timeout defaults.
- Modify: `backend/src/ragstudio/services/hybrid_chunk_search.py`
  - Delegates scoring constants to `HybridScorePolicy`.
- Modify: `backend/src/ragstudio/services/retrieval_fusion.py`
  - Delegates RRF, direct priority, lane priority, and direct boosts to `FusionScorePolicy`.
- Modify: `backend/src/ragstudio/services/layout_neighbor_service.py`
  - Delegates spatial proximity and fixed score values to `LayoutNeighborPolicy`.
- Modify: `backend/src/ragstudio/services/context_window_service.py`
  - Delegates context window scores to `ContextWindowPolicy`.
- Modify: `backend/src/ragstudio/services/retrieval_route_planner.py`
  - Delegates lane timeout fallback and budget fraction to `RoutePlanningPolicy`.
- Test: `backend/tests/test_hybrid_chunk_search_arabic.py`
- Test: `backend/tests/test_rag_retrieval_fusion.py`
- Test: `backend/tests/test_layout_neighbor_service.py`
- Test: `backend/tests/test_context_window_service.py`
- Test: `backend/tests/test_retrieval_route_planner.py`

- Create: `backend/src/ragstudio/services/prompt_templates.py`
  - Owns prompt IDs, prompt versions, and formatter functions for answer generation, LLM reranking, metadata autosuggest, and vision recovery.
- Modify: `backend/src/ragstudio/services/runtime_answer_service.py`
  - Uses the answer prompt template and records prompt metadata.
- Modify: `backend/src/ragstudio/services/llm_reranker_service.py`
  - Uses the reranker prompt template and keeps current JSON contract.
- Modify: `backend/src/ragstudio/services/domain_metadata_ai_suggester.py`
  - Uses the autosuggest prompt template while keeping the current prompt body.
- Modify: `backend/src/ragstudio/services/parser_normalization.py`
  - Uses the vision recovery prompt template while keeping the current prompt body.
- Test: `backend/tests/test_domain_metadata_ai_suggester.py`
- Test: `backend/tests/test_parser_normalization.py`

- Create: `backend/src/ragstudio/services/redaction_registry.py`
  - Owns shared redaction rules for proof packets, document evidence previews, and document evidence exports.
- Modify: `backend/src/ragstudio/proof_packet/redaction.py`
  - Uses the shared registry.
- Modify: `backend/src/ragstudio/services/document_parse_evidence_service.py`
  - Uses the shared registry for preview safety.
- Modify: `backend/src/ragstudio/services/document_parse_evidence_exporter.py`
  - Uses the shared registry for export validation.
- Test: `backend/tests/test_proof_packet_validator.py`
- Test: `backend/tests/test_document_parse_evidence_service.py` if it exists; otherwise create `backend/tests/test_document_parse_evidence_redaction.py`.

- Create: `backend/src/ragstudio/schemas/defaults.py`
  - Defines API response models for current defaults.
- Create: `backend/src/ragstudio/api/routes/defaults.py`
  - Exposes default settings and policy versions for frontend synchronization.
- Modify: `backend/src/ragstudio/app.py`
  - Registers the defaults route.
- Modify: `frontend/src/api/client.ts`
  - Adds `apiClient.defaults()`.
- Modify: `frontend/src/features/settings/settings-page.tsx`
  - Reads runtime default values instead of duplicating important numeric fallbacks.
- Modify: `frontend/src/features/variants/variants-page.tsx`
  - Keeps local presets but labels them as UI presets separate from runtime defaults.
- Test: `frontend/tests/api-client.test.ts`
- Test: `frontend/tests/settings-page.test.tsx`
- Test: `frontend/tests/variants-page.test.tsx`

- Create: `backend/src/ragstudio/services/operational_policy.py`
  - Owns upload limits, worker lease defaults, chunk persistence guardrails, chunk-search fallback limits, candidate-diversity thresholds, retrieval metric gates, evaluation scoring weights, and backend variant presets.
- Modify: `backend/src/ragstudio/api/upload_utils.py`
  - Uses upload policy values instead of module-level numeric constants.
- Modify: `backend/src/ragstudio/workers/index_worker.py`
  - Uses worker lease default from operational policy.
- Modify: `backend/src/ragstudio/services/background_runner_factory.py`
  - Uses worker lease default from operational policy.
- Modify: `backend/src/ragstudio/services/chunk_persistence_service.py`
  - Uses chunk persistence guardrails from operational policy.
- Modify: `backend/src/ragstudio/services/chunk_service.py`
  - Uses fallback candidate limit from operational policy.
- Modify: `backend/src/ragstudio/services/candidate_diversity.py`
  - Uses default Jaccard threshold from operational policy.
- Modify: `backend/src/ragstudio/services/retrieval_metrics.py`
  - Uses retrieval metric gate defaults from operational policy.
- Modify: `backend/src/ragstudio/services/scoring_service.py`
  - Uses evaluation scoring weights from operational policy.
- Modify: `backend/src/ragstudio/schemas/variants.py`
  - Uses backend variant presets from operational policy.
- Test: create `backend/tests/test_operational_policy.py`
- Test: `backend/tests/test_experiments_scoring.py`
- Test: `backend/tests/test_retrieval_metrics.py`

- Create: `backend/src/ragstudio/services/reference_regex_registry.py`
  - Owns standard script, reference, query-understanding, and proof-safe parser regexes while leaving user-provided custom regex compilation in the contract/compiler layer.
- Modify: `backend/src/ragstudio/services/script_detection.py`
  - Imports script regexes from the shared registry.
- Modify: `backend/src/ragstudio/services/arabic_text.py`
  - Imports Arabic token and diacritic regexes from the shared registry.
- Modify: `backend/src/ragstudio/services/reference_metadata.py`
  - Imports built-in reference regexes from the shared registry.
- Modify: `backend/src/ragstudio/services/query_understanding.py`
  - Imports built-in query intent regexes from the shared registry.
- Modify: `backend/src/ragstudio/services/query_hypothesis_verifier.py`
  - Imports reference verifier regex from the shared registry.
- Test: create `backend/tests/test_reference_regex_registry.py`
- Test: `backend/tests/test_domain_metadata_quality_gate.py`
- Test: `backend/tests/test_retrieval_route_input.py`

- Create: `backend/src/ragstudio/services/static_policy_catalog.py`
  - Classifies remaining hardcoded items as `runtime_default`, `tunable_policy`, `protocol_constant`, `security_policy`, or `ui_fallback`, with source paths and ownership notes.
- Modify: `backend/src/ragstudio/services/domain_profile_registry.py`
  - Adds a policy version constant to built-in domain profiles and exposes profile defaults in a testable form.
- Modify: `backend/src/ragstudio/services/chunk_splitter.py`
  - Adds named constants for chunk profile word targets, full-width layout threshold, and semantic split lower bound.
- Modify: `backend/src/ragstudio/services/retrieval_evidence.py`
  - Adds named constants for candidate expansion limits such as `limit * 2` and `20`.
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
  - Adds named constants for graph seed cap and response/query fallback budgets that are not covered by route policy.
- Modify: `backend/src/ragstudio/services/query_hypothesis_service.py`
  - Adds a policy version for allowed intents/scripts/domain hints/answer shapes and classifies them as protocol vocabularies.
- Modify: `backend/src/ragstudio/services/provider_manifest_service.py`
  - Adds named policy constants for supported manifest sections and capability vocabulary.
- Modify: `backend/src/ragstudio/services/pdf_preflight_service.py`
  - Uses named policy constants for preflight ratio fallback and proof-safe regex handling.
- Modify: `backend/src/ragstudio/proof_packet/validator.py`
  - Classifies `PACKET_ID`, `DEFAULT_PACKET_ROOT`, and source commit length as proof protocol constants.
- Modify: `backend/src/ragstudio/proof_packet/errors.py`
  - Classifies error codes and recovery guidance as proof protocol constants.
- Test: create `backend/tests/test_static_policy_catalog.py`
- Test: `backend/tests/test_domain_profile_registry.py`
- Test: `backend/tests/test_parser_normalization.py`
- Test: `backend/tests/test_proof_packet_validator.py`

- Modify: `backend/src/ragstudio/services/domain_metadata_quality_gate.py`
  - Enforce `reference_unit_unresolved` only when the reference contract is verified/executable.
- Test: `backend/tests/test_domain_metadata_quality_gate.py`
  - Adds regression coverage for `metadata_only` reference hints versus verified executable contracts.

---

### Task 1: Runtime Defaults Registry

**Files:**
- Create: `backend/src/ragstudio/services/runtime_defaults.py`
- Modify: `backend/src/ragstudio/schemas/settings.py`
- Modify: `backend/src/ragstudio/db/models.py`
- Modify: `backend/src/ragstudio/db/engine.py`
- Modify: `backend/src/ragstudio/services/settings_service.py`
- Modify: `backend/src/ragstudio/services/runtime_profile_service.py`
- Test: `backend/tests/test_settings.py`
- Test: `backend/tests/test_runtime_profile_service.py`

- [x] **Step 1: Write failing tests for the canonical runtime defaults**

Append these tests to `backend/tests/test_settings.py`:

```python
from ragstudio.schemas.settings import SettingsProfileIn
from ragstudio.services.runtime_defaults import RUNTIME_DEFAULTS, RUNTIME_LIMITS


def test_settings_schema_uses_canonical_runtime_defaults() -> None:
    profile = SettingsProfileIn()

    assert profile.llm_timeout_ms == RUNTIME_DEFAULTS.llm_timeout_ms
    assert profile.embedding_timeout_ms == RUNTIME_DEFAULTS.embedding_timeout_ms
    assert profile.embedding_dimensions == RUNTIME_DEFAULTS.embedding_dimensions
    assert profile.embedding_batch_size == RUNTIME_DEFAULTS.embedding_batch_size
    assert profile.mineru_timeout_ms == RUNTIME_DEFAULTS.mineru_timeout_ms
    assert profile.mineru_poll_interval_ms == RUNTIME_DEFAULTS.mineru_poll_interval_ms
    assert profile.vision_timeout_ms == RUNTIME_DEFAULTS.vision_timeout_ms
    assert profile.reranker_timeout_ms == RUNTIME_DEFAULTS.reranker_timeout_ms
    assert profile.chunk_token_size == RUNTIME_DEFAULTS.chunk_token_size
    assert profile.chunk_overlap_token_size == RUNTIME_DEFAULTS.chunk_overlap_token_size
    assert profile.max_context_tokens == RUNTIME_DEFAULTS.max_context_tokens
    assert profile.top_k == RUNTIME_DEFAULTS.top_k
    assert profile.chunk_top_k == RUNTIME_DEFAULTS.chunk_top_k
    assert profile.cosine_better_than_threshold == RUNTIME_DEFAULTS.cosine_better_than_threshold
    assert profile.max_total_tokens == RUNTIME_DEFAULTS.max_total_tokens
    assert profile.max_entity_tokens == RUNTIME_DEFAULTS.max_entity_tokens
    assert profile.max_relation_tokens == RUNTIME_DEFAULTS.max_relation_tokens


def test_runtime_default_limits_preserve_current_bounds() -> None:
    assert RUNTIME_LIMITS.timeout_min_ms == 100
    assert RUNTIME_LIMITS.timeout_max_ms == 1_800_000
    assert RUNTIME_LIMITS.mineru_timeout_max_ms == 28_800_000
    assert RUNTIME_LIMITS.top_k_max == 200
    assert RUNTIME_LIMITS.embedding_dimensions_max == 65_536
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; pytest backend/tests/test_settings.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.runtime_defaults'`.

- [x] **Step 3: Add the runtime defaults module**

Create `backend/src/ragstudio/services/runtime_defaults.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeDefaults:
    llm_timeout_ms: int = 10_000
    embedding_timeout_ms: int = 10_000
    embedding_dimensions: int = 1_536
    embedding_batch_size: int = 16
    mineru_timeout_ms: int = 14_400_000
    mineru_poll_interval_ms: int = 1_000
    mineru_max_concurrent_files: int = 1
    vision_timeout_ms: int = 10_000
    reranker_timeout_ms: int = 10_000
    chunk_token_size: int = 1_200
    chunk_overlap_token_size: int = 100
    context_window: int = 1
    max_context_tokens: int = 2_000
    top_k: int = 40
    chunk_top_k: int = 20
    cosine_better_than_threshold: float = 0.2
    max_total_tokens: int = 30_000
    max_entity_tokens: int = 6_000
    max_relation_tokens: int = 8_000
    llm_model_max_async: int = 4
    embedding_func_max_async: int = 8
    max_parallel_insert: int = 2


@dataclass(frozen=True, slots=True)
class RuntimeLimits:
    timeout_min_ms: int = 100
    timeout_max_ms: int = 1_800_000
    mineru_timeout_max_ms: int = 28_800_000
    mineru_poll_interval_max_ms: int = 60_000
    embedding_dimensions_max: int = 65_536
    embedding_batch_size_max: int = 1_024
    chunk_token_size_min: int = 100
    chunk_token_size_max: int = 8_192
    chunk_overlap_token_size_max: int = 2_048
    context_window_max: int = 10
    max_context_tokens_max: int = 100_000
    top_k_max: int = 200
    runtime_token_budget_max: int = 1_000_000
    async_limit_max: int = 128
    max_parallel_insert_max: int = 64


RUNTIME_DEFAULTS = RuntimeDefaults()
RUNTIME_LIMITS = RuntimeLimits()


def default_column_sql(name: str) -> str:
    value = getattr(RUNTIME_DEFAULTS, name)
    column_type = "FLOAT" if isinstance(value, float) else "INTEGER"
    return f"{column_type} DEFAULT {value} NOT NULL"
```

- [x] **Step 4: Wire settings schema to the canonical defaults**

In `backend/src/ragstudio/schemas/settings.py`, import the new registry:

```python
from ragstudio.services.runtime_defaults import RUNTIME_DEFAULTS, RUNTIME_LIMITS
```

Replace the local constants with compatibility aliases:

```python
MINERU_DEFAULT_TIMEOUT_MS = RUNTIME_DEFAULTS.mineru_timeout_ms
RUNTIME_TIMEOUT_MIN_MS = RUNTIME_LIMITS.timeout_min_ms
RUNTIME_TIMEOUT_MAX_MS = RUNTIME_LIMITS.timeout_max_ms
```

Replace numeric defaults and bounds in `SettingsProfileIn` with `RUNTIME_DEFAULTS` and `RUNTIME_LIMITS`. Example replacements:

```python
llm_timeout_ms: int = Field(
    default=RUNTIME_DEFAULTS.llm_timeout_ms,
    ge=RUNTIME_LIMITS.timeout_min_ms,
    le=RUNTIME_LIMITS.timeout_max_ms,
)
embedding_dimensions: int = Field(
    default=RUNTIME_DEFAULTS.embedding_dimensions,
    ge=1,
    le=RUNTIME_LIMITS.embedding_dimensions_max,
)
top_k: int = Field(default=RUNTIME_DEFAULTS.top_k, ge=1, le=RUNTIME_LIMITS.top_k_max)
cosine_better_than_threshold: float = Field(
    default=RUNTIME_DEFAULTS.cosine_better_than_threshold,
    ge=0,
    le=1,
)
```

- [x] **Step 5: Wire ORM and services to the canonical defaults**

In `backend/src/ragstudio/db/models.py`, import:

```python
from ragstudio.services.runtime_defaults import RUNTIME_DEFAULTS
```

Replace profile defaults such as:

```python
llm_timeout_ms: Mapped[int] = mapped_column(Integer, default=RUNTIME_DEFAULTS.llm_timeout_ms)
embedding_dimensions: Mapped[int] = mapped_column(
    Integer,
    default=RUNTIME_DEFAULTS.embedding_dimensions,
)
cosine_better_than_threshold: Mapped[float] = mapped_column(
    Float,
    default=RUNTIME_DEFAULTS.cosine_better_than_threshold,
)
```

In `backend/src/ragstudio/db/engine.py`, import:

```python
from ragstudio.services.runtime_defaults import RUNTIME_DEFAULTS, default_column_sql
```

Use `default_column_sql(...)` for the runtime profile column repair map:

```python
"llm_timeout_ms": default_column_sql("llm_timeout_ms"),
"embedding_timeout_ms": default_column_sql("embedding_timeout_ms"),
"embedding_dimensions": default_column_sql("embedding_dimensions"),
"embedding_batch_size": default_column_sql("embedding_batch_size"),
"mineru_timeout_ms": default_column_sql("mineru_timeout_ms"),
"mineru_poll_interval_ms": default_column_sql("mineru_poll_interval_ms"),
"vision_timeout_ms": default_column_sql("vision_timeout_ms"),
"reranker_timeout_ms": default_column_sql("reranker_timeout_ms"),
"chunk_token_size": default_column_sql("chunk_token_size"),
"chunk_overlap_token_size": default_column_sql("chunk_overlap_token_size"),
"max_context_tokens": default_column_sql("max_context_tokens"),
"top_k": default_column_sql("top_k"),
"chunk_top_k": default_column_sql("chunk_top_k"),
"cosine_better_than_threshold": default_column_sql("cosine_better_than_threshold"),
"max_total_tokens": default_column_sql("max_total_tokens"),
"max_entity_tokens": default_column_sql("max_entity_tokens"),
"max_relation_tokens": default_column_sql("max_relation_tokens"),
```

Replace the MinerU repair SQL literal with an f-string using `RUNTIME_DEFAULTS.mineru_timeout_ms`.

In `settings_service.py` and `runtime_profile_service.py`, import `RUNTIME_DEFAULTS` and replace fallback expressions such as `profile.top_k or 40` with `profile.top_k or RUNTIME_DEFAULTS.top_k`.

- [x] **Step 6: Run focused backend tests**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; pytest backend/tests/test_settings.py backend/tests/test_runtime_profile_service.py -q
```

Expected: PASS.

- [x] **Step 7: Commit runtime defaults registry**

Run:

```powershell
git add backend/src/ragstudio/services/runtime_defaults.py backend/src/ragstudio/schemas/settings.py backend/src/ragstudio/db/models.py backend/src/ragstudio/db/engine.py backend/src/ragstudio/services/settings_service.py backend/src/ragstudio/services/runtime_profile_service.py backend/tests/test_settings.py backend/tests/test_runtime_profile_service.py
git commit -m "refactor: centralize runtime defaults"
```

Expected: commit succeeds with only runtime default files staged.

---

### Task 2: Retrieval Scoring Policy Objects

**Files:**
- Create: `backend/src/ragstudio/services/retrieval_policy.py`
- Modify: `backend/src/ragstudio/services/hybrid_chunk_search.py`
- Modify: `backend/src/ragstudio/services/retrieval_fusion.py`
- Modify: `backend/src/ragstudio/services/layout_neighbor_service.py`
- Modify: `backend/src/ragstudio/services/context_window_service.py`
- Modify: `backend/src/ragstudio/services/retrieval_route_planner.py`
- Test: `backend/tests/test_hybrid_chunk_search_arabic.py`
- Test: `backend/tests/test_rag_retrieval_fusion.py`
- Test: `backend/tests/test_layout_neighbor_service.py`
- Test: `backend/tests/test_context_window_service.py`
- Test: `backend/tests/test_retrieval_route_planner.py`

- [x] **Step 1: Write failing tests for policy export and current values**

Create `backend/tests/test_retrieval_policy.py`:

```python
from ragstudio.services.retrieval_policy import (
    DEFAULT_RETRIEVAL_POLICY,
    FusionScorePolicy,
    HybridScorePolicy,
    LayoutNeighborPolicy,
    RoutePlanningPolicy,
)


def test_hybrid_score_policy_preserves_current_weights() -> None:
    policy = HybridScorePolicy()

    assert policy.reference_exact == 100.0
    assert policy.same_chapter_reference_query == 60.0
    assert policy.same_chapter_with_verse_query == 5.0
    assert policy.neighbor_match == 30.0
    assert policy.term_coverage_multiplier == 10.0
    assert policy.semantic_density_multiplier == 2.0
    assert policy.metadata_boost_cap == 12.0
    assert policy.layout_context_cap == 16.0
    assert policy.arabic_exact == 40.0
    assert policy.arabic_token == 24.0
    assert policy.answer_bearing_count == 30.0
    assert policy.guidance_request == 40.0
    assert policy.exact_query_phrase == 8.0
    assert policy.answer_bearing_phrase == 24.0


def test_fusion_policy_preserves_current_priorities() -> None:
    policy = FusionScorePolicy()

    assert policy.rrf_k == 60
    assert policy.direct_priority["reference_exact"] == 100
    assert policy.direct_priority["arabic_exact"] == 90
    assert policy.direct_priority["target_phrase"] == 80
    assert policy.lane_priority["metadata"] == 40
    assert policy.lane_priority["graph"] == 30
    assert policy.direct_boost["reference_exact"] == 100.0


def test_layout_and_route_policies_preserve_current_thresholds() -> None:
    assert LayoutNeighborPolicy().vertical_proximity == 150.0
    assert RoutePlanningPolicy().lane_timeout_ms(None) == 8000
    assert RoutePlanningPolicy().lane_timeout_ms(10_000) == 3500
    assert DEFAULT_RETRIEVAL_POLICY.policy_version == "2026-05-24"
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; pytest backend/tests/test_retrieval_policy.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.retrieval_policy'`.

- [x] **Step 3: Add retrieval policy module**

Create `backend/src/ragstudio/services/retrieval_policy.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class HybridScorePolicy:
    reference_exact: float = 100.0
    same_chapter_reference_query: float = 60.0
    same_chapter_with_verse_query: float = 5.0
    neighbor_match: float = 30.0
    term_coverage_multiplier: float = 10.0
    semantic_density_multiplier: float = 2.0
    metadata_boost_cap: float = 12.0
    metadata_title_term_multiplier: float = 2.0
    layout_context_cap: float = 16.0
    layout_context_term_multiplier: float = 4.0
    arabic_exact: float = 40.0
    arabic_token: float = 24.0
    answer_bearing_count: float = 30.0
    guidance_request: float = 40.0
    exact_query_phrase: float = 8.0
    answer_bearing_phrase: float = 24.0


@dataclass(frozen=True, slots=True)
class FusionScorePolicy:
    rrf_k: int = 60
    direct_priority: dict[str, int] = field(
        default_factory=lambda: {
            "reference_hypothesis": 5,
            "reference_exact": 100,
            "arabic_exact": 90,
            "target_phrase": 80,
            "reference_tool": 70,
            "lexical_tool": 60,
            "pgvector": 20,
            "default": 10,
        }
    )
    lane_priority: dict[str, int] = field(
        default_factory=lambda: {
            "metadata": 40,
            "reference_exact": 40,
            "arabic_lexical": 35,
            "lexical": 35,
            "graph": 30,
            "pgvector": 20,
            "native": 10,
            "default": 0,
        }
    )
    direct_boost: dict[str, float] = field(
        default_factory=lambda: {
            "reference_exact": 100.0,
            "arabic_exact": 90.0,
            "target_phrase": 80.0,
        }
    )


@dataclass(frozen=True, slots=True)
class LayoutNeighborPolicy:
    vertical_proximity: float = 150.0
    base_score: float = 9.0
    base_boost_score: float = 1.5
    base_final_score: float = 10.5
    spatial_proximity_boost: float = 1.0
    layout_group_boost: float = 2.0
    reading_order_neighbor_boost: float = 1.0


@dataclass(frozen=True, slots=True)
class ContextWindowPolicy:
    base_score: float = 8.0
    boost_score: float = 1.0
    final_score: float = 9.0


@dataclass(frozen=True, slots=True)
class RoutePlanningPolicy:
    default_lane_timeout_ms: int = 8_000
    min_lane_timeout_ms: int = 250
    response_budget_fraction: float = 0.35

    def lane_timeout_ms(self, response_budget_ms: int | None) -> int:
        if response_budget_ms is None:
            return self.default_lane_timeout_ms
        budget = int(response_budget_ms * self.response_budget_fraction)
        return max(self.min_lane_timeout_ms, min(budget, self.default_lane_timeout_ms))


@dataclass(frozen=True, slots=True)
class RetrievalPolicy:
    policy_version: str = "2026-05-24"
    hybrid: HybridScorePolicy = field(default_factory=HybridScorePolicy)
    fusion: FusionScorePolicy = field(default_factory=FusionScorePolicy)
    layout_neighbor: LayoutNeighborPolicy = field(default_factory=LayoutNeighborPolicy)
    context_window: ContextWindowPolicy = field(default_factory=ContextWindowPolicy)
    route_planning: RoutePlanningPolicy = field(default_factory=RoutePlanningPolicy)


DEFAULT_RETRIEVAL_POLICY = RetrievalPolicy()
```

- [x] **Step 4: Replace hybrid search literals with policy references**

In `backend/src/ragstudio/services/hybrid_chunk_search.py`, import:

```python
from ragstudio.services.retrieval_policy import DEFAULT_RETRIEVAL_POLICY, HybridScorePolicy
```

Update class construction:

```python
class HybridChunkSearch:
    def __init__(self, policy: HybridScorePolicy | None = None) -> None:
        self.policy = policy or DEFAULT_RETRIEVAL_POLICY.hybrid
```

Replace score literals with `self.policy` values. Examples:

```python
reference_exact = self.policy.reference_exact
same_chapter = (
    self.policy.same_chapter_reference_query
    if q_verse is None
    else self.policy.same_chapter_with_verse_query
)
neighbor_match = self.policy.neighbor_match
"term_coverage": coverage * self.policy.term_coverage_multiplier,
"semantic_density": density * self.policy.semantic_density_multiplier,
return min(boost, self.policy.metadata_boost_cap)
return min(
    self.policy.layout_context_cap,
    len(overlap) * self.policy.layout_context_term_multiplier,
)
return self.policy.arabic_exact
return self.policy.arabic_token
return self.policy.answer_bearing_count
return self.policy.guidance_request
return self.policy.exact_query_phrase
return self.policy.answer_bearing_phrase
```

- [x] **Step 5: Replace fusion and context literals with policy references**

In `retrieval_fusion.py`, import:

```python
from ragstudio.services.retrieval_policy import DEFAULT_RETRIEVAL_POLICY, FusionScorePolicy
```

Update `RetrievalFusion`:

```python
class RetrievalFusion:
    def __init__(self, policy: FusionScorePolicy | None = None) -> None:
        self.policy = policy or DEFAULT_RETRIEVAL_POLICY.fusion
```

Use `self.policy.rrf_k` in the RRF formula and add `"policy_version": DEFAULT_RETRIEVAL_POLICY.policy_version` to `fusion_score_basis`.

Refactor helper functions to accept the policy:

```python
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
```

Apply the same pattern to `_lane_priority`, `_duplicate_winner`, and `_direct_boost`.

In `layout_neighbor_service.py`, import `DEFAULT_RETRIEVAL_POLICY`, set `policy = DEFAULT_RETRIEVAL_POLICY.layout_neighbor`, and replace `150.0`, `9.0`, `1.5`, `10.5`, `1.0`, and `2.0`.

In `context_window_service.py`, import `DEFAULT_RETRIEVAL_POLICY`, set `policy = DEFAULT_RETRIEVAL_POLICY.context_window`, and replace `base_score=8.0`, `boost_score=1.0`, and `final_score=9.0`.

In `retrieval_route_planner.py`, import `DEFAULT_RETRIEVAL_POLICY` and replace `_lane_timeout_ms` with:

```python
def _lane_timeout_ms(response_budget_ms: int | None) -> int:
    return DEFAULT_RETRIEVAL_POLICY.route_planning.lane_timeout_ms(response_budget_ms)
```

- [x] **Step 6: Run retrieval policy tests**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; pytest backend/tests/test_retrieval_policy.py backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_rag_retrieval_fusion.py backend/tests/test_layout_neighbor_service.py backend/tests/test_context_window_service.py backend/tests/test_retrieval_route_planner.py -q
```

Expected: PASS.

- [x] **Step 7: Commit retrieval policy refactor**

Run:

```powershell
git add backend/src/ragstudio/services/retrieval_policy.py backend/src/ragstudio/services/hybrid_chunk_search.py backend/src/ragstudio/services/retrieval_fusion.py backend/src/ragstudio/services/layout_neighbor_service.py backend/src/ragstudio/services/context_window_service.py backend/src/ragstudio/services/retrieval_route_planner.py backend/tests/test_retrieval_policy.py backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_rag_retrieval_fusion.py backend/tests/test_layout_neighbor_service.py backend/tests/test_context_window_service.py backend/tests/test_retrieval_route_planner.py
git commit -m "refactor: name retrieval scoring policies"
```

Expected: commit succeeds with only retrieval policy files staged.

---

### Task 3: Prompt Template Registry

**Files:**
- Create: `backend/src/ragstudio/services/prompt_templates.py`
- Modify: `backend/src/ragstudio/services/runtime_answer_service.py`
- Modify: `backend/src/ragstudio/services/llm_reranker_service.py`
- Modify: `backend/src/ragstudio/services/domain_metadata_ai_suggester.py`
- Modify: `backend/src/ragstudio/services/parser_normalization.py`
- Test: `backend/tests/test_domain_metadata_ai_suggester.py`
- Test: `backend/tests/test_parser_normalization.py`
- Test: create `backend/tests/test_prompt_templates.py`

- [x] **Step 1: Write failing tests for prompt metadata**

Create `backend/tests/test_prompt_templates.py`:

```python
from ragstudio.services.prompt_templates import (
    ANSWER_PROMPT,
    AUTOSUGGEST_PROMPT,
    LLM_RERANKER_PROMPT,
    VISION_RECOVERY_PROMPT,
)


def test_prompt_templates_are_named_and_versioned() -> None:
    prompts = [ANSWER_PROMPT, LLM_RERANKER_PROMPT, AUTOSUGGEST_PROMPT, VISION_RECOVERY_PROMPT]

    assert [prompt.prompt_id for prompt in prompts] == [
        "runtime_answer.v1",
        "llm_reranker.v1",
        "domain_metadata_autosuggest.v1",
        "vision_recovery.v1",
    ]
    assert all(prompt.version == "2026-05-24" for prompt in prompts)


def test_answer_prompt_keeps_grounding_contract() -> None:
    assert "Answer only from the provided evidence" in ANSWER_PROMPT.system
    assert "If the evidence does not support an answer" in ANSWER_PROMPT.system


def test_llm_reranker_prompt_keeps_json_contract() -> None:
    assert "Return only a JSON array" in LLM_RERANKER_PROMPT.system
    assert "zero-based" in LLM_RERANKER_PROMPT.system
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; pytest backend/tests/test_prompt_templates.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.prompt_templates'`.

- [x] **Step 3: Add prompt template definitions**

Create `backend/src/ragstudio/services/prompt_templates.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    prompt_id: str
    version: str
    system: str = ""
    user_prefix: str = ""

    def metadata(self) -> dict[str, str]:
        return {"prompt_id": self.prompt_id, "prompt_version": self.version}


ANSWER_PROMPT = PromptTemplate(
    prompt_id="runtime_answer.v1",
    version="2026-05-24",
    system=(
        "Answer only from the provided evidence. Cite evidence by its "
        "label, such as [S1] or [S2]. If the evidence does not support "
        "an answer, say that clearly and do not guess."
    ),
)

LLM_RERANKER_PROMPT = PromptTemplate(
    prompt_id="llm_reranker.v1",
    version="2026-05-24",
    system=(
        "Rank evidence for the user query. Return only a JSON array. "
        "Each item must contain index, score, and reason. Use zero-based "
        "indexes from the provided evidence."
    ),
)

AUTOSUGGEST_PROMPT = PromptTemplate(
    prompt_id="domain_metadata_autosuggest.v1",
    version="2026-05-24",
    user_prefix="You classify documents for a RAG indexing system.",
)

VISION_RECOVERY_PROMPT = PromptTemplate(
    prompt_id="vision_recovery.v1",
    version="2026-05-24",
    user_prefix="Extract visible text from a cropped document block.",
)
```

- [x] **Step 4: Wire runtime answer and LLM reranker prompts**

In `runtime_answer_service.py`, import:

```python
from ragstudio.services.prompt_templates import ANSWER_PROMPT
```

Replace the inline system string with:

```python
{"role": "system", "content": ANSWER_PROMPT.system}
```

Add prompt metadata to the returned usage dictionary:

```python
usage = self._usage(body)
usage.update(ANSWER_PROMPT.metadata())
return self._content(body), usage
```

In `llm_reranker_service.py`, import:

```python
from ragstudio.services.prompt_templates import LLM_RERANKER_PROMPT
```

Replace the inline system string in `_payload` with:

```python
{"role": "system", "content": LLM_RERANKER_PROMPT.system}
```

Add the prompt metadata to payload:

```python
"metadata": LLM_RERANKER_PROMPT.metadata(),
```

- [x] **Step 5: Wire autosuggest and vision prompt metadata without changing prompt text**

In `domain_metadata_ai_suggester.py`, import `AUTOSUGGEST_PROMPT`. At the top of the string returned by `_prompt`, keep the current first sentence and add a comment-free metadata line inside the prompt body:

```python
return f"""{AUTOSUGGEST_PROMPT.user_prefix}
Prompt id: {AUTOSUGGEST_PROMPT.prompt_id}
Prompt version: {AUTOSUGGEST_PROMPT.version}
Be honest. Use only the sampled pages and filename as evidence.
"""
```

After adding those lines, keep the existing prompt body starting at `Do not guess a specific collection unless the pages show it.` unchanged.

In `parser_normalization.py`, import `VISION_RECOVERY_PROMPT` and update `_vision_recovery_prompt` to include:

```python
return (
    f"{VISION_RECOVERY_PROMPT.user_prefix}\n"
    f"Prompt id: {VISION_RECOVERY_PROMPT.prompt_id}\n"
    f"Prompt version: {VISION_RECOVERY_PROMPT.version}\n"
)
```

After adding those lines, keep the existing recovery prompt text that lists block type, page, triggers, existing text, and output JSON unchanged.

- [x] **Step 6: Run prompt tests**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; pytest backend/tests/test_prompt_templates.py backend/tests/test_domain_metadata_ai_suggester.py backend/tests/test_parser_normalization.py -q
```

Expected: PASS.

- [x] **Step 7: Commit prompt template registry**

Run:

```powershell
git add backend/src/ragstudio/services/prompt_templates.py backend/src/ragstudio/services/runtime_answer_service.py backend/src/ragstudio/services/llm_reranker_service.py backend/src/ragstudio/services/domain_metadata_ai_suggester.py backend/src/ragstudio/services/parser_normalization.py backend/tests/test_prompt_templates.py backend/tests/test_domain_metadata_ai_suggester.py backend/tests/test_parser_normalization.py
git commit -m "refactor: version ragstudio prompt templates"
```

Expected: commit succeeds with only prompt-related files staged.

---

### Task 4: Shared Redaction Registry

**Files:**
- Create: `backend/src/ragstudio/services/redaction_registry.py`
- Modify: `backend/src/ragstudio/proof_packet/redaction.py`
- Modify: `backend/src/ragstudio/services/document_parse_evidence_service.py`
- Modify: `backend/src/ragstudio/services/document_parse_evidence_exporter.py`
- Test: create `backend/tests/test_redaction_registry.py`
- Test: `backend/tests/test_proof_packet_validator.py`

- [x] **Step 1: Write failing tests for shared redaction rules**

Create `backend/tests/test_redaction_registry.py`:

```python
from ragstudio.services.redaction_registry import find_redaction_matches, redact_text


def test_shared_redaction_registry_detects_secret_and_private_location() -> None:
    text = (
        "token sk-exampleSecretValue123456 "
        "host http://127.0.0.1:8000 "
        "path C:\\Users\\jihad\\private.txt"
    )

    matches = find_redaction_matches(text)
    rule_ids = {match.rule_id for match in matches}

    assert "openai_key" in rule_ids
    assert "localhost" in rule_ids
    assert "local_absolute_path" in rule_ids


def test_shared_redaction_registry_redacts_values() -> None:
    text = "Authorization: Bearer abcdefghijklmnop and file://private"

    redacted = redact_text(text)

    assert "abcdefghijklmnop" not in redacted
    assert "file://" not in redacted
    assert "[REDACTED:bearer_token]" in redacted
    assert "[REDACTED:file_uri]" in redacted
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; pytest backend/tests/test_redaction_registry.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.redaction_registry'`.

- [x] **Step 3: Add shared redaction registry**

Create `backend/src/ragstudio/services/redaction_registry.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RedactionRule:
    rule_id: str
    pattern: re.Pattern[str]


@dataclass(frozen=True, slots=True)
class RedactionMatch:
    rule_id: str
    start: int
    end: int
    value: str


REDACTION_RULES: tuple[RedactionRule, ...] = (
    RedactionRule("openai_key", re.compile(r"sk-[A-Za-z0-9_-]{8,}")),
    RedactionRule("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    RedactionRule("github_pat", re.compile(r"github_pat_[A-Za-z0-9_]+")),
    RedactionRule("github_token", re.compile(r"ghp_[A-Za-z0-9_]{20,}", re.IGNORECASE)),
    RedactionRule("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]+")),
    RedactionRule("google_api_key", re.compile(r"AIza[0-9A-Za-z_-]{20,}")),
    RedactionRule("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._=-]{6,}\b", re.IGNORECASE)),
    RedactionRule("secret_key_name", re.compile(r"(api[_-]?key|token|secret|password|authorization)", re.IGNORECASE)),
    RedactionRule("localhost", re.compile(r"localhost|127\.0\.0\.1|0\.0\.0\.0")),
    RedactionRule("private_10_net", re.compile(r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}")),
    RedactionRule("private_172_net", re.compile(r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}")),
    RedactionRule("private_192_net", re.compile(r"192\.168\.\d{1,3}\.\d{1,3}")),
    RedactionRule("local_absolute_path", re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\"'\s]+|/Users/[^\s\"']+|/home/[^\s\"']+|/tmp/[^\s\"']+|/var/[^\s\"']+", re.IGNORECASE)),
    RedactionRule("unc_path", re.compile(r"\\\\[^\s\\/:*?\"<>|]+\\[^\s\"']+")),
    RedactionRule("file_uri", re.compile(r"file://")),
)


def find_redaction_matches(text: str) -> list[RedactionMatch]:
    matches: list[RedactionMatch] = []
    for rule in REDACTION_RULES:
        for match in rule.pattern.finditer(text):
            matches.append(
                RedactionMatch(
                    rule_id=rule.rule_id,
                    start=match.start(),
                    end=match.end(),
                    value=match.group(0),
                )
            )
    return sorted(matches, key=lambda item: (item.start, item.end, item.rule_id))


def redact_text(text: str) -> str:
    redacted = text
    for rule in REDACTION_RULES:
        redacted = rule.pattern.sub(f"[REDACTED:{rule.rule_id}]", redacted)
    return redacted
```

- [x] **Step 4: Wire proof and document evidence code to the registry**

In `backend/src/ragstudio/proof_packet/redaction.py`, replace the local rule tuple with adapters over `REDACTION_RULES`:

```python
from ragstudio.services.redaction_registry import REDACTION_RULES

RULES = tuple(RedactionRule(rule.rule_id, rule.pattern) for rule in REDACTION_RULES)
```

In `document_parse_evidence_service.py`, import `redact_text` and `find_redaction_matches`. Use `redact_text` in preview text scrubbing, preserving the existing `TEXT_PREVIEW_LIMIT`.

In `document_parse_evidence_exporter.py`, replace local `_PUBLIC_SAFETY_PATTERNS` with `find_redaction_matches` and emit the existing `"secret-shaped value"` or `"local absolute path"` labels by mapping rule IDs:

```python
PUBLIC_SAFETY_LABELS = {
    "local_absolute_path": "local absolute path",
    "unc_path": "local absolute path",
    "openai_key": "secret-shaped value",
    "github_token": "secret-shaped value",
    "github_pat": "secret-shaped value",
    "bearer_token": "secret-shaped value",
}
```

- [x] **Step 5: Run redaction tests**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; pytest backend/tests/test_redaction_registry.py backend/tests/test_proof_packet_validator.py -q
```

Expected: PASS.

- [x] **Step 6: Commit shared redaction registry**

Run:

```powershell
git add backend/src/ragstudio/services/redaction_registry.py backend/src/ragstudio/proof_packet/redaction.py backend/src/ragstudio/services/document_parse_evidence_service.py backend/src/ragstudio/services/document_parse_evidence_exporter.py backend/tests/test_redaction_registry.py backend/tests/test_proof_packet_validator.py
git commit -m "refactor: share public safety redaction rules"
```

Expected: commit succeeds with only redaction files staged.

---

### Task 5: Defaults API For Frontend Synchronization

**Files:**
- Create: `backend/src/ragstudio/schemas/defaults.py`
- Create: `backend/src/ragstudio/api/routes/defaults.py`
- Modify: `backend/src/ragstudio/app.py`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/features/settings/settings-page.tsx`
- Modify: `frontend/src/features/variants/variants-page.tsx`
- Test: create `backend/tests/test_defaults_api.py`
- Test: `frontend/tests/api-client.test.ts`
- Test: `frontend/tests/settings-page.test.tsx`
- Test: `frontend/tests/variants-page.test.tsx`

- [x] **Step 1: Write failing backend API test**

Create `backend/tests/test_defaults_api.py`:

```python
from fastapi.testclient import TestClient

from ragstudio.app import create_app
from ragstudio.services.runtime_defaults import RUNTIME_DEFAULTS


def test_defaults_api_returns_runtime_defaults() -> None:
    client = TestClient(create_app())

    response = client.get("/api/defaults")

    assert response.status_code == 200
    body = response.json()
    assert body["runtime"]["top_k"] == RUNTIME_DEFAULTS.top_k
    assert body["runtime"]["chunk_top_k"] == RUNTIME_DEFAULTS.chunk_top_k
    assert body["runtime"]["max_context_tokens"] == RUNTIME_DEFAULTS.max_context_tokens
    assert body["runtime"]["cosine_better_than_threshold"] == (
        RUNTIME_DEFAULTS.cosine_better_than_threshold
    )
    assert body["policy_versions"]["retrieval"] == "2026-05-24"
```

- [x] **Step 2: Run backend test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; pytest backend/tests/test_defaults_api.py -q
```

Expected: FAIL with `404 Not Found` for `/api/defaults`.

- [x] **Step 3: Add defaults schema and route**

Create `backend/src/ragstudio/schemas/defaults.py`:

```python
from __future__ import annotations

from pydantic import BaseModel


class RuntimeDefaultsOut(BaseModel):
    llm_timeout_ms: int
    embedding_timeout_ms: int
    embedding_dimensions: int
    embedding_batch_size: int
    mineru_timeout_ms: int
    mineru_poll_interval_ms: int
    mineru_max_concurrent_files: int
    vision_timeout_ms: int
    reranker_timeout_ms: int
    chunk_token_size: int
    chunk_overlap_token_size: int
    context_window: int
    max_context_tokens: int
    top_k: int
    chunk_top_k: int
    cosine_better_than_threshold: float
    max_total_tokens: int
    max_entity_tokens: int
    max_relation_tokens: int
    llm_model_max_async: int
    embedding_func_max_async: int
    max_parallel_insert: int


class DefaultsOut(BaseModel):
    runtime: RuntimeDefaultsOut
    policy_versions: dict[str, str]
```

Create `backend/src/ragstudio/api/routes/defaults.py`:

```python
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter

from ragstudio.schemas.defaults import DefaultsOut, RuntimeDefaultsOut
from ragstudio.services.retrieval_policy import DEFAULT_RETRIEVAL_POLICY
from ragstudio.services.runtime_defaults import RUNTIME_DEFAULTS

router = APIRouter(prefix="/defaults", tags=["defaults"])


@router.get("", response_model=DefaultsOut)
async def get_defaults() -> DefaultsOut:
    return DefaultsOut(
        runtime=RuntimeDefaultsOut(**asdict(RUNTIME_DEFAULTS)),
        policy_versions={"retrieval": DEFAULT_RETRIEVAL_POLICY.policy_version},
    )
```

In `backend/src/ragstudio/app.py`, import and register the route:

```python
from ragstudio.api.routes import defaults
```

```python
app.include_router(defaults.router, prefix="/api")
```

- [x] **Step 4: Add frontend client method and tests**

In `frontend/src/api/client.ts`, add types:

```typescript
export interface RuntimeDefaultsOut {
  llm_timeout_ms: number;
  embedding_timeout_ms: number;
  embedding_dimensions: number;
  embedding_batch_size: number;
  mineru_timeout_ms: number;
  mineru_poll_interval_ms: number;
  mineru_max_concurrent_files: number;
  vision_timeout_ms: number;
  reranker_timeout_ms: number;
  chunk_token_size: number;
  chunk_overlap_token_size: number;
  context_window: number;
  max_context_tokens: number;
  top_k: number;
  chunk_top_k: number;
  cosine_better_than_threshold: number;
  max_total_tokens: number;
  max_entity_tokens: number;
  max_relation_tokens: number;
  llm_model_max_async: number;
  embedding_func_max_async: number;
  max_parallel_insert: number;
}

export interface DefaultsOut {
  runtime: RuntimeDefaultsOut;
  policy_versions: Record<string, string>;
}
```

Add the client method:

```typescript
defaults: () => request<DefaultsOut>("/api/defaults"),
```

Append to `frontend/tests/api-client.test.ts`:

```typescript
it("fetches runtime defaults", async () => {
  mockFetchJson({
    runtime: { top_k: 40, chunk_top_k: 20, max_context_tokens: 2000 },
    policy_versions: { retrieval: "2026-05-24" },
  });

  const result = await apiClient.defaults();

  expect(fetch).toHaveBeenCalledWith("/api/defaults", expect.any(Object));
  expect(result.policy_versions.retrieval).toBe("2026-05-24");
});
```

- [x] **Step 5: Use API defaults in settings page without changing visible behavior**

In `frontend/src/features/settings/settings-page.tsx`, add:

```typescript
const defaultsQuery = useQuery({
  queryKey: ["defaults"],
  queryFn: apiClient.defaults,
  staleTime: 60_000,
});

const runtimeDefaults = defaultsQuery.data?.runtime ?? SETTINGS_DEFAULTS;
```

Replace fallback calls like:

```typescript
numberValue("top_k", 40)
onBlur={() => commitNumberField("top_k", 40)}
```

with:

```typescript
numberValue("top_k", runtimeDefaults.top_k)
onBlur={() => commitNumberField("top_k", runtimeDefaults.top_k)}
```

Keep `SETTINGS_DEFAULTS` as a local offline fallback with the same values so the page still renders if `/api/defaults` is unavailable.

- [x] **Step 6: Clarify variant presets are UI presets**

In `frontend/src/features/variants/variants-page.tsx`, rename:

```typescript
const presets = {
```

to:

```typescript
const uiVariantPresets = {
```

Update usages of `presets` to `uiVariantPresets`. This keeps current values and makes the file's hardcoded items accurately scoped to UI presets rather than runtime defaults.

- [x] **Step 7: Run backend and frontend tests**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; pytest backend/tests/test_defaults_api.py backend/tests/test_settings.py -q
```

Expected: PASS.

Run:

```powershell
cd frontend; npm test -- api-client.test.ts settings-page.test.tsx variants-page.test.tsx --runInBand
```

Expected: PASS. If this project uses Vitest without `--runInBand`, run `npm test -- api-client.test.ts settings-page.test.tsx variants-page.test.tsx`.

- [x] **Step 8: Regenerate OpenAPI bindings if the project expects generated API drift to be committed**

Run:

```powershell
.\scripts\generate-openapi.sh
```

Expected: OpenAPI schema updates include `/api/defaults`. If the shell script cannot run in PowerShell, run it from Git Bash.

- [x] **Step 9: Commit defaults API and frontend sync**

Run:

```powershell
git add backend/src/ragstudio/schemas/defaults.py backend/src/ragstudio/api/routes/defaults.py backend/src/ragstudio/app.py backend/tests/test_defaults_api.py frontend/src/api/client.ts frontend/src/features/settings/settings-page.tsx frontend/src/features/variants/variants-page.tsx frontend/tests/api-client.test.ts frontend/tests/settings-page.test.tsx frontend/tests/variants-page.test.tsx
git commit -m "feat: expose runtime defaults to frontend"
```

Expected: commit succeeds with only defaults API and frontend sync files staged.

---

### Task 6: Operational And Evaluation Policy Registry

**Files:**
- Create: `backend/src/ragstudio/services/operational_policy.py`
- Modify: `backend/src/ragstudio/api/upload_utils.py`
- Modify: `backend/src/ragstudio/workers/index_worker.py`
- Modify: `backend/src/ragstudio/services/background_runner_factory.py`
- Modify: `backend/src/ragstudio/services/chunk_persistence_service.py`
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Modify: `backend/src/ragstudio/services/candidate_diversity.py`
- Modify: `backend/src/ragstudio/services/retrieval_metrics.py`
- Modify: `backend/src/ragstudio/services/scoring_service.py`
- Modify: `backend/src/ragstudio/schemas/variants.py`
- Test: create `backend/tests/test_operational_policy.py`
- Test: `backend/tests/test_experiments_scoring.py`
- Test: `backend/tests/test_retrieval_metrics.py`

- [x] **Step 1: Write failing tests for operational policy values**

Create `backend/tests/test_operational_policy.py`:

```python
from ragstudio.services.operational_policy import DEFAULT_OPERATIONAL_POLICY


def test_operational_policy_preserves_current_limits() -> None:
    policy = DEFAULT_OPERATIONAL_POLICY

    assert policy.upload.max_upload_bytes == 25 * 1024 * 1024
    assert policy.upload.upload_chunk_bytes == 1024 * 1024
    assert policy.worker.lease_seconds == 300
    assert policy.chunk_persistence.min_expected_chunks == 2
    assert policy.chunk_persistence.max_expected_chunks == 5000
    assert policy.chunk_persistence.persist_batch_size == 500
    assert policy.chunk_search.fallback_candidate_limit == 100
    assert policy.candidate_diversity.similarity_threshold == 0.65


def test_evaluation_and_retrieval_gate_defaults_are_named() -> None:
    policy = DEFAULT_OPERATIONAL_POLICY

    assert policy.evaluation.expected_answer_weight == 50.0
    assert policy.evaluation.must_include_weight == 35.0
    assert policy.evaluation.must_avoid_weight == 15.0
    assert policy.retrieval_metrics.min_precision_at_k == 0.75
    assert policy.retrieval_metrics.min_recall_at_k == 0.70
    assert policy.retrieval_metrics.min_mrr == 0.80
    assert policy.retrieval_metrics.min_hit_rate == 1.0


def test_variant_presets_are_backend_policy_not_ui_only() -> None:
    policy = DEFAULT_OPERATIONAL_POLICY

    assert policy.variant_presets["balanced"] == {
        "top_k": 5,
        "temperature": 0.2,
        "enable_rerank": True,
    }
    assert policy.variant_presets["fast"] == {
        "top_k": 4,
        "temperature": 0.0,
        "enable_rerank": False,
    }
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; pytest backend/tests/test_operational_policy.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.operational_policy'`.

- [x] **Step 3: Add operational policy module**

Create `backend/src/ragstudio/services/operational_policy.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class UploadPolicy:
    max_upload_bytes: int = 25 * 1024 * 1024
    upload_chunk_bytes: int = 1024 * 1024


@dataclass(frozen=True, slots=True)
class WorkerPolicy:
    lease_seconds: int = 300
    job_max_attempts: int = 3


@dataclass(frozen=True, slots=True)
class ChunkPersistencePolicy:
    min_expected_chunks: int = 2
    max_expected_chunks: int = 5000
    persist_batch_size: int = 500


@dataclass(frozen=True, slots=True)
class ChunkSearchPolicy:
    fallback_candidate_limit: int = 100


@dataclass(frozen=True, slots=True)
class CandidateDiversityPolicy:
    similarity_threshold: float = 0.65


@dataclass(frozen=True, slots=True)
class RetrievalMetricGatePolicy:
    min_precision_at_k: float = 0.75
    min_recall_at_k: float = 0.70
    min_mrr: float = 0.80
    min_hit_rate: float = 1.0


@dataclass(frozen=True, slots=True)
class EvaluationScoringPolicy:
    expected_answer_weight: float = 50.0
    must_include_weight: float = 35.0
    must_avoid_weight: float = 15.0


@dataclass(frozen=True, slots=True)
class OperationalPolicy:
    policy_version: str = "2026-05-24"
    upload: UploadPolicy = field(default_factory=UploadPolicy)
    worker: WorkerPolicy = field(default_factory=WorkerPolicy)
    chunk_persistence: ChunkPersistencePolicy = field(default_factory=ChunkPersistencePolicy)
    chunk_search: ChunkSearchPolicy = field(default_factory=ChunkSearchPolicy)
    candidate_diversity: CandidateDiversityPolicy = field(default_factory=CandidateDiversityPolicy)
    retrieval_metrics: RetrievalMetricGatePolicy = field(default_factory=RetrievalMetricGatePolicy)
    evaluation: EvaluationScoringPolicy = field(default_factory=EvaluationScoringPolicy)
    variant_presets: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {
            "balanced": {"top_k": 5, "temperature": 0.2, "enable_rerank": True},
            "precise": {"top_k": 3, "temperature": 0.1, "enable_rerank": True},
            "broad": {"top_k": 12, "temperature": 0.3, "enable_rerank": True},
            "fast": {"top_k": 4, "temperature": 0.0, "enable_rerank": False},
        }
    )


DEFAULT_OPERATIONAL_POLICY = OperationalPolicy()
```

- [x] **Step 4: Replace operational literals with policy references**

In `backend/src/ragstudio/api/upload_utils.py`, import:

```python
from ragstudio.services.operational_policy import DEFAULT_OPERATIONAL_POLICY
```

Replace the upload constants:

```python
MAX_UPLOAD_BYTES = DEFAULT_OPERATIONAL_POLICY.upload.max_upload_bytes
UPLOAD_CHUNK_BYTES = DEFAULT_OPERATIONAL_POLICY.upload.upload_chunk_bytes
```

In `backend/src/ragstudio/workers/index_worker.py`, import `DEFAULT_OPERATIONAL_POLICY` and replace default arguments:

```python
lease_seconds: int = DEFAULT_OPERATIONAL_POLICY.worker.lease_seconds,
```

In `backend/src/ragstudio/services/background_runner_factory.py`, import `DEFAULT_OPERATIONAL_POLICY` and replace:

```python
lease_seconds: int = DEFAULT_OPERATIONAL_POLICY.worker.lease_seconds,
```

In `backend/src/ragstudio/services/chunk_persistence_service.py`, import `DEFAULT_OPERATIONAL_POLICY` and replace:

```python
_MIN_EXPECTED_CHUNKS = DEFAULT_OPERATIONAL_POLICY.chunk_persistence.min_expected_chunks
_MAX_EXPECTED_CHUNKS = DEFAULT_OPERATIONAL_POLICY.chunk_persistence.max_expected_chunks
_PERSIST_BATCH_SIZE = DEFAULT_OPERATIONAL_POLICY.chunk_persistence.persist_batch_size
```

In `backend/src/ragstudio/services/chunk_service.py`, replace:

```python
_FALLBACK_SEARCH_CANDIDATE_LIMIT = (
    DEFAULT_OPERATIONAL_POLICY.chunk_search.fallback_candidate_limit
)
```

In `backend/src/ragstudio/services/candidate_diversity.py`, replace the function default with:

```python
similarity_threshold: float = (
    DEFAULT_OPERATIONAL_POLICY.candidate_diversity.similarity_threshold
),
```

- [x] **Step 5: Replace scoring, metric, and variant preset literals**

In `backend/src/ragstudio/services/retrieval_metrics.py`, import `DEFAULT_OPERATIONAL_POLICY` and update the `RetrievalQualityGate` defaults:

```python
min_precision_at_k: float = DEFAULT_OPERATIONAL_POLICY.retrieval_metrics.min_precision_at_k
min_recall_at_k: float = DEFAULT_OPERATIONAL_POLICY.retrieval_metrics.min_recall_at_k
min_mrr: float = DEFAULT_OPERATIONAL_POLICY.retrieval_metrics.min_mrr
min_hit_rate: float = DEFAULT_OPERATIONAL_POLICY.retrieval_metrics.min_hit_rate
```

In `backend/src/ragstudio/services/scoring_service.py`, import `DEFAULT_OPERATIONAL_POLICY` and replace the weights:

```python
policy = DEFAULT_OPERATIONAL_POLICY.evaluation
if expected_terms:
    total += (len(expected_hits) / len(expected_terms)) * policy.expected_answer_weight
    weights += policy.expected_answer_weight
if include_terms:
    total += (len(include_hits) / len(include_terms)) * policy.must_include_weight
    weights += policy.must_include_weight
if avoid_terms:
    total += ((len(avoid_terms) - len(avoid_hits)) / len(avoid_terms)) * policy.must_avoid_weight
    weights += policy.must_avoid_weight
```

In `backend/src/ragstudio/schemas/variants.py`, import `DEFAULT_OPERATIONAL_POLICY` and replace:

```python
VARIANT_PRESET_DEFAULTS = DEFAULT_OPERATIONAL_POLICY.variant_presets
```

- [x] **Step 6: Run operational policy tests**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; pytest backend/tests/test_operational_policy.py backend/tests/test_experiments_scoring.py backend/tests/test_retrieval_metrics.py -q
```

Expected: PASS.

- [x] **Step 7: Commit operational policy registry**

Run:

```powershell
git add backend/src/ragstudio/services/operational_policy.py backend/src/ragstudio/api/upload_utils.py backend/src/ragstudio/workers/index_worker.py backend/src/ragstudio/services/background_runner_factory.py backend/src/ragstudio/services/chunk_persistence_service.py backend/src/ragstudio/services/chunk_service.py backend/src/ragstudio/services/candidate_diversity.py backend/src/ragstudio/services/retrieval_metrics.py backend/src/ragstudio/services/scoring_service.py backend/src/ragstudio/schemas/variants.py backend/tests/test_operational_policy.py backend/tests/test_experiments_scoring.py backend/tests/test_retrieval_metrics.py
git commit -m "refactor: name operational policy defaults"
```

Expected: commit succeeds with only operational policy files staged.

---

### Task 7: Reference And Query Regex Registry

**Files:**
- Create: `backend/src/ragstudio/services/reference_regex_registry.py`
- Modify: `backend/src/ragstudio/services/script_detection.py`
- Modify: `backend/src/ragstudio/services/arabic_text.py`
- Modify: `backend/src/ragstudio/services/reference_metadata.py`
- Modify: `backend/src/ragstudio/services/query_understanding.py`
- Modify: `backend/src/ragstudio/services/query_hypothesis_verifier.py`
- Test: create `backend/tests/test_reference_regex_registry.py`
- Test: `backend/tests/test_domain_metadata_quality_gate.py`
- Test: `backend/tests/test_retrieval_route_input.py`

- [x] **Step 1: Write failing tests for shared built-in regexes**

Create `backend/tests/test_reference_regex_registry.py`:

```python
from ragstudio.services.reference_regex_registry import (
    ARABIC_DIACRITICS_PATTERN,
    ARABIC_TOKEN_PATTERN,
    QUERY_REFERENCE_PATTERN,
    REFERENCE_PATTERN,
    SCRIPT_PATTERNS,
)


def test_script_patterns_preserve_existing_script_detection() -> None:
    assert SCRIPT_PATTERNS["arabic"].search("السلام")
    assert SCRIPT_PATTERNS["latin"].search("Evidence")
    assert SCRIPT_PATTERNS["hebrew"].search("שלום")
    assert SCRIPT_PATTERNS["han"].search("漢字")


def test_arabic_patterns_preserve_token_and_diacritic_behavior() -> None:
    assert ARABIC_TOKEN_PATTERN.findall("abc السلام 123") == ["السلام"]
    assert ARABIC_DIACRITICS_PATTERN.sub("", "قُرْآن") == "قرآن"


def test_reference_patterns_preserve_quran_reference_behavior() -> None:
    match = REFERENCE_PATTERN.search("See 12:13 for the reference")
    assert match is not None
    assert match.group("chapter") == "12"
    assert match.group("verse") == "13"

    verifier_match = QUERY_REFERENCE_PATTERN.search("[12:13]")
    assert verifier_match is not None
    assert verifier_match.group("reference") == "12:13"
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; pytest backend/tests/test_reference_regex_registry.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.reference_regex_registry'`.

- [x] **Step 3: Add shared built-in regex registry**

Create `backend/src/ragstudio/services/reference_regex_registry.py`:

```python
from __future__ import annotations

import re

ARABIC_DIACRITICS_PATTERN = re.compile(
    r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]"
)
ARABIC_TOKEN_PATTERN = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+")

SCRIPT_PATTERNS: dict[str, re.Pattern[str]] = {
    "arabic": re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]"),
    "latin": re.compile(r"[A-Za-z]"),
    "cyrillic": re.compile(r"[\u0400-\u04ff]"),
    "greek": re.compile(r"[\u0370-\u03ff]"),
    "hebrew": re.compile(r"[\u0590-\u05ff]"),
    "devanagari": re.compile(r"[\u0900-\u097f]"),
    "han": re.compile(r"[\u4e00-\u9fff]"),
}

REFERENCE_PATTERN = re.compile(
    r"(?P<prefix>\bQuran\s+)?(?P<bracket>\[)?"
    r"(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})"
    r"(?(bracket)\])",
    flags=re.IGNORECASE,
)
CHAPTER_ONLY_PATTERN = re.compile(r"\b(?:chapter|surah|sura)\s+(?P<chapter>\d{1,4})\b", re.IGNORECASE)
LEGAL_SECTION_PATTERN = re.compile(r"\b(?:section|article|clause)\s+(?P<section>[A-Za-z0-9_.:-]+)\b", re.IGNORECASE)
PAGE_LINE_PATTERN = re.compile(r"\bpage\s+(?P<page>\d{1,5})(?:\s*,?\s*line\s+(?P<line>\d{1,5}))?\b", re.IGNORECASE)
BOOK_HADITH_PATTERN = re.compile(r"\bBook\s+(?P<book>\d+)\s*,?\s*Hadith\s+(?P<hadith>\d+)\b", re.IGNORECASE)

QUERY_ARABIC_PATTERN = re.compile(r"[\u0600-\u06FF]")
QUERY_REFERENCE_PATTERN = re.compile(r"\[(?P<reference>\d{1,3}:\d{1,3})\]")
QUERY_GRAPH_CONTEXT_PATTERN = re.compile(
    r"\b(?:related|relationship|graph|neighbor|neighbour|connected|context)\b",
    re.IGNORECASE,
)
QUERY_PHRASE_PATTERN = re.compile(r'"([^"]{2,160})"')
QUERY_NORMALIZED_PHRASE_PATTERN = re.compile(r"[^0-9A-Za-z\u0600-\u06FF]+")
```

- [x] **Step 4: Wire script and Arabic modules to the registry**

In `backend/src/ragstudio/services/script_detection.py`, replace the local `SCRIPT_PATTERNS` definition with:

```python
from ragstudio.services.reference_regex_registry import SCRIPT_PATTERNS
```

In `backend/src/ragstudio/services/arabic_text.py`, replace local compiled regexes with:

```python
from ragstudio.services.reference_regex_registry import (
    ARABIC_DIACRITICS_PATTERN,
    ARABIC_TOKEN_PATTERN,
)

ARABIC_DIACRITICS = ARABIC_DIACRITICS_PATTERN
ARABIC_TOKEN = ARABIC_TOKEN_PATTERN
```

- [x] **Step 5: Wire reference and query modules to the registry**

In `backend/src/ragstudio/services/reference_metadata.py`, import:

```python
from ragstudio.services.reference_regex_registry import (
    BOOK_HADITH_PATTERN,
    CHAPTER_ONLY_PATTERN,
    LEGAL_SECTION_PATTERN,
    PAGE_LINE_PATTERN,
    REFERENCE_PATTERN,
)
```

Remove the equivalent local compiled regex declarations.

In `backend/src/ragstudio/services/query_understanding.py`, import:

```python
from ragstudio.services.reference_regex_registry import (
    QUERY_ARABIC_PATTERN,
    QUERY_GRAPH_CONTEXT_PATTERN,
    QUERY_NORMALIZED_PHRASE_PATTERN,
    REFERENCE_PATTERN,
)
```

Map local names to registry names where the rest of the file expects local identifiers:

```python
_ARABIC_RE = QUERY_ARABIC_PATTERN
_REFERENCE_RE = REFERENCE_PATTERN
_GRAPH_CONTEXT_RE = QUERY_GRAPH_CONTEXT_PATTERN
_NORMALIZED_PHRASE_RE = QUERY_NORMALIZED_PHRASE_PATTERN
```

In `backend/src/ragstudio/services/query_hypothesis_verifier.py`, replace local `_REFERENCE_RE` with:

```python
from ragstudio.services.reference_regex_registry import QUERY_REFERENCE_PATTERN

_REFERENCE_RE = QUERY_REFERENCE_PATTERN
```

Do not move user-configured regex compilation in `reference_contracts.py`, `reference_query_parser.py`, `reference_contract_validator.py`, or `document_contract.py`; those are contract inputs and should stay close to validation.

- [x] **Step 6: Run regex registry tests**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; pytest backend/tests/test_reference_regex_registry.py backend/tests/test_domain_metadata_quality_gate.py backend/tests/test_retrieval_route_input.py -q
```

Expected: PASS.

- [x] **Step 7: Commit regex registry**

Run:

```powershell
git add backend/src/ragstudio/services/reference_regex_registry.py backend/src/ragstudio/services/script_detection.py backend/src/ragstudio/services/arabic_text.py backend/src/ragstudio/services/reference_metadata.py backend/src/ragstudio/services/query_understanding.py backend/src/ragstudio/services/query_hypothesis_verifier.py backend/tests/test_reference_regex_registry.py backend/tests/test_domain_metadata_quality_gate.py backend/tests/test_retrieval_route_input.py
git commit -m "refactor: share built-in reference regexes"
```

Expected: commit succeeds with only regex registry files staged.

---

### Task 8: Domain, API, Proof, And Query Policy Classification

**Files:**
- Create: `backend/src/ragstudio/services/static_policy_catalog.py`
- Modify: `backend/src/ragstudio/services/domain_profile_registry.py`
- Modify: `backend/src/ragstudio/services/chunk_splitter.py`
- Modify: `backend/src/ragstudio/services/retrieval_evidence.py`
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Modify: `backend/src/ragstudio/services/query_hypothesis_service.py`
- Modify: `backend/src/ragstudio/services/provider_manifest_service.py`
- Modify: `backend/src/ragstudio/services/pdf_preflight_service.py`
- Modify: `backend/src/ragstudio/proof_packet/validator.py`
- Modify: `backend/src/ragstudio/proof_packet/errors.py`
- Test: create `backend/tests/test_static_policy_catalog.py`
- Test: `backend/tests/test_domain_profile_registry.py`
- Test: `backend/tests/test_parser_normalization.py`
- Test: `backend/tests/test_proof_packet_validator.py`

- [x] **Step 1: Write failing tests for the remaining policy catalog**

Create `backend/tests/test_static_policy_catalog.py`:

```python
from ragstudio.services.static_policy_catalog import (
    POLICY_CATALOG_VERSION,
    policy_item,
    policy_items_by_kind,
)


def test_policy_catalog_classifies_remaining_hardcoded_items() -> None:
    assert POLICY_CATALOG_VERSION == "2026-05-24"

    expected_ids = {
        "domain_profile_defaults",
        "chunk_profile_word_targets",
        "block_type_vocabulary",
        "query_hypothesis_protocol_vocabulary",
        "api_pagination_bounds",
        "provider_manifest_vocabulary",
        "pdf_preflight_ratio_policy",
        "proof_packet_protocol_constants",
        "proof_packet_error_codes",
        "retrieval_candidate_expansion",
    }

    assert expected_ids.issubset({item.policy_id for item in policy_items_by_kind()})


def test_policy_catalog_distinguishes_protocol_from_tunable_policy() -> None:
    assert policy_item("proof_packet_protocol_constants").kind == "protocol_constant"
    assert policy_item("proof_packet_error_codes").kind == "protocol_constant"
    assert policy_item("chunk_profile_word_targets").kind == "tunable_policy"
    assert policy_item("api_pagination_bounds").kind == "runtime_default"
    assert policy_item("query_hypothesis_protocol_vocabulary").kind == "protocol_constant"
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; pytest backend/tests/test_static_policy_catalog.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragstudio.services.static_policy_catalog'`.

- [x] **Step 3: Add static policy catalog**

Create `backend/src/ragstudio/services/static_policy_catalog.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PolicyKind = Literal[
    "runtime_default",
    "tunable_policy",
    "protocol_constant",
    "security_policy",
    "ui_fallback",
]

POLICY_CATALOG_VERSION = "2026-05-24"


@dataclass(frozen=True, slots=True)
class StaticPolicyItem:
    policy_id: str
    kind: PolicyKind
    owner: str
    source_paths: tuple[str, ...]
    note: str


STATIC_POLICY_ITEMS: tuple[StaticPolicyItem, ...] = (
    StaticPolicyItem(
        policy_id="domain_profile_defaults",
        kind="tunable_policy",
        owner="domain_profile_registry",
        source_paths=("backend/src/ragstudio/services/domain_profile_registry.py",),
        note="Built-in domain profiles are product defaults; changing them requires route-planner tests.",
    ),
    StaticPolicyItem(
        policy_id="chunk_profile_word_targets",
        kind="tunable_policy",
        owner="chunk_splitter",
        source_paths=("backend/src/ragstudio/services/chunk_splitter.py",),
        note="Word targets and hard caps affect canonical evidence boundaries.",
    ),
    StaticPolicyItem(
        policy_id="block_type_vocabulary",
        kind="protocol_constant",
        owner="block_types",
        source_paths=("backend/src/ragstudio/services/block_types.py",),
        note="Parser block categories define cross-service vocabulary.",
    ),
    StaticPolicyItem(
        policy_id="query_hypothesis_protocol_vocabulary",
        kind="protocol_constant",
        owner="query_hypothesis_service",
        source_paths=("backend/src/ragstudio/services/query_hypothesis_service.py",),
        note="Allowed intents, scripts, term types, domain hints, and answer shapes are parser protocol.",
    ),
    StaticPolicyItem(
        policy_id="api_pagination_bounds",
        kind="runtime_default",
        owner="api_routes",
        source_paths=("backend/src/ragstudio/api/routes/", "backend/src/ragstudio/schemas/"),
        note="List defaults and max page sizes are API behavior, not retrieval scoring.",
    ),
    StaticPolicyItem(
        policy_id="provider_manifest_vocabulary",
        kind="protocol_constant",
        owner="provider_manifest_service",
        source_paths=("backend/src/ragstudio/services/provider_manifest_service.py",),
        note="Manifest sections and capabilities are external provider contract vocabulary.",
    ),
    StaticPolicyItem(
        policy_id="pdf_preflight_ratio_policy",
        kind="tunable_policy",
        owner="pdf_preflight_service",
        source_paths=("backend/src/ragstudio/services/pdf_preflight_service.py",),
        note="Reference-script pass ratios gate parser preflight behavior.",
    ),
    StaticPolicyItem(
        policy_id="proof_packet_protocol_constants",
        kind="protocol_constant",
        owner="proof_packet_validator",
        source_paths=("backend/src/ragstudio/proof_packet/validator.py",),
        note="Packet id, packet root, validator version, and commit length define proof protocol.",
    ),
    StaticPolicyItem(
        policy_id="proof_packet_error_codes",
        kind="protocol_constant",
        owner="proof_packet_errors",
        source_paths=("backend/src/ragstudio/proof_packet/errors.py",),
        note="Error codes and recovery guidance are stable validator output contract.",
    ),
    StaticPolicyItem(
        policy_id="retrieval_candidate_expansion",
        kind="tunable_policy",
        owner="retrieval_evidence",
        source_paths=(
            "backend/src/ragstudio/services/retrieval_evidence.py",
            "backend/src/ragstudio/services/retrieval_orchestrator.py",
        ),
        note="Expansion factors, minimum candidate windows, and seed caps affect recall and latency.",
    ),
)


def policy_items_by_kind(kind: PolicyKind | None = None) -> tuple[StaticPolicyItem, ...]:
    if kind is None:
        return STATIC_POLICY_ITEMS
    return tuple(item for item in STATIC_POLICY_ITEMS if item.kind == kind)


def policy_item(policy_id: str) -> StaticPolicyItem:
    for item in STATIC_POLICY_ITEMS:
        if item.policy_id == policy_id:
            return item
    raise KeyError(f"Unknown static policy item: {policy_id}")
```

- [x] **Step 4: Add policy version constants to remaining protocol/default modules**

In `backend/src/ragstudio/services/domain_profile_registry.py`, add near the type aliases:

```python
DOMAIN_PROFILE_POLICY_VERSION = "2026-05-24"
```

Add a test to `backend/tests/test_domain_profile_registry.py`:

```python
from ragstudio.services.domain_profile_registry import DOMAIN_PROFILE_POLICY_VERSION


def test_domain_profile_policy_version_is_explicit() -> None:
    assert DOMAIN_PROFILE_POLICY_VERSION == "2026-05-24"
```

In `backend/src/ragstudio/services/query_hypothesis_service.py`, add:

```python
QUERY_HYPOTHESIS_PROTOCOL_VERSION = "2026-05-24"
```

Keep `_ALLOWED_INTENTS`, `_ALLOWED_SCRIPTS`, `_ALLOWED_TERM_TYPES`, `_ALLOWED_DOMAIN_HINTS`, `_ALLOWED_ANSWER_SHAPES`, and alias maps in this module because they are protocol vocabulary, not user-tunable scoring knobs.

In `backend/src/ragstudio/proof_packet/validator.py`, add:

```python
PROOF_PACKET_PROTOCOL_VERSION = "2026-05-24"
SOURCE_COMMIT_SHA_LENGTH = 40
```

Replace `len(source_commit) != 40` and `len(source_commit) == 40` with `SOURCE_COMMIT_SHA_LENGTH`.

In `backend/src/ragstudio/proof_packet/errors.py`, add:

```python
PROOF_PACKET_ERROR_PROTOCOL_VERSION = "2026-05-24"
```

- [x] **Step 5: Name remaining tunable chunking and retrieval expansion constants**

In `backend/src/ragstudio/services/chunk_splitter.py`, add near `ChunkProfile`:

```python
REFERENCE_HEAVY_TARGET_WORDS = 500
REFERENCE_HEAVY_HARD_MAX_WORDS = 900
TAFSEER_BOOK_TARGET_WORDS = 1000
LAYOUT_TABLE_TARGET_WORDS = 800
LAYOUT_TABLE_HARD_MAX_WORDS = 1200
SHORT_REFERENCE_TARGET_WORDS = 400
SHORT_REFERENCE_HARD_MAX_WORDS = 800
GENERIC_TARGET_WORDS = 1000
FULL_WIDTH_LAYOUT_RATIO = 0.70
SEMANTIC_SPLIT_LOWER_BOUND_RATIO = 0.55
```

Replace the corresponding inline values in `profile_for(...)`, `_banded_visual_order(...)`, and `_semantic_split_index(...)`.

In `backend/src/ragstudio/services/retrieval_evidence.py`, add:

```python
CANDIDATE_EXPANSION_MULTIPLIER = 2
MIN_EXPANDED_CANDIDATES = 20
```

Replace `candidate_limit=max(limit * 2, 20)` with:

```python
candidate_limit=max(limit * CANDIDATE_EXPANSION_MULTIPLIER, MIN_EXPANDED_CANDIDATES)
```

In `backend/src/ragstudio/services/retrieval_orchestrator.py`, add:

```python
GRAPH_EXPANSION_MAX_SEEDS = 5
DEFAULT_QUERY_LIMIT = 8
```

Replace `max_seeds=5` and `int(query_config.get("limit") or 8)` with those names.

- [x] **Step 6: Classify provider manifest and preflight constants**

In `backend/src/ragstudio/services/provider_manifest_service.py`, add:

```python
PROVIDER_MANIFEST_PROTOCOL_VERSION = "2026-05-24"
```

Keep `SUPPORTED_SECTIONS`, `KNOWN_SECTIONS`, and `CAPABILITIES` in this module, but add a comment directly above them:

```python
# Provider manifest protocol vocabulary; update tests before changing these values.
```

In `backend/src/ragstudio/services/pdf_preflight_service.py`, add:

```python
PDF_PREFLIGHT_POLICY_VERSION = "2026-05-24"
DEFAULT_MIN_REFERENCE_SCRIPT_PASS_RATIO = 0.98
```

Use `DEFAULT_MIN_REFERENCE_SCRIPT_PASS_RATIO` wherever the config fallback currently uses `0.98` or `AppSettings.pdf_ocr_min_reference_script_pass_ratio`.

- [x] **Step 7: Run classification tests**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; pytest backend/tests/test_static_policy_catalog.py backend/tests/test_domain_profile_registry.py backend/tests/test_parser_normalization.py backend/tests/test_proof_packet_validator.py -q
```

Expected: PASS.

- [x] **Step 8: Commit static policy classification**

Run:

```powershell
git add backend/src/ragstudio/services/static_policy_catalog.py backend/src/ragstudio/services/domain_profile_registry.py backend/src/ragstudio/services/chunk_splitter.py backend/src/ragstudio/services/retrieval_evidence.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/src/ragstudio/services/query_hypothesis_service.py backend/src/ragstudio/services/provider_manifest_service.py backend/src/ragstudio/services/pdf_preflight_service.py backend/src/ragstudio/proof_packet/validator.py backend/src/ragstudio/proof_packet/errors.py backend/tests/test_static_policy_catalog.py backend/tests/test_domain_profile_registry.py backend/tests/test_parser_normalization.py backend/tests/test_proof_packet_validator.py
git commit -m "docs: classify remaining hardcoded policies"
```

Expected: commit succeeds with only static policy classification files staged.

---

### Task 9: Documentation And Final Verification

**Files:**
- Modify: `docs/superpowers/plans/2026-05-24-hardcoded-policy-improvements.md`
- Create or Modify: `docs/architecture/hardcoded-policy-inventory.md` if `docs/architecture/` exists; otherwise create `docs/hardcoded-policy-inventory.md`
- Test: focused backend and frontend test commands from this task.

- [x] **Step 1: Write the architecture note**

Create `docs/hardcoded-policy-inventory.md` if there is no existing `docs/architecture/` directory. Use this content:

```markdown
# Hardcoded Policy Inventory

Ragstudio keeps product runtime defaults, retrieval policy, prompts, and public-safety redaction rules in named modules so behavior can be inspected and tested before tuning.

## Standard Defaults

- Runtime defaults live in `backend/src/ragstudio/services/runtime_defaults.py`.
- Retrieval scoring defaults live in `backend/src/ragstudio/services/retrieval_policy.py`.
- Prompt identifiers and versions live in `backend/src/ragstudio/services/prompt_templates.py`.
- Public-safety redaction rules live in `backend/src/ragstudio/services/redaction_registry.py`.
- Operational limits and eval weights live in `backend/src/ragstudio/services/operational_policy.py`.
- Built-in script/reference/query regexes live in `backend/src/ragstudio/services/reference_regex_registry.py`.
- Remaining protocol constants and product policies are classified in `backend/src/ragstudio/services/static_policy_catalog.py`.

## Design Rules

- Changing a retrieval score requires a focused test that asserts ordering and trace metadata.
- Changing prompt wording requires a prompt version update and a test for the required output contract.
- Changing redaction rules requires proof-packet and document-evidence safety tests.
- Frontend runtime defaults should come from `/api/defaults`; local values are offline fallbacks only.

## Remaining Tunable Areas

- Domain-specific lexical adapters should own corpus-specific synonyms and reference behavior.
- Layout proximity and chunking thresholds should become domain-profile options when eval coverage exists.
- Evaluation scoring should keep the current substring scorer as a baseline and add rubric-specific adapters separately.
- User-provided custom regexes should remain validated by document/reference contract compilers, not promoted to global built-ins.
- Proof packet IDs, proof error codes, provider manifest vocabulary, query-hypothesis vocabularies, and block-type vocabularies are protocol constants. Do not tune them like scoring weights.
```

- [x] **Step 2: Run backend verification**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; pytest backend/tests/test_settings.py backend/tests/test_runtime_profile_service.py backend/tests/test_retrieval_policy.py backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_rag_retrieval_fusion.py backend/tests/test_layout_neighbor_service.py backend/tests/test_context_window_service.py backend/tests/test_retrieval_route_planner.py backend/tests/test_prompt_templates.py backend/tests/test_domain_metadata_ai_suggester.py backend/tests/test_parser_normalization.py backend/tests/test_redaction_registry.py backend/tests/test_proof_packet_validator.py backend/tests/test_defaults_api.py backend/tests/test_operational_policy.py backend/tests/test_experiments_scoring.py backend/tests/test_retrieval_metrics.py backend/tests/test_reference_regex_registry.py backend/tests/test_domain_metadata_quality_gate.py backend/tests/test_retrieval_route_input.py backend/tests/test_static_policy_catalog.py backend/tests/test_domain_profile_registry.py -q
```

Expected: PASS.

- [x] **Step 3: Run frontend verification**

Run:

```powershell
cd frontend; npm test -- api-client.test.ts settings-page.test.tsx variants-page.test.tsx
```

Expected: PASS.

- [x] **Step 4: Inspect changed files**

Run:

```powershell
git diff --stat
git diff -- backend/src/ragstudio/services/runtime_defaults.py backend/src/ragstudio/services/retrieval_policy.py backend/src/ragstudio/services/prompt_templates.py backend/src/ragstudio/services/redaction_registry.py backend/src/ragstudio/services/operational_policy.py backend/src/ragstudio/services/reference_regex_registry.py backend/src/ragstudio/services/static_policy_catalog.py
```

Expected: diff shows behavior-preserving refactors and named registries, not unrelated UI or retrieval tuning.

- [x] **Step 5: Commit documentation**

Run:

```powershell
git add docs/hardcoded-policy-inventory.md docs/superpowers/plans/2026-05-24-hardcoded-policy-improvements.md
git commit -m "docs: document hardcoded policy registry"
```

Expected: commit succeeds with only documentation files staged.

---

### Task 10: Structured-Reference Enforcement Follow-Up

**Recommendation:** Change structured-reference enforcement to require a verified/executable contract. For `metadata_only`, keep `reference_schema` and `domain_structure` as hints for retrieval/display, but do not require every chunk to resolve to a reference unit. Keep script, table, and layout gates from the vision model when they are independently supported by evidence.

**Files:**
- Modify: `backend/src/ragstudio/services/domain_metadata_quality_gate.py`
- Test: `backend/tests/test_domain_metadata_quality_gate.py`

- [x] **Step 1: Write regression tests for unverified versus verified reference contracts**

Append to `backend/tests/test_domain_metadata_quality_gate.py`:

```python
def test_unverified_reference_schema_does_not_emit_reference_unit_unresolved():
    metadata = DomainMetadata(
        domain="policy",
        document_type="insurance_policy",
        language="mixed",
        custom_json={
            "reference_schema": {
                "type": "bilingual_section_numbering",
                "fields": {"clause": "clause"},
                "canonical_ref_template": "{clause}",
            },
            "domain_structure": {
                "primary_anchor": {
                    "regex": r"^(?:Clause|البند)\s+(?P<clause>\d+)",
                    "unit": "clause",
                    "verified": False,
                }
            },
            "quality_policy": {
                "required_scripts": ["latin"],
                "missing_required_script_action": "warn",
            },
        },
    )
    chunk = AdapterChunk(
        text="Definitions and general terms without a clause anchor.",
        source_location={"page": 1},
        metadata={},
    )

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        [chunk],
        domain_metadata=metadata,
    )

    assert "reference_unit_unresolved" not in report["parser_quality"]["warning_counts"]
    assert report["index_quality_report"]["summary"]["reference_unit_unresolved_count"] == 0


def test_verified_reference_contract_still_enforces_unresolved_reference_units():
    metadata = DomainMetadata(
        domain="policy",
        document_type="insurance_policy",
        language="mixed",
        custom_json={
            "reference_schema": {
                "type": "bilingual_section_numbering",
                "fields": {"clause": "clause"},
                "canonical_ref_template": "{clause}",
            },
            "domain_structure": {
                "primary_anchor": {
                    "regex": r"^(?:Clause|البند)\s+(?P<clause>\d+)",
                    "unit": "clause",
                    "verified": True,
                }
            },
            "quality_policy": {
                "required_scripts": ["latin"],
                "missing_required_script_action": "warn",
            },
        },
    )
    chunk = AdapterChunk(
        text="Definitions and general terms without a clause anchor.",
        source_location={"page": 1},
        metadata={},
    )

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        [chunk],
        domain_metadata=metadata,
    )

    assert report["parser_quality"]["warning_counts"]["reference_unit_unresolved"] == 1
    assert report["index_quality_report"]["summary"]["reference_unit_unresolved_count"] == 1
```

Reviewer follow-up added during implementation: make the unverified case
parameterized across each disabling signal (`contract_status=metadata_only`,
`reference_contract.verified=false`, and
`reference_contract_validation.status=unverified`). Also add a regression where
metadata-only reference hints still produce script/materialization blocking when
`reference_metadata.references` independently identifies a reference unit.

- [x] **Step 2: Run the focused tests and confirm the first test fails before implementation**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; pytest backend/tests/test_domain_metadata_quality_gate.py -k "unverified_reference_schema or verified_reference_contract" -q
```

Expected before implementation: FAIL because unverified `reference_schema` currently makes `ReferenceSemantics.profile_name` structured and `DomainMetadataQualityGate` treats the chunk as requiring a resolved reference unit.

- [x] **Step 3: Split reference hints from executable enforcement**

Keep `ReferenceSemantics.from_metadata()` unchanged so `reference_schema` and
standard reference metadata still act as retrieval/display hints and existing
structured-reference reporting remains compatible.

In `backend/src/ragstudio/services/domain_metadata_quality_gate.py`, change
`MetadataQualityProfile.structured_references` from:

```python
structured_references=semantics.profile_name != "generic",
```

to:

```python
structured_references=(
    semantics.profile_name != "generic"
    and _reference_enforcement_enabled(custom_json)
),
```

Add:

```python
def _reference_enforcement_enabled(custom_json: dict[str, Any]) -> bool:
    reference_contract = custom_json.get("reference_contract")
    if isinstance(reference_contract, dict) and reference_contract.get("verified") is False:
        return False
    validation = custom_json.get("reference_contract_validation")
    if isinstance(validation, dict) and validation.get("status") == "unverified":
        return False
    if custom_json.get("contract_status") == "metadata_only":
        return False
    return True
```

This keeps vision-derived `reference_schema` useful for retrieval/display hints
while preventing unverified `metadata_only` contracts from becoming hard quality
gates.

Reviewer follow-up added during implementation: keep `structured_references`
as the hint/reporting signal and add a separate
`require_resolved_reference_unit` flag. `annotate_reference_quality()` must still
run for metadata-only hints so independently evidenced script/table/layout gates
continue to produce quality reports and materialization policy.

- [x] **Step 4: Keep independent script/table/layout gates intact**

Do not remove or weaken these paths in `backend/src/ragstudio/services/domain_metadata_quality_gate.py`:

```python
required_scripts = set(contract.required_scripts)
optional_scripts = set(contract.optional_scripts)
required_scripts_by_unit_role = dict(contract.required_scripts_by_unit_role)
optional_scripts_by_unit_role = dict(contract.optional_scripts_by_unit_role)
```

The intended behavior is:

- script gates still run when `quality_policy.required_scripts`, role-scoped scripts, parser metadata, or chunk metadata independently identifies expected scripts;
- table/layout gates still run from parser metadata and layout quality policy;
- only the global “every content chunk must resolve to a reference unit” rule requires `contract.verified`.

- [x] **Step 5: Run validation**

Run:

```powershell
$env:PYTHONPATH='E:\repos\Ragstudio\backend\src'; pytest backend/tests/test_domain_metadata_quality_gate.py backend/tests/test_reference_metadata.py backend/tests/test_reference_contracts.py -q
```

Expected: PASS. The new regression proves `metadata_only` no longer creates `reference_unit_unresolved`, while verified executable contracts still enforce unresolved reference units.

- [ ] **Step 6: Commit the enforcement fix**

Run:

```powershell
git add backend/src/ragstudio/services/domain_metadata_quality_gate.py backend/tests/test_domain_metadata_quality_gate.py docs/superpowers/plans/2026-05-24-hardcoded-policy-improvements.md
git commit -m "fix: require verified reference contracts for unresolved-unit enforcement"
```

Expected: commit succeeds with only the structured-reference enforcement fix and plan update staged.

---

## Self-Review

**Spec coverage:** The plan covers constants, regex patterns, prompts, scoring heuristics, thresholds, operational guardrails, worker leases, upload limits, persistence limits, metric gates, eval weights, backend variant presets, frontend default synchronization, API bounds, domain profile defaults, chunk profile word targets, proof protocol constants, query-hypothesis protocol vocabulary, provider manifest vocabulary, and retrieval candidate expansion constants. It distinguishes standard defaults from design limitations by keeping stable defaults while moving tunable heuristics into named policy modules or explicitly classifying stable protocol constants. It lists concrete improvement items and maps each to files, tests, and verification commands.

**Placeholder scan:** The plan avoids placeholder instructions. Each code-changing step includes concrete code or exact replacement patterns, exact file paths, and focused test commands with expected results.

**Post-review addition:** Task 10 captures the `metadata_only` reference-schema recommendation. It separates vision-proposed reference hints from verified executable reference contracts, preserves independently evidenced script/table/layout quality gates, and requires a focused regression test for both unverified and verified reference behavior.

**Type consistency:** New names used across tasks are consistent: `RUNTIME_DEFAULTS`, `RUNTIME_LIMITS`, `DEFAULT_RETRIEVAL_POLICY`, `PromptTemplate`, `REDACTION_RULES`, `DEFAULT_OPERATIONAL_POLICY`, `SCRIPT_PATTERNS`, `STATIC_POLICY_ITEMS`, `DefaultsOut`, and `RuntimeDefaultsOut`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-24-hardcoded-policy-improvements.md`. Two execution options:

**1. Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
