# Three-Pillar P0/P1 Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the remaining P0/P1 drift where generic Ragstudio domain, layout, and context behavior still depends on domain-shaped fields, narrow layout rules, or weak structural context propagation.

**Architecture:** Keep the proof boundary strict: the vision/model layer proposes contracts and policies; Ragstudio compiles, executes, validates, and only then enforces them. Generic services must consume verified capabilities, canonical references, layout contracts, and structural context links rather than global Quran, Hadith, Arabic, or one-document-shape assumptions.

**Tech Stack:** Python 3.12, FastAPI service layer, Pydantic schemas, SQLAlchemy-backed chunks/jobs/documents, pytest, Ruff, React/TypeScript, Vitest.

---

## Priority Map

**P0: Correctness / proof-boundary drift**

- Remove Quran-shaped query-hypothesis protocol fields from generic query and verification flow.
- Move Hadith/Bukhari count and Arabic direct-match scoring out of generic scoring into explicit adapter capabilities.
- Put legacy chapter/verse and book/hadith reference metadata behavior behind verified adapter selection.

**P1: Architecture depth / observability drift**

- Make layout neighbor expansion use a backend layout contract instead of fixed same-page/vertical-only rules.
- Prevent native retrieval fallback from silently losing layout/context evidence when canonical hydration is unavailable.
- Expand context windows from structural links, heading paths, reference ranges, and verified relationships.
- Show the three-pillar reasons in UI traces without React becoming the source of truth.
- Expand drift guards so new domain-specific literals cannot re-enter generic files.

---

## File Structure

- Modify: `backend/src/ragstudio/services/query_hypothesis_service.py`
  - Replace Quran-shaped probable-answer fields with generic identity groups and display labels.
- Modify: `backend/src/ragstudio/services/query_hypothesis_verifier.py`
  - Verify expected references through canonical contract output only.
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
  - Stop allowing `surah_and_verse` as a generic direct-evidence answer shape and enrich layout/context traces.
- Modify: `backend/src/ragstudio/services/retrieval_policy.py`
  - Rename generic score labels and keep compatibility aliases outside the public policy shape.
- Modify: `backend/src/ragstudio/services/hybrid_chunk_search.py`
  - Replace hardcoded Hadith/Bukhari answer-bearing boost with adapter-provided scoring signals.
- Create: `backend/src/ragstudio/services/domain_retrieval_adapters.py`
  - Own domain/script-specific scoring capability declarations.
- Modify: `backend/src/ragstudio/services/reference_metadata.py`
  - Make legacy reference parsing adapter-selected and expose generic identity range metadata.
- Modify: `backend/src/ragstudio/services/reference_regex_registry.py`
  - Mark legacy regexes as compatibility adapters, not generic fallback enforcement.
- Create: `backend/src/ragstudio/services/layout_contracts.py`
  - Define layout relationship policy compiled from backend metadata and model-verified hints.
- Modify: `backend/src/ragstudio/services/layout_neighbor_service.py`
  - Use layout contract relationships for page, bbox, table, caption, figure, equation, and reading-order expansion.
- Modify: `backend/src/ragstudio/services/native_raganything_adapter.py`
  - Mark raw native candidates with layout/context loss flags and hydrate from canonical chunks when possible.
- Create: `backend/src/ragstudio/services/context_contracts.py`
  - Define context expansion policy from chunk links, section paths, heading paths, and verified references.
- Modify: `backend/src/ragstudio/services/context_window_service.py`
  - Use structural context expansion instead of adjacency-only expansion.
- Modify: `backend/src/ragstudio/services/context_assembly_service.py`
  - Preserve structural context reasons and prevent direct evidence from losing required breadcrumb/layout labels.
- Modify: `frontend/src/features/query/three-pillar-trace.ts`
  - Render backend-provided domain/layout/context reasons without hardcoding stage names as behavior.
- Modify: `frontend/src/features/query/query-pathway-viewer.tsx`
  - Show the new three-pillar reasons in the pathway inspector.
- Modify: `frontend/src/features/query/evidence-viewer.tsx`
  - Show layout/context loss flags and contract-derived context labels.
- Modify: `backend/tests/test_query_hypothesis_service.py`
- Modify: `backend/tests/test_query_hypothesis_verifier.py`
- Modify: `backend/tests/test_hybrid_chunk_search_arabic.py`
- Create: `backend/tests/test_domain_retrieval_adapters.py`
- Modify: `backend/tests/test_reference_metadata.py`
- Modify: `backend/tests/test_layout_neighbor_service.py`
- Modify: `backend/tests/test_native_raganything_adapter.py`
- Modify: `backend/tests/test_context_window_service.py`
- Modify: `backend/tests/test_context_assembly_service.py`
- Modify: `frontend/tests/three-pillar-trace.test.ts`
- Modify: `frontend/tests/query-pathway-viewer.test.tsx`
- Modify: `frontend/tests/evidence-viewer.test.tsx`
- Modify: `backend/tests/test_architecture_drift_guards.py`
- Modify: `docs/architecture/hardcoded-policy-inventory.md`

---

### Task 1: Remove Quran-Shaped Query-Hypothesis Protocol Fields

**Files:**
- Modify: `backend/src/ragstudio/services/query_hypothesis_service.py`
- Modify: `backend/src/ragstudio/services/query_hypothesis_verifier.py`
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Modify: `backend/tests/test_query_hypothesis_service.py`
- Modify: `backend/tests/test_query_hypothesis_verifier.py`
- Modify: `backend/tests/test_retrieval_orchestrator.py`

- [x] **Step 1: Add failing generic probable-answer parsing test**

Append to `backend/tests/test_query_hypothesis_service.py`:

```python
from ragstudio.services.query_hypothesis_service import _probable_answer


def test_probable_answer_uses_reference_groups_without_domain_fields():
    answer = _probable_answer(
        {
            "matched_term": "mercy",
            "reference_groups": {"chapter": "19", "verse": "13"},
            "display_label": "Chapter 19, verse 13",
        },
        reference_contracts=[
            {
                "reference_contract": {
                    "verified": True,
                    "canonical_units": True,
                    "canonical_ref_template": "{chapter}:{verse}",
                    "required_groups": ["chapter", "verse"],
                }
            }
        ],
    )

    assert answer is not None
    assert answer.reference == "19:13"
    assert answer.reference_groups == {"chapter": "19", "verse": "13"}
    assert answer.display_label == "Chapter 19, verse 13"
    assert not hasattr(answer, "surah_number")
    assert not hasattr(answer, "ayah")
```

- [x] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_query_hypothesis_service.py::test_probable_answer_uses_reference_groups_without_domain_fields -q
```

Expected: FAIL because `ProbableAnswer` still exposes Quran-shaped fields.

- [x] **Step 3: Replace the probable-answer data shape**

In `backend/src/ragstudio/services/query_hypothesis_service.py`, replace the current `ProbableAnswer` dataclass with:

```python
@dataclass(frozen=True)
class ProbableAnswer:
    matched_term: str | None = None
    reference: str | None = None
    reference_groups: dict[str, str] | None = None
    display_label: str | None = None

    def to_trace(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in asdict(self).items()
            if value is not None
        }
```

Then replace `_probable_answer()` with this implementation:

```python
def _probable_answer(
    raw: Any,
    *,
    reference_contracts: list[dict[str, Any]],
) -> ProbableAnswer | None:
    if not isinstance(raw, dict):
        return None
    reference_group_match = _reference_groups_from_contracts(raw, reference_contracts)
    reference_groups = reference_group_match.groups if reference_group_match else None
    contract_reference = (
        canonical_reference_from_groups(
            reference_groups,
            reference_group_match.template,
        )
        if reference_group_match is not None
        else None
    )
    reference = contract_reference or _safe_reference(
        raw.get("reference"),
        reference_contracts=reference_contracts,
    )
    return ProbableAnswer(
        matched_term=_safe_short_text(raw.get("matched_term"), max_length=80),
        reference=reference,
        reference_groups=reference_groups,
        display_label=_safe_short_text(
            raw.get("display_label", raw.get("reference_label")),
            max_length=120,
        ),
    )
```

- [x] **Step 4: Add failing verifier regression**

Append to `backend/tests/test_query_hypothesis_verifier.py`:

```python
def test_verifier_does_not_synthesize_chapter_verse_reference_without_contract():
    hypothesis = QueryHypothesis(
        query="find mercy",
        valid=True,
        intent="find_word_occurrence",
        target_terms=[TargetTerm(surface="mercy", script="latin", term_type="exact_text")],
        answer_shape="reference",
        probable_answer=ProbableAnswer(
            matched_term="mercy",
            display_label="Chapter 19, verse 13",
        ),
    )

    verification = QueryHypothesisVerifier().verify(hypothesis, [])

    assert verification.reference is None
    assert verification.status == "unverified"
```

- [x] **Step 5: Remove verifier fallback fields**

In `backend/src/ragstudio/services/query_hypothesis_verifier.py`:

1. Remove `surah`, `surah_number`, and `ayah` from `QueryHypothesisVerification`.
2. Remove assignments for those fields in the confirmed result.
3. Replace `_expected_reference()` with:

```python
def _expected_reference(hypothesis: QueryHypothesis) -> str | None:
    answer = hypothesis.probable_answer
    if answer is None:
        return None
    return answer.reference
```

- [x] **Step 6: Remove `surah_and_verse` as a direct-evidence answer shape**

In `backend/src/ragstudio/services/retrieval_orchestrator.py`, replace:

```python
and hypothesis.answer_shape in {"surah_and_verse", "reference"}
```

with:

```python
and hypothesis.answer_shape == "reference"
```

Add this regression to `backend/tests/test_retrieval_orchestrator.py`:

```python
def test_confirmed_hypothesis_answer_requires_generic_reference_shape():
    hypothesis = QueryHypothesis(
        query="find mercy",
        valid=True,
        intent="find_word_occurrence",
        target_terms=[TargetTerm(surface="mercy", script="latin", term_type="exact_text")],
        answer_shape="surah_and_verse",
        probable_answer=ProbableAnswer(reference="19:13"),
    )
    verification = QueryHypothesisVerification(
        status="confirmed",
        reason="target_term_found_in_evidence",
        target_terms=["mercy"],
        matched_terms=["mercy"],
        reference="19:13",
    )

    assert _confirmed_hypothesis_answer_allowed(
        hypothesis,
        verification,
        domain_expansion=SimpleNamespace(domain_family="reference_heavy"),
    ) is False
```

- [x] **Step 7: Run focused tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_query_hypothesis_service.py backend/tests/test_query_hypothesis_verifier.py backend/tests/test_retrieval_orchestrator.py -q
python -m ruff check backend/src/ragstudio/services/query_hypothesis_service.py backend/src/ragstudio/services/query_hypothesis_verifier.py backend/src/ragstudio/services/retrieval_orchestrator.py
```

Expected: PASS.

- [x] **Step 8: Commit**

```powershell
git add backend/src/ragstudio/services/query_hypothesis_service.py backend/src/ragstudio/services/query_hypothesis_verifier.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_query_hypothesis_service.py backend/tests/test_query_hypothesis_verifier.py backend/tests/test_retrieval_orchestrator.py
git commit -m "fix: make query hypotheses use generic reference contracts"
```

---

### Task 2: Move Domain-Specific Retrieval Scoring Into Adapters

**Files:**
- Create: `backend/src/ragstudio/services/domain_retrieval_adapters.py`
- Modify: `backend/src/ragstudio/services/hybrid_chunk_search.py`
- Modify: `backend/src/ragstudio/services/retrieval_policy.py`
- Modify: `backend/src/ragstudio/schemas/chunks.py`
- Create: `backend/tests/test_domain_retrieval_adapters.py`
- Modify: `backend/tests/test_hybrid_chunk_search_arabic.py`
- Modify: `backend/tests/test_retrieval_policy.py`

- [x] **Step 1: Add adapter tests**

Create `backend/tests/test_domain_retrieval_adapters.py`:

```python
from ragstudio.services.domain_retrieval_adapters import (
    RetrievalScoringSignals,
    scoring_signals_for_metadata,
)


def test_generic_metadata_has_no_hadith_count_boost():
    signals = scoring_signals_for_metadata({"domain_metadata": {"domain": "generic"}})

    assert signals == RetrievalScoringSignals()


def test_hadith_adapter_declares_count_answer_terms():
    signals = scoring_signals_for_metadata(
        {"domain_metadata": {"domain": "hadith", "collection": "sahih_bukhari"}}
    )

    assert signals.count_answer_terms == frozenset({"hadith", "collection", "bukhari"})
    assert signals.reference_label == "hadith"
```

- [x] **Step 2: Run the adapter tests to verify they fail**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_domain_retrieval_adapters.py -q
```

Expected: FAIL because `domain_retrieval_adapters.py` does not exist.

- [x] **Step 3: Add the adapter module**

Create `backend/src/ragstudio/services/domain_retrieval_adapters.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RetrievalScoringSignals:
    count_answer_terms: frozenset[str] = frozenset()
    exact_script_boost: str | None = None
    reference_label: str | None = None


def scoring_signals_for_metadata(metadata: dict[str, Any]) -> RetrievalScoringSignals:
    domain_metadata = metadata.get("domain_metadata")
    if not isinstance(domain_metadata, dict):
        return RetrievalScoringSignals()
    domain = str(domain_metadata.get("domain") or "").casefold()
    collection = str(domain_metadata.get("collection") or "").casefold()
    tags = {
        str(tag).casefold()
        for tag in domain_metadata.get("tags", [])
        if isinstance(tag, str)
    }
    if domain == "hadith" or "hadith" in tags:
        terms = {"hadith", "collection"}
        if "bukhari" in collection:
            terms.add("bukhari")
        return RetrievalScoringSignals(
            count_answer_terms=frozenset(terms),
            exact_script_boost="arabic",
            reference_label="hadith",
        )
    declared_scripts = {
        str(script).casefold()
        for script in domain_metadata.get("declared_scripts", [])
        if isinstance(script, str)
    }
    if "arabic" in declared_scripts:
        return RetrievalScoringSignals(exact_script_boost="arabic")
    return RetrievalScoringSignals()
```

- [x] **Step 4: Replace hardcoded count-answer boost**

In `backend/src/ragstudio/services/hybrid_chunk_search.py`, import:

```python
from ragstudio.services.domain_retrieval_adapters import scoring_signals_for_metadata
```

Replace `_answer_bearing_count_boost()` with:

```python
def _answer_bearing_count_boost(
    self,
    query_text: str,
    chunk_text: str,
    metadata: dict[str, Any],
) -> float:
    if not _COUNT_QUERY_RE.search(query_text):
        return 0.0
    combined = f"{chunk_text} {self._metadata_title(metadata)}".casefold()
    if not _NUMBER_RE.search(combined):
        return 0.0
    signals = scoring_signals_for_metadata(metadata)
    if not signals.count_answer_terms:
        return 0.0
    if not any(term in combined for term in signals.count_answer_terms):
        return 0.0
    return self.policy.answer_bearing_count
```

- [x] **Step 5: Add generic count regression**

Append to `backend/tests/test_hybrid_chunk_search_arabic.py`:

```python
def test_count_boost_does_not_fire_without_domain_adapter():
    service = HybridChunkSearchService()
    score = service._answer_bearing_count_boost(
        "how many items",
        "The collection contains 7277 records.",
        {"domain_metadata": {"domain": "generic"}},
    )

    assert score == 0.0
```

- [x] **Step 6: Rename public score weight fields**

In `backend/src/ragstudio/schemas/chunks.py`, replace `same_chapter` with:

```python
same_parent_reference: float | None = None
```

Keep incoming compatibility in the model validator:

```python
if self.same_parent_reference is None:
    legacy_value = getattr(self, "same_chapter", None)
    if legacy_value is not None:
        self.same_parent_reference = legacy_value
```

In `backend/src/ragstudio/services/retrieval_policy.py`, keep properties `same_chapter_reference_query` and `same_chapter_with_verse_query` as compatibility aliases, but ensure all production scoring uses `same_parent_reference_query` and `same_parent_with_unit_query`.

- [x] **Step 7: Run focused tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_domain_retrieval_adapters.py backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_retrieval_policy.py -q
python -m ruff check backend/src/ragstudio/services/domain_retrieval_adapters.py backend/src/ragstudio/services/hybrid_chunk_search.py backend/src/ragstudio/services/retrieval_policy.py backend/src/ragstudio/schemas/chunks.py
```

Expected: PASS.

- [x] **Step 8: Commit**

```powershell
git add backend/src/ragstudio/services/domain_retrieval_adapters.py backend/src/ragstudio/services/hybrid_chunk_search.py backend/src/ragstudio/services/retrieval_policy.py backend/src/ragstudio/schemas/chunks.py backend/tests/test_domain_retrieval_adapters.py backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_retrieval_policy.py
git commit -m "fix: move domain scoring signals into adapters"
```

---

### Task 3: Put Legacy Reference Metadata Behind Verified Adapter Selection

**Files:**
- Modify: `backend/src/ragstudio/services/reference_metadata.py`
- Modify: `backend/src/ragstudio/services/reference_regex_registry.py`
- Modify: `backend/tests/test_reference_metadata.py`

- [x] **Step 1: Add failing generic reference-range test**

Append to `backend/tests/test_reference_metadata.py`:

```python
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.reference_metadata import ReferenceSemantics


def test_verified_generic_identity_range_does_not_emit_chapter_or_hadith_fields():
    semantics = ReferenceSemantics.from_metadata(
        DomainMetadata(
            custom_json={
                "reference_schema": {
                    "type": "part_item",
                    "canonical_ref_template": "part:{part}:item:{item}",
                    "identity_fields": ["part", "item"],
                },
                "reference_resolution": {"enabled": True, "build_canonical_units": True},
                "domain_structure": {
                    "primary_anchor": {
                        "regex": r"Part\s+(?P<part>\d+),\s+Item\s+(?P<item>\d+)",
                        "verified": True,
                    }
                },
            }
        )
    )

    metadata = semantics.derive_reference_metadata("Part 2, Item 7", {"page": 4})

    assert metadata["reference_identity_range"] == {
        "part": {"start": 2, "end": 2},
        "item": {"start": 7, "end": 7},
    }
    assert "chapter_start" not in metadata
    assert "verse_start" not in metadata
    assert "book_start" not in metadata
    assert "hadith_start" not in metadata
```

- [x] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_reference_metadata.py::test_verified_generic_identity_range_does_not_emit_chapter_or_hadith_fields -q
```

Expected: FAIL because generic identity ranges are not emitted.

- [x] **Step 3: Add generic identity range helper**

In `backend/src/ragstudio/services/reference_metadata.py`, add:

```python
def _identity_range(references: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    ranges: dict[str, dict[str, int]] = {}
    for reference in references:
        for key, value in reference.items():
            if not isinstance(value, int) or isinstance(value, bool):
                continue
            current = ranges.setdefault(key, {"start": value, "end": value})
            current["start"] = min(current["start"], value)
            current["end"] = max(current["end"], value)
    return ranges
```

In `derive_reference_metadata()`, after `references` is built, add:

```python
identity_range = _identity_range(references)
if identity_range:
    metadata["reference_identity_range"] = identity_range
```

- [x] **Step 4: Gate legacy chapter/verse and book/hadith metadata**

Wrap the existing chapter/verse metadata block with:

```python
if self.reference_type in {"surah_ayah", "chapter_verse"}:
    chapter_verse_refs = [
        ref
        for ref in references
        if isinstance(ref.get("chapter"), int) and isinstance(ref.get("verse"), int)
    ]
else:
    chapter_verse_refs = []
```

Wrap the existing book/hadith metadata block with:

```python
if self.reference_type in {"book_hadith", "hadith"}:
    book_hadith_refs = [
        ref
        for ref in references
        if isinstance(ref.get("book"), int) and isinstance(ref.get("hadith"), int)
    ]
else:
    book_hadith_refs = []
```

- [x] **Step 5: Make default regex selection adapter-selected**

In `_reference_patterns()` in `backend/src/ragstudio/services/reference_metadata.py`, only add `REFERENCE_PATTERN`, `CHAPTER_ONLY_PATTERN`, and `BOOK_HADITH_PATTERN` when `self.reference_capability == "verified"` and `self.reference_type` explicitly selects that adapter.

Use this guard:

```python
verified_adapter = self.reference_capability == "verified"
```

Then require `verified_adapter` in each legacy pattern branch.

- [x] **Step 6: Run focused tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_reference_metadata.py -q
python -m ruff check backend/src/ragstudio/services/reference_metadata.py backend/src/ragstudio/services/reference_regex_registry.py
```

Expected: PASS.

- [x] **Step 7: Commit**

```powershell
git add backend/src/ragstudio/services/reference_metadata.py backend/src/ragstudio/services/reference_regex_registry.py backend/tests/test_reference_metadata.py
git commit -m "fix: keep legacy reference metadata adapter-scoped"
```

---

### Task 4: Make Layout Expansion Contract-Driven

**Files:**
- Create: `backend/src/ragstudio/services/layout_contracts.py`
- Modify: `backend/src/ragstudio/services/layout_neighbor_service.py`
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Modify: `backend/tests/test_layout_neighbor_service.py`
- Modify: `backend/tests/test_retrieval_orchestrator.py`

- [x] **Step 1: Add layout contract tests**

Create or append to `backend/tests/test_layout_neighbor_service.py`:

```python
from ragstudio.services.layout_contracts import LayoutExpansionPolicy, layout_policy_from_metadata


def test_layout_policy_reads_verified_table_caption_relationships():
    policy = layout_policy_from_metadata(
        {
            "layout_contract": {
                "verified": True,
                "relationships": ["table_caption", "figure_caption", "bbox_overlap"],
                "vertical_proximity": 90,
                "horizontal_overlap_min": 0.25,
            }
        }
    )

    assert policy == LayoutExpansionPolicy(
        relationships=frozenset({"table_caption", "figure_caption", "bbox_overlap"}),
        vertical_proximity=90.0,
        horizontal_overlap_min=0.25,
    )


def test_unverified_layout_policy_uses_safe_defaults():
    policy = layout_policy_from_metadata(
        {"layout_contract": {"verified": False, "relationships": ["bbox_overlap"]}}
    )

    assert policy.relationships == frozenset({"same_page", "same_reference", "layout_group", "reading_order"})
    assert policy.vertical_proximity == 150.0
```

- [x] **Step 2: Run layout contract tests to verify they fail**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_layout_neighbor_service.py::test_layout_policy_reads_verified_table_caption_relationships backend/tests/test_layout_neighbor_service.py::test_unverified_layout_policy_uses_safe_defaults -q
```

Expected: FAIL because `layout_contracts.py` does not exist.

- [x] **Step 3: Add layout contract module**

Create `backend/src/ragstudio/services/layout_contracts.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_LAYOUT_RELATIONSHIPS = frozenset(
    {"same_page", "same_reference", "layout_group", "reading_order"}
)


@dataclass(frozen=True, slots=True)
class LayoutExpansionPolicy:
    relationships: frozenset[str] = DEFAULT_LAYOUT_RELATIONSHIPS
    vertical_proximity: float = 150.0
    horizontal_overlap_min: float = 0.0


def layout_policy_from_metadata(metadata: dict[str, Any]) -> LayoutExpansionPolicy:
    contract = metadata.get("layout_contract")
    if not isinstance(contract, dict) or contract.get("verified") is not True:
        return LayoutExpansionPolicy()
    relationships = {
        str(value).strip()
        for value in contract.get("relationships", [])
        if isinstance(value, str) and value.strip()
    }
    vertical_proximity = _float_value(contract.get("vertical_proximity"), default=150.0)
    horizontal_overlap_min = _float_value(contract.get("horizontal_overlap_min"), default=0.0)
    return LayoutExpansionPolicy(
        relationships=frozenset(relationships) or DEFAULT_LAYOUT_RELATIONSHIPS,
        vertical_proximity=vertical_proximity,
        horizontal_overlap_min=horizontal_overlap_min,
    )


def _float_value(value: Any, *, default: float) -> float:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return default
```

- [x] **Step 4: Use layout policy in neighbor expansion**

In `backend/src/ragstudio/services/layout_neighbor_service.py`:

1. Import `layout_policy_from_metadata`.
2. Build a policy from seed metadata and the service default.
3. Only run relationship checks that are enabled in `policy.relationships`.
4. Include `bbox_overlap` when both seed and row bboxes exist and horizontal overlap ratio is at least `policy.horizontal_overlap_min`.

Add this helper:

```python
def _horizontal_overlap_ratio(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    overlap = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    width = max(1.0, min(left[2] - left[0], right[2] - right[0]))
    return overlap / width
```

- [x] **Step 5: Add trace assertion**

Append to `backend/tests/test_retrieval_orchestrator.py`:

```python
def test_layout_neighbor_trace_reports_contract_relationships():
    candidates = [
        EvidenceCandidate(
            candidate_id="layout-neighbor:chunk-1",
            text="Caption text",
            document_id="doc-1",
            chunk_id="chunk-1",
            source_location={"page": 1},
            metadata={"layout_group_id": "table-1"},
            tool="metadata",
            tool_rank=1,
            reasons=["layout_neighbor", "bbox_overlap", "layout_group"],
        )
    ]

    assert _layout_neighbor_trace_reason(candidates) == "contract_layout_neighbors"
```

Update `_layout_neighbor_trace_reason()` in `retrieval_orchestrator.py` so `bbox_overlap`, `table_caption`, and `figure_caption` return `"contract_layout_neighbors"`.

- [x] **Step 6: Run focused tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_layout_neighbor_service.py backend/tests/test_retrieval_orchestrator.py -q
python -m ruff check backend/src/ragstudio/services/layout_contracts.py backend/src/ragstudio/services/layout_neighbor_service.py backend/src/ragstudio/services/retrieval_orchestrator.py
```

Expected: PASS.

- [x] **Step 7: Commit**

```powershell
git add backend/src/ragstudio/services/layout_contracts.py backend/src/ragstudio/services/layout_neighbor_service.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_layout_neighbor_service.py backend/tests/test_retrieval_orchestrator.py
git commit -m "feat: make layout neighbor expansion contract-driven"
```

---

### Task 5: Prevent Native Retrieval From Losing Layout And Context Evidence Silently

**Files:**
- Modify: `backend/src/ragstudio/services/native_raganything_adapter.py`
- Modify: `backend/src/ragstudio/services/vector_retrieval_service.py`
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Modify: `backend/tests/test_native_raganything_adapter.py`
- Modify: `backend/tests/test_retrieval_orchestrator.py`

- [x] **Step 1: Add native fallback metadata test**

Append to `backend/tests/test_native_raganything_adapter.py`:

```python
def test_raw_native_candidate_marks_missing_canonical_layout_context():
    adapter = NativeRAGAnythingAdapter(profile=runtime_profile())
    rows = [
        {
            "id": "runtime-only-1",
            "document_id": "doc-1",
            "content": "Runtime text",
            "score": 0.9,
            "page": 2,
        }
    ]

    candidates = adapter._candidate_rows_from_native_rows(rows, document_ids=["doc-1"])

    assert candidates[0]["metadata"]["canonical_hydration_status"] == "missing"
    assert candidates[0]["metadata"]["layout_context_status"] == "runtime_minimal"
    assert candidates[0]["metadata"]["risk_flags"] == ["runtime_bridge_missing"]
```

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_native_raganything_adapter.py::test_raw_native_candidate_marks_missing_canonical_layout_context -q
```

Expected: FAIL because raw native candidates do not expose these status fields.

- [x] **Step 3: Mark raw native fallback candidates**

In `backend/src/ragstudio/services/native_raganything_adapter.py`, in the raw native row conversion metadata, add:

```python
"canonical_hydration_status": "missing",
"layout_context_status": "runtime_minimal",
"risk_flags": ["runtime_bridge_missing"],
```

Keep canonical runtime chunks unchanged where they already include rich metadata.

- [x] **Step 4: Preserve risk flags through vector/native hydration**

In `backend/src/ragstudio/services/vector_retrieval_service.py`, when building `EvidenceCandidate`, pass raw risk flags:

```python
risk_flags=tuple(
    str(flag)
    for flag in metadata.get("risk_flags", [])
    if isinstance(flag, str) and flag
),
```

- [x] **Step 5: Add retrieval trace regression**

Append to `backend/tests/test_retrieval_orchestrator.py`:

```python
def test_runtime_bridge_missing_risk_is_visible_in_context_drop_reason():
    candidate = EvidenceCandidate(
        candidate_id="native:runtime-only-1",
        text="Runtime text",
        document_id="doc-1",
        chunk_id=None,
        source_location={"page": 2},
        metadata={"risk_flags": ["runtime_bridge_missing"]},
        tool="native",
        tool_rank=1,
        risk_flags=("runtime_bridge_missing",),
    )

    context = ContextAssemblyService().assemble([candidate])

    assert context.dropped[0].drop_reason == "runtime_bridge_missing"
```

- [x] **Step 6: Run focused tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_native_raganything_adapter.py backend/tests/test_retrieval_orchestrator.py -q
python -m ruff check backend/src/ragstudio/services/native_raganything_adapter.py backend/src/ragstudio/services/vector_retrieval_service.py backend/src/ragstudio/services/retrieval_orchestrator.py
```

Expected: PASS.

- [x] **Step 7: Commit**

```powershell
git add backend/src/ragstudio/services/native_raganything_adapter.py backend/src/ragstudio/services/vector_retrieval_service.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_native_raganything_adapter.py backend/tests/test_retrieval_orchestrator.py
git commit -m "fix: expose native retrieval layout context loss"
```

---

### Task 6: Expand Context Windows From Structural Contracts

**Files:**
- Create: `backend/src/ragstudio/services/context_contracts.py`
- Modify: `backend/src/ragstudio/services/context_window_service.py`
- Modify: `backend/src/ragstudio/services/context_assembly_service.py`
- Modify: `backend/tests/test_context_window_service.py`
- Modify: `backend/tests/test_context_assembly_service.py`

- [x] **Step 1: Add context policy tests**

Create or append to `backend/tests/test_context_window_service.py`:

```python
from ragstudio.services.context_contracts import ContextExpansionPolicy, context_policy_from_metadata


def test_context_policy_reads_verified_structural_links():
    policy = context_policy_from_metadata(
        {
            "context_contract": {
                "verified": True,
                "relationships": ["heading_path", "section_path", "reference_range"],
                "max_reference_distance": 2,
            }
        }
    )

    assert policy == ContextExpansionPolicy(
        relationships=frozenset({"heading_path", "section_path", "reference_range"}),
        max_reference_distance=2,
    )


def test_unverified_context_policy_uses_link_defaults():
    policy = context_policy_from_metadata(
        {"context_contract": {"verified": False, "relationships": ["heading_path"]}}
    )

    assert policy.relationships == frozenset({"reading_order", "parent", "sibling", "linked"})
    assert policy.max_reference_distance == 1
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_context_window_service.py::test_context_policy_reads_verified_structural_links backend/tests/test_context_window_service.py::test_unverified_context_policy_uses_link_defaults -q
```

Expected: FAIL because `context_contracts.py` does not exist.

- [x] **Step 3: Add context contract module**

Create `backend/src/ragstudio/services/context_contracts.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_CONTEXT_RELATIONSHIPS = frozenset({"reading_order", "parent", "sibling", "linked"})


@dataclass(frozen=True, slots=True)
class ContextExpansionPolicy:
    relationships: frozenset[str] = DEFAULT_CONTEXT_RELATIONSHIPS
    max_reference_distance: int = 1


def context_policy_from_metadata(metadata: dict[str, Any]) -> ContextExpansionPolicy:
    contract = metadata.get("context_contract")
    if not isinstance(contract, dict) or contract.get("verified") is not True:
        return ContextExpansionPolicy()
    relationships = {
        str(value).strip()
        for value in contract.get("relationships", [])
        if isinstance(value, str) and value.strip()
    }
    distance = contract.get("max_reference_distance")
    max_reference_distance = distance if isinstance(distance, int) and distance > 0 else 1
    return ContextExpansionPolicy(
        relationships=frozenset(relationships) or DEFAULT_CONTEXT_RELATIONSHIPS,
        max_reference_distance=max_reference_distance,
    )
```

- [x] **Step 4: Add structural context matching**

In `backend/src/ragstudio/services/context_window_service.py`:

1. Import `context_policy_from_metadata`.
2. Collect seed `heading_path`, `section_path`, and `reference_identity_range` values.
3. Add relationship reasons:

```python
if "heading_path" in policy.relationships and _same_path(metadata, seed_heading_paths, "heading_path"):
    reasons.append("heading_path_context")
if "section_path" in policy.relationships and _same_path(metadata, seed_section_paths, "section_path"):
    reasons.append("section_path_context")
if "reference_range" in policy.relationships and _near_reference_range(
    metadata,
    seed_reference_ranges,
    max_distance=policy.max_reference_distance,
):
    reasons.append("reference_range_context")
```

Add helpers:

```python
def _same_path(metadata: dict[str, Any], seed_paths: set[tuple[str, ...]], key: str) -> bool:
    value = metadata.get(key)
    if isinstance(value, str):
        path = (value,)
    elif isinstance(value, list):
        path = tuple(str(item) for item in value if isinstance(item, str) and item)
    else:
        path = ()
    return bool(path and path in seed_paths)


def _near_reference_range(
    metadata: dict[str, Any],
    seed_ranges: list[dict[str, dict[str, int]]],
    *,
    max_distance: int,
) -> bool:
    current = metadata.get("reference_identity_range")
    if not isinstance(current, dict):
        return False
    for seed in seed_ranges:
        for field, seed_range in seed.items():
            current_range = current.get(field)
            if not isinstance(current_range, dict):
                continue
            seed_end = seed_range.get("end")
            current_start = current_range.get("start")
            if isinstance(seed_end, int) and isinstance(current_start, int):
                if abs(current_start - seed_end) <= max_distance:
                    return True
    return False
```

- [x] **Step 5: Preserve structural reasons in assembly**

Append to `backend/tests/test_context_assembly_service.py`:

```python
def test_context_assembly_preserves_structural_context_reason():
    candidate = EvidenceCandidate(
        candidate_id="context-window:chunk-2",
        text="Continuation text",
        document_id="doc-1",
        chunk_id="chunk-2",
        source_location={"page": 2},
        metadata={"heading_path": ["Part 1", "Section 2"]},
        tool="metadata",
        tool_rank=1,
        reasons=["context_window", "heading_path_context"],
        retrieval_pass="context_window",
    )

    assembled = ContextAssemblyService().assemble([candidate])

    assert assembled.evidence[0].included_reason == "structural_context"
```

Update `_included_reason()` in `context_assembly_service.py`:

```python
passes = _retrieval_passes(candidate)
if "context_window" in passes and any(
    reason in candidate.reasons
    for reason in {"heading_path_context", "section_path_context", "reference_range_context"}
):
    return "structural_context"
```

- [x] **Step 6: Run focused tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_context_window_service.py backend/tests/test_context_assembly_service.py -q
python -m ruff check backend/src/ragstudio/services/context_contracts.py backend/src/ragstudio/services/context_window_service.py backend/src/ragstudio/services/context_assembly_service.py
```

Expected: PASS.

- [x] **Step 7: Commit**

```powershell
git add backend/src/ragstudio/services/context_contracts.py backend/src/ragstudio/services/context_window_service.py backend/src/ragstudio/services/context_assembly_service.py backend/tests/test_context_window_service.py backend/tests/test_context_assembly_service.py
git commit -m "feat: expand context windows from structural contracts"
```

---

### Task 7: Surface Three-Pillar Reasons In The UI

**Files:**
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Modify: `frontend/src/features/query/three-pillar-trace.ts`
- Modify: `frontend/src/features/query/query-pathway-viewer.tsx`
- Modify: `frontend/src/features/query/evidence-viewer.tsx`
- Modify: `frontend/tests/three-pillar-trace.test.ts`
- Modify: `frontend/tests/query-pathway-viewer.test.tsx`
- Modify: `frontend/tests/evidence-viewer.test.tsx`

- [x] **Step 1: Add frontend trace normalization test**

Append to `frontend/tests/three-pillar-trace.test.ts`:

```typescript
it("normalizes backend-provided three-pillar reasons", () => {
  const summary = buildThreePillarTrace({
    chunk_traces: [
      {
        stage: "retrieval_route_plan",
        domain_profile_id: "reference_heavy",
        domain_reasons: ["verified_reference_contract"],
      },
      {
        stage: "layout_neighbor_expansion",
        status: "ran",
        layout_reasons: ["bbox_overlap", "layout_group"],
      },
      {
        stage: "retrieval_lane_result",
        lane: "context_window",
        status: "ran",
        context_reasons: ["heading_path_context"],
      },
    ],
    reranker_traces: [],
  } as never);

  expect(summary.route.domainReasons).toEqual(["verified_reference_contract"]);
  expect(summary.layout.layoutReasons).toEqual(["bbox_overlap", "layout_group"]);
  expect(summary.context.contextReasons).toEqual(["heading_path_context"]);
});
```

- [x] **Step 2: Run frontend test to verify it fails**

Run:

```powershell
cd frontend; npm test -- three-pillar-trace.test.ts --run
```

Expected: FAIL because `domainReasons`, `layoutReasons`, and `contextReasons` are not normalized.

- [x] **Step 3: Add backend trace fields**

In `backend/src/ragstudio/services/retrieval_orchestrator.py`, add:

- `domain_reasons` on the route trace from domain profile, verified contract status, and materialization policy.
- `layout_reasons` on layout neighbor trace from candidate reasons excluding `layout_neighbor`.
- `context_reasons` on context window trace from candidate reasons excluding `context_window`.

Use this helper:

```python
def _unique_reasons(candidates: list[EvidenceCandidate], *, exclude: set[str]) -> list[str]:
    values: list[str] = []
    for candidate in candidates:
        for reason in candidate.reasons:
            if reason in exclude or reason in values:
                continue
            values.append(reason)
    return values
```

- [x] **Step 4: Normalize fields in the frontend**

In `frontend/src/features/query/three-pillar-trace.ts`, add fields:

```typescript
domainReasons: string[];
layoutReasons: string[];
contextReasons: string[];
```

Populate them with:

```typescript
domainReasons: stringArray(routeTrace?.domain_reasons),
layoutReasons: stringArray(layoutTrace?.layout_reasons),
contextReasons: stringArray(contextTrace?.context_reasons),
```

- [x] **Step 5: Render reason chips**

In `frontend/src/features/query/query-pathway-viewer.tsx` and `frontend/src/features/query/evidence-viewer.tsx`, render these arrays with the existing compact badge/chip style used for trace status values. Use labels:

- Domain: `Contract reasons`
- Layout: `Layout reasons`
- Context: `Context reasons`

- [x] **Step 6: Run frontend tests**

Run:

```powershell
cd frontend; npm test -- three-pillar-trace.test.ts query-pathway-viewer.test.tsx evidence-viewer.test.tsx --run
```

Expected: PASS.

- [x] **Step 7: Commit**

```powershell
git add backend/src/ragstudio/services/retrieval_orchestrator.py frontend/src/features/query/three-pillar-trace.ts frontend/src/features/query/query-pathway-viewer.tsx frontend/src/features/query/evidence-viewer.tsx frontend/tests/three-pillar-trace.test.ts frontend/tests/query-pathway-viewer.test.tsx frontend/tests/evidence-viewer.test.tsx
git commit -m "feat: surface three-pillar trace reasons"
```

---

### Task 8: Expand Architecture Drift Guards And Documentation

**Files:**
- Modify: `backend/tests/test_architecture_drift_guards.py`
- Modify: `docs/architecture/hardcoded-policy-inventory.md`
- Modify: `docs/superpowers/plans/2026-05-25-three-pillar-p0-p1-remediation.md`

- [x] **Step 1: Add missed generic files to the guard**

In `backend/tests/test_architecture_drift_guards.py`, replace `GENERIC_FILES` with:

```python
GENERIC_FILES = [
    "backend/src/ragstudio/services/domain_classifier.py",
    "backend/src/ragstudio/services/retrieval_evidence.py",
    "backend/src/ragstudio/services/hybrid_chunk_search.py",
    "backend/src/ragstudio/services/evidence_first_answer_service.py",
    "backend/src/ragstudio/services/domain_metadata_quality_gate.py",
    "backend/src/ragstudio/services/document_parser_service.py",
    "backend/src/ragstudio/services/chunk_service.py",
    "backend/src/ragstudio/services/index_lifecycle_service.py",
    "backend/src/ragstudio/services/mineru_relationship_builder.py",
    "backend/src/ragstudio/services/query_understanding.py",
    "backend/src/ragstudio/services/query_hypothesis_service.py",
    "backend/src/ragstudio/services/query_hypothesis_verifier.py",
    "backend/src/ragstudio/services/retrieval_orchestrator.py",
    "backend/src/ragstudio/services/retrieval_policy.py",
    "backend/src/ragstudio/services/reference_metadata.py",
    "backend/src/ragstudio/schemas/chunks.py",
]
```

Replace `DOMAIN_TERMS` with:

```python
DOMAIN_TERMS = [
    "quran",
    "surah",
    "ayah",
    "surah_and_verse",
    "surah_number",
    "chapter_verse",
    "book_hadith",
    "same_chapter",
    "boost_neighbor_verses",
    "next_ayah",
    "previous_ayah",
    "\"hadith\" in combined",
    "\"bukhari\" in combined",
]
```

- [x] **Step 2: Add adapter allowlist**

Add this allowlist so intentionally adapter-owned modules can keep compatibility vocabulary:

```python
ADAPTER_ALLOWED_FILES = {
    "backend/src/ragstudio/services/reference_regex_registry.py",
    "backend/src/ragstudio/services/domain_retrieval_adapters.py",
}
```

Then assert that adapter-owned files document their classification:

```python
def test_adapter_files_document_domain_specific_vocabulary_boundary():
    offenders: list[str] = []
    for relative_path in ADAPTER_ALLOWED_FILES:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8").casefold()
        if "adapter" not in text or "generic" not in text:
            offenders.append(relative_path)

    assert offenders == []
```

- [x] **Step 3: Run guard to verify it fails until prior tasks are complete**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_architecture_drift_guards.py -q
```

Expected: FAIL before Tasks 1 through 7 are complete; PASS after those tasks remove the generic drift.

- [x] **Step 4: Update hardcoded policy inventory**

Append to `docs/architecture/hardcoded-policy-inventory.md`:

```markdown
## Three-Pillar Drift Boundary

- Domain-aware behavior is generic by default. Domain-shaped names such as Quran, Surah, Ayah, Hadith, Bukhari, chapter-verse, and book-hadith belong in adapter-owned files or fixtures, not generic orchestration, scoring, query, or schema surfaces.
- Layout-aware behavior is contract-driven. Same-page and reading-order expansion are safe defaults, while bbox overlap, table-caption, figure-caption, equation, and multi-column behavior require backend layout policy evidence.
- Context-aware behavior is structural. Parent, previous, next, heading path, section path, and verified reference range links are context signals; raw semantic proximity alone is not sufficient proof of context.
- Native runtime candidates must either hydrate to canonical chunks or carry visible layout/context loss flags.
- UI trace components render backend-owned three-pillar reasons and must not invent pipeline stage vocabulary.
```

- [x] **Step 5: Run final focused validation**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_query_hypothesis_service.py backend/tests/test_query_hypothesis_verifier.py backend/tests/test_domain_retrieval_adapters.py backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_reference_metadata.py backend/tests/test_layout_neighbor_service.py backend/tests/test_native_raganything_adapter.py backend/tests/test_context_window_service.py backend/tests/test_context_assembly_service.py backend/tests/test_architecture_drift_guards.py -q
python -m ruff check backend/src/ragstudio/services/query_hypothesis_service.py backend/src/ragstudio/services/query_hypothesis_verifier.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/src/ragstudio/services/domain_retrieval_adapters.py backend/src/ragstudio/services/hybrid_chunk_search.py backend/src/ragstudio/services/retrieval_policy.py backend/src/ragstudio/schemas/chunks.py backend/src/ragstudio/services/reference_metadata.py backend/src/ragstudio/services/layout_contracts.py backend/src/ragstudio/services/layout_neighbor_service.py backend/src/ragstudio/services/native_raganything_adapter.py backend/src/ragstudio/services/vector_retrieval_service.py backend/src/ragstudio/services/context_contracts.py backend/src/ragstudio/services/context_window_service.py backend/src/ragstudio/services/context_assembly_service.py backend/tests/test_architecture_drift_guards.py
cd frontend; npm test -- three-pillar-trace.test.ts query-pathway-viewer.test.tsx evidence-viewer.test.tsx --run
```

Expected: PASS.

- [x] **Step 6: Commit**

```powershell
git add backend/tests/test_architecture_drift_guards.py docs/architecture/hardcoded-policy-inventory.md docs/superpowers/plans/2026-05-25-three-pillar-p0-p1-remediation.md
git commit -m "test: expand three-pillar architecture drift guards"
```

---

## Final Verification

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_query_hypothesis_service.py backend/tests/test_query_hypothesis_verifier.py backend/tests/test_domain_retrieval_adapters.py backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_retrieval_policy.py backend/tests/test_reference_metadata.py backend/tests/test_layout_neighbor_service.py backend/tests/test_native_raganything_adapter.py backend/tests/test_context_window_service.py backend/tests/test_context_assembly_service.py backend/tests/test_retrieval_orchestrator.py backend/tests/test_architecture_drift_guards.py -q
python -m ruff check backend/src/ragstudio/services/query_hypothesis_service.py backend/src/ragstudio/services/query_hypothesis_verifier.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/src/ragstudio/services/domain_retrieval_adapters.py backend/src/ragstudio/services/hybrid_chunk_search.py backend/src/ragstudio/services/retrieval_policy.py backend/src/ragstudio/schemas/chunks.py backend/src/ragstudio/services/reference_metadata.py backend/src/ragstudio/services/reference_regex_registry.py backend/src/ragstudio/services/layout_contracts.py backend/src/ragstudio/services/layout_neighbor_service.py backend/src/ragstudio/services/native_raganything_adapter.py backend/src/ragstudio/services/vector_retrieval_service.py backend/src/ragstudio/services/context_contracts.py backend/src/ragstudio/services/context_window_service.py backend/src/ragstudio/services/context_assembly_service.py backend/tests/test_architecture_drift_guards.py
cd frontend; npm test -- three-pillar-trace.test.ts query-pathway-viewer.test.tsx evidence-viewer.test.tsx --run
```

Expected: all commands pass.

---

## Self-Review

**Spec coverage:** P0 domain/proof-boundary drift is covered by Tasks 1, 2, and 3. P1 layout-aware drift is covered by Tasks 4, 5, and 7. P1 context-aware drift is covered by Tasks 5, 6, and 7. Regression prevention and documentation are covered by Task 8.

**Placeholder scan:** The plan avoids placeholder instructions. Every task lists exact files, test code, commands, expected outcomes, and commit boundaries.

**Type consistency:** The planned names are consistent across tasks: `RetrievalScoringSignals`, `LayoutExpansionPolicy`, `ContextExpansionPolicy`, `reference_identity_range`, `domain_reasons`, `layout_reasons`, and `context_reasons`.

---

Plan complete and saved to `docs/superpowers/plans/2026-05-25-three-pillar-p0-p1-remediation.md`. Two execution options:

**1. Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, with checkpoints for review.

Which approach?
