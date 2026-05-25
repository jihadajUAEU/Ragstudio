# Three-Pillar Architecture Drift Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the remaining generic-pipeline drift where Quran-shaped or hint-only reference assumptions leak into domain-aware, layout-aware, and context-aware behavior.

**Architecture:** Keep the proof boundary strict: the model proposes reference identities, regex extractors, layout policies, and query/display hints; Ragstudio executes and verifies contracts before enforcement. Metadata-only hints remain visible for display and operator review, while verified executable contracts drive chunking, scoring, query parsing, graph materialization, and final answer formatting.

**Tech Stack:** Python 3.12, FastAPI service layer, Pydantic schemas, SQLAlchemy-backed document contracts, pytest, React/TypeScript stage-flow UI.

---

## Why This Helps The Three Pillars

**Domain-aware:** Domain behavior moves from hardcoded terms such as `quran`, `chapter`, and `verse` into model-declared `identity.fields`, verified executable contracts, and explicit domain adapters. Domain labels can still select adapters, but generic services do not enforce domain-specific fields.

**Layout-aware:** Layout and stage evidence stay backend-owned and contract-driven. The document flow UI renders stage metadata from the backend, so adding or removing stages does not require React to know every pipeline stage name.

**Context-aware:** Query parsing, scoring, neighbor expansion, and answer rendering use canonical references and verified contract display metadata. Context assembly can preserve same-reference, neighboring-reference, and layout-neighbor evidence without assuming a specific `chapter:verse` shape.

---

## File Structure

- Modify: `backend/src/ragstudio/services/reference_contracts.py`
  - Owns the distinction between reference hints and verified executable reference contracts.
- Modify: `backend/src/ragstudio/services/domain_classifier.py`
  - Uses verified contract capability for `reference_heavy` routing while preserving domain-family labels.
- Modify: `backend/src/ragstudio/services/retrieval_evidence.py`
  - Stops treating unverified reference hints as proof of reference-heavy retrieval capability.
- Modify: `backend/src/ragstudio/services/chunk_lexical_search_repository.py`
  - Allows verified-contract parsing first and makes legacy parsing profile-gated.
- Modify: `backend/src/ragstudio/services/reference_metadata.py`
  - Adds explicit reference capability status and generic identity-range metadata.
- Modify: `backend/src/ragstudio/services/hybrid_chunk_search.py`
  - Scores exact, parent, and neighbor reference matches through generic fields.
- Modify: `backend/src/ragstudio/services/retrieval_policy.py`
  - Renames scoring knobs to generic reference terms while keeping compatibility aliases during migration.
- Modify: `backend/src/ragstudio/services/reference_regex_registry.py`
  - Classifies legacy regexes as adapter-owned, not generic defaults.
- Modify: `backend/src/ragstudio/services/query_hypothesis_service.py`
  - Uses verified contract fields for probable-answer references.
- Modify: `backend/src/ragstudio/services/evidence_first_answer_service.py`
  - Renders answer references through display metadata instead of assuming `Surah`.
- Modify: `backend/src/ragstudio/services/document_pipeline_timeline_service.py`
  - Adds backend-owned stage display metadata.
- Modify: `backend/src/ragstudio/schemas/document_pipeline_timeline.py`
  - Adds optional stage category, icon hint, and inspector kind.
- Modify: `frontend/src/features/document-evidence/document-pipeline-stage-flow.tsx`
  - Uses backend stage display metadata with neutral fallbacks.
- Modify: `backend/src/ragstudio/services/domain_metadata_quality_gate.py`
  - Removes built-in chapter, verse, and hadith reference extraction from generic quality gates.
- Modify: `backend/src/ragstudio/services/document_parser_service.py`
  - Stops deriving parser extraction language from domain-name substrings.
- Modify: `backend/src/ragstudio/services/parser_normalization.py`
  - Uses explicit model-declared script and recovery policy instead of Quran-shaped recovery labels.
- Create: `backend/src/ragstudio/services/domain_quality_policy.py`
  - Centralizes explicit quality-language and script-policy derivation.
- Modify: `backend/src/ragstudio/services/chunk_service.py`
  - Replaces domain-string quality language inference with shared quality policy metadata.
- Modify: `backend/src/ragstudio/services/index_lifecycle_service.py`
  - Uses the same shared quality policy helper as chunk search and graph materialization.
- Modify: `backend/src/ragstudio/services/mineru_relationship_builder.py`
  - Emits graph edge types from declared graph policy instead of hardcoded ayah or verse aliases.
- Modify: `backend/src/ragstudio/services/metadata_json_schema.py`
  - Normalizes examples and retrieval/graph vocabulary away from chapter and verse defaults.
- Modify: `backend/src/ragstudio/services/query_understanding.py`
  - Makes reference and script intents depend on domain expansion or verified contract hints.
- Modify: `backend/tests/test_reference_contracts.py`
  - Adds hint-versus-verified contract tests.
- Modify: `backend/tests/test_domain_classifier.py`
  - Adds metadata-only and verified-contract routing tests.
- Modify: `backend/tests/test_reference_metadata.py`
  - Adds generic identity-field reference semantics tests.
- Modify: `backend/tests/test_hybrid_chunk_search_arabic.py`
  - Adds compatibility tests and generic scoring tests near current reference scoring coverage.
- Modify: `backend/tests/test_query_hypothesis_service.py`
  - Adds generic contract probable-answer parsing tests.
- Modify: `backend/tests/test_document_pipeline_timeline.py`
  - Adds stage metadata tests for unknown and known stages.
- Modify: `frontend/tests/document-pipeline-stage-flow.test.tsx`
  - Adds generic stage rendering and inspector fallback tests.
- Modify: `backend/tests/test_domain_metadata_quality_gate.py`
  - Adds contract-required quality gate reference extraction tests.
- Modify: `backend/tests/test_document_parser_service.py`
  - Adds explicit parser language policy tests.
- Modify: `backend/tests/test_parser_normalization.py`
  - Adds explicit script and recovery-label regression tests.
- Modify: `backend/tests/test_mineru_relationship_builder.py`
  - Adds generic graph edge vocabulary tests.
- Modify: `backend/tests/test_metadata_json_schema.py`
  - Adds neutral example and named-group contract validation tests.
- Modify: `backend/tests/test_query_understanding.py`
  - Adds contract-aware reference intent tests.
- Create: `backend/tests/test_architecture_drift_guards.py`
  - Adds source scans that prevent generic files from reintroducing domain-shaped enforcement.
- Modify: `docs/architecture/hardcoded-policy-inventory.md`
  - Records which items are protocol, adapter-owned, display-only hints, or verified enforcement.

---

### Task 1: Split Reference Hints From Verified Contracts

**Files:**
- Modify: `backend/src/ragstudio/services/reference_contracts.py`
- Modify: `backend/src/ragstudio/services/domain_classifier.py`
- Modify: `backend/src/ragstudio/services/retrieval_evidence.py`
- Modify: `backend/tests/test_reference_contracts.py`
- Modify: `backend/tests/test_domain_classifier.py`

- [x] **Step 1: Write failing reference contract capability tests**

Add this test file if it does not exist, or append these tests to `backend/tests/test_reference_contracts.py`:

```python
from ragstudio.services.reference_contracts import (
    metadata_has_reference_hint,
    metadata_has_verified_reference_contract,
)


def test_reference_schema_is_hint_not_verified_contract():
    metadata = {
        "custom_json": {
            "reference_schema": {
                "type": "parent_item",
                "canonical_ref_template": "{parent_ref}:{unit_ref}",
                "fields": {"parent_ref": "parent", "unit_ref": "unit"},
            }
        }
    }

    assert metadata_has_reference_hint(metadata) is True
    assert metadata_has_verified_reference_contract(metadata) is False


def test_verified_reference_contract_is_enforceable_capability():
    metadata = {
        "index_contract": {
            "reference_contract": {
                "verified": True,
                "canonical_units": True,
                "schema_type": "parent_item",
                "canonical_ref_template": "{parent_ref}:{unit_ref}",
                "required_groups": ["parent_ref", "unit_ref"],
            }
        }
    }

    assert metadata_has_reference_hint(metadata) is True
    assert metadata_has_verified_reference_contract(metadata) is True
```

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_reference_contracts.py -q
```

Expected: FAIL with import errors for `metadata_has_reference_hint` and `metadata_has_verified_reference_contract`.

- [x] **Step 3: Implement capability helpers**

In `backend/src/ragstudio/services/reference_contracts.py`, replace `metadata_declares_reference_contract()` and `metadata_list_declares_reference_contract()` with these helpers, keeping the old names as compatibility wrappers:

```python
def metadata_has_reference_hint(metadata: dict[str, Any]) -> bool:
    custom_json = _dict_value(metadata.get("custom_json"))
    if isinstance(custom_json.get("reference_schema"), dict):
        return True
    if isinstance(custom_json.get("domain_structure"), dict):
        return True
    if isinstance(metadata.get("reference_contract"), dict):
        return True
    index_contract = _dict_value(metadata.get("index_contract"))
    return isinstance(index_contract.get("reference_contract"), dict)


def metadata_has_verified_reference_contract(metadata: dict[str, Any]) -> bool:
    for payload in _reference_contract_payloads(metadata):
        if payload.get("verified") is True and payload.get("canonical_units") is True:
            return True
    custom_json = _dict_value(metadata.get("custom_json"))
    contract = build_executable_reference_contract(custom_json)
    reference_resolution = _dict_value(custom_json.get("reference_resolution"))
    return bool(
        contract.verified
        and reference_resolution.get("build_canonical_units") is True
    )


def metadata_list_has_reference_hint(domain_metadata: list[dict[str, Any]]) -> bool:
    return any(
        metadata_has_reference_hint(metadata)
        for metadata in domain_metadata
        if isinstance(metadata, dict)
    )


def metadata_list_has_verified_reference_contract(
    domain_metadata: list[dict[str, Any]],
) -> bool:
    return any(
        metadata_has_verified_reference_contract(metadata)
        for metadata in domain_metadata
        if isinstance(metadata, dict)
    )


def metadata_declares_reference_contract(metadata: dict[str, Any]) -> bool:
    return metadata_has_reference_hint(metadata)


def metadata_list_declares_reference_contract(
    domain_metadata: list[dict[str, Any]],
) -> bool:
    return metadata_list_has_reference_hint(domain_metadata)


def _reference_contract_payloads(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    direct = metadata.get("reference_contract")
    if isinstance(direct, dict):
        payloads.append(direct)
    index_contract = _dict_value(metadata.get("index_contract"))
    nested = index_contract.get("reference_contract")
    if isinstance(nested, dict):
        payloads.append(nested)
    custom_json = _dict_value(metadata.get("custom_json"))
    custom_nested = custom_json.get("reference_contract")
    if isinstance(custom_nested, dict):
        payloads.append(custom_nested)
    return payloads
```

- [x] **Step 4: Update domain classifier to use verified capability**

In `backend/src/ragstudio/services/domain_classifier.py`, change the import and local variables:

```python
from ragstudio.services.reference_contracts import (
    metadata_list_has_reference_hint,
    metadata_list_has_verified_reference_contract,
)
```

Inside `DomainClassifier.classify()` use:

```python
has_reference_hint = metadata_list_has_reference_hint(domain_metadata)
has_verified_reference_contract = metadata_list_has_verified_reference_contract(domain_metadata)
```

Then use `has_verified_reference_contract` for `reference_heavy` and `materialization_hint="graph"` decisions. Use `has_reference_hint` only for layout hint display:

```python
effective_layout_hint = layout_hint or ("reference" if has_reference_hint else None)
```

- [x] **Step 5: Add classifier regression tests**

Append to `backend/tests/test_domain_classifier.py`:

```python
def test_domain_classifier_keeps_unverified_reference_schema_as_hint():
    result = DomainClassifier().classify(
        [
            {
                "domain": "archive",
                "custom_json": {
                    "reference_schema": {
                        "type": "parent_item",
                        "fields": {"parent_ref": "parent", "unit_ref": "unit"},
                    }
                },
            }
        ]
    )

    assert result.layout_hint == "reference"
    assert result.reference_heavy is False
    assert result.materialization_hint == "vector"


def test_domain_classifier_routes_verified_contract_as_reference_heavy():
    result = DomainClassifier().classify(
        [
            {
                "domain": "archive",
                "index_contract": {
                    "reference_contract": {
                        "verified": True,
                        "canonical_units": True,
                        "schema_type": "parent_item",
                        "canonical_ref_template": "{parent_ref}:{unit_ref}",
                        "required_groups": ["parent_ref", "unit_ref"],
                    }
                },
            }
        ]
    )

    assert result.layout_hint == "reference"
    assert result.reference_heavy is True
    assert result.materialization_hint == "graph"
```

- [x] **Step 6: Update retrieval evidence domain family**

In `backend/src/ragstudio/services/retrieval_evidence.py`, import `metadata_has_verified_reference_contract` and change `_domain_family()` so only verified contracts return `reference_heavy`:

```python
if metadata_has_verified_reference_contract(domain_metadata):
    return "reference_heavy"
```

- [x] **Step 7: Run focused tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_reference_contracts.py backend/tests/test_domain_classifier.py -q
```

Expected: PASS.

- [x] **Step 8: Commit**

```powershell
git add backend/src/ragstudio/services/reference_contracts.py backend/src/ragstudio/services/domain_classifier.py backend/src/ragstudio/services/retrieval_evidence.py backend/tests/test_reference_contracts.py backend/tests/test_domain_classifier.py
git commit -m "fix: separate reference hints from verified contracts"
```

---

### Task 2: Make Reference Semantics Generic And Verification-Aware

**Files:**
- Modify: `backend/src/ragstudio/services/reference_metadata.py`
- Modify: `backend/tests/test_reference_metadata.py`

- [x] **Step 1: Write failing metadata-only semantics test**

Append to `backend/tests/test_reference_metadata.py`:

```python
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.reference_metadata import ReferenceSemantics


def test_metadata_only_reference_schema_does_not_enable_enforcement_defaults():
    semantics = ReferenceSemantics.from_metadata(
        DomainMetadata(
            custom_json={
                "reference_schema": {
                    "type": "parent_item",
                    "fields": {"parent_ref": "parent", "unit_ref": "unit"},
                    "canonical_ref_template": "{parent_ref}:{unit_ref}",
                }
            }
        )
    )

    assert semantics.profile_name == "reference_hint"
    assert semantics.chunk_unit == "section"
    assert semantics.exact_reference_top1 is False
    assert semantics.boost_neighbor_verses is False
    assert semantics.canonical_units_enabled is False
```

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_reference_metadata.py::test_metadata_only_reference_schema_does_not_enable_enforcement_defaults -q
```

Expected: FAIL because current semantics uses `scripture_reference`, may default `chunk_unit` to `verse`, and enables reference boosts from a hint.

- [x] **Step 3: Add explicit capability status**

In `backend/src/ragstudio/services/reference_metadata.py`, add a field to `ReferenceSemantics`:

```python
    reference_capability: str = "none"
```

Inside `from_metadata()`, replace the current `structured_reference` and `profile_name` derivation with:

```python
has_reference_schema = isinstance(reference_schema, dict)
has_structured_hint = has_reference_schema or cls._has_structured_reference_fields(metadata)
has_verified_anchor = False
reference_capability = "none"
if has_structured_hint:
    reference_capability = "hint"
if contract.verified and cls._bool_value(
    reference_resolution.get("build_canonical_units"), default=False
):
    reference_capability = "verified"
profile_name = (
    "verified_reference"
    if reference_capability == "verified"
    else "reference_hint"
    if reference_capability == "hint"
    else "generic"
)
```

Keep the existing `has_verified_anchor` calculation later in the function, but make enforcement defaults depend on `reference_capability == "verified"`.

- [x] **Step 4: Replace hint-driven defaults**

In the `ReferenceSemantics` return block, use:

```python
verified_reference = reference_capability == "verified"
```

Then change defaults:

```python
exact_reference_top1=cls._bool_value(
    retrieval.get("exact_reference_top1"),
    default=verified_reference,
),
boost_same_chapter=cls._bool_value(
    retrieval.get("boost_same_chapter"),
    default=verified_reference,
),
boost_neighbor_verses=cls._bool_value(
    retrieval.get("boost_neighbor_verses", retrieval.get("boost_neighbor_references")),
    default=verified_reference,
),
canonical_units_enabled=bool(
    verified_reference
    and has_verified_anchor
    and cls._bool_value(reference_resolution.get("enabled"), default=False)
    and cls._bool_value(reference_resolution.get("build_canonical_units"), default=False)
),
```

Remove the special default:

```python
if chunk_unit == "section" and structured_reference and not contract.anchors:
    chunk_unit = "verse"
```

- [x] **Step 5: Add verified generic semantics test**

Append to `backend/tests/test_reference_metadata.py`:

```python
def test_verified_generic_reference_contract_enables_reference_defaults():
    semantics = ReferenceSemantics.from_metadata(
        DomainMetadata(
            custom_json={
                "reference_schema": {
                    "type": "parent_item",
                    "fields": {"parent_ref": "parent", "unit_ref": "unit"},
                    "canonical_ref_template": "{parent_ref}:{unit_ref}",
                },
                "domain_structure": {
                    "primary_anchor": {
                        "regex": r"Part\s+(?P<parent_ref>\d+)\s+Item\s+(?P<unit_ref>\d+)",
                        "unit": "item",
                        "verified": True,
                    }
                },
                "reference_resolution": {
                    "enabled": True,
                    "build_canonical_units": True,
                },
            }
        )
    )

    assert semantics.profile_name == "verified_reference"
    assert semantics.reference_capability == "verified"
    assert semantics.chunk_unit == "item"
    assert semantics.exact_reference_top1 is True
    assert semantics.canonical_units_enabled is True
```

- [x] **Step 6: Run focused tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_reference_metadata.py -q
```

Expected: PASS.

- [x] **Step 7: Commit**

```powershell
git add backend/src/ragstudio/services/reference_metadata.py backend/tests/test_reference_metadata.py
git commit -m "fix: make reference semantics verification-aware"
```

---

### Task 3: Replace Chapter/Verse Scoring With Generic Reference Coordinates

**Files:**
- Modify: `backend/src/ragstudio/services/reference_metadata.py`
- Modify: `backend/src/ragstudio/services/hybrid_chunk_search.py`
- Modify: `backend/src/ragstudio/services/retrieval_policy.py`
- Modify: `backend/tests/test_reference_metadata.py`
- Modify: `backend/tests/test_hybrid_chunk_search_arabic.py`

- [x] **Step 1: Write failing generic reference metadata test**

Append to `backend/tests/test_reference_metadata.py`:

```python
def test_reference_metadata_records_generic_identity_ranges():
    semantics = ReferenceSemantics.from_metadata(
        DomainMetadata(
            custom_json={
                "reference_schema": {
                    "type": "parent_item",
                    "fields": {"parent_ref": "parent", "unit_ref": "unit"},
                    "canonical_ref_template": "{parent_ref}:{unit_ref}",
                },
                "domain_structure": {
                    "primary_anchor": {
                        "regex": r"Part\s+(?P<parent_ref>\d+)\s+Item\s+(?P<unit_ref>\d+)",
                        "unit": "item",
                        "verified": True,
                    }
                },
                "reference_resolution": {"enabled": True, "build_canonical_units": True},
                "chunking": {"unit": "item", "include_neighbors": 1},
            }
        )
    )

    metadata = semantics.reference_metadata_for_text("Part 7 Item 104 Body text")

    assert metadata["references"] == ["7:104"]
    assert metadata["identity_ranges"] == {
        "parent_ref": {"start": 7, "end": 7},
        "unit_ref": {"start": 104, "end": 104},
    }
    assert metadata["previous_ref"] == "7:103"
    assert metadata["next_ref"] == "7:105"
```

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_reference_metadata.py::test_reference_metadata_records_generic_identity_ranges -q
```

Expected: FAIL because `identity_ranges` does not exist and neighbor references are only built from `chapter` and `verse`.

- [x] **Step 3: Add generic identity range metadata**

In `backend/src/ragstudio/services/reference_metadata.py`, add helpers:

```python
def _numeric_identity_ranges(
    references: list[dict[str, int | str]],
) -> dict[str, dict[str, int]]:
    ranges: dict[str, dict[str, int]] = {}
    keys = {
        key
        for reference in references
        for key, value in reference.items()
        if key != "ref" and isinstance(value, int)
    }
    for key in keys:
        values = [int(reference[key]) for reference in references if isinstance(reference.get(key), int)]
        if values:
            ranges[key] = {"start": min(values), "end": max(values)}
    return ranges


def _neighbor_reference_from_identity(
    reference: dict[str, int | str],
    *,
    unit_field: str,
    delta: int,
    template: str | None,
) -> str | None:
    value = reference.get(unit_field)
    if not isinstance(value, int):
        return None
    next_value = value + delta
    if next_value <= 0:
        return None
    groups = dict(reference)
    groups[unit_field] = next_value
    return canonical_reference_from_groups(
        {key: str(item) for key, item in groups.items() if key != "ref"},
        template,
    )
```

Inside `_reference_metadata_from_references()`, after `metadata` is created, add:

```python
identity_ranges = _numeric_identity_ranges(references)
if identity_ranges:
    metadata["identity_ranges"] = identity_ranges
```

Then use the last identity field as the neighbor unit when `include_neighbors > 0`:

```python
identity_fields = list(self.required_reference_groups)
unit_field = identity_fields[-1] if identity_fields else None
if self.include_neighbors > 0 and unit_field and len(references) == 1:
    previous_ref = _neighbor_reference_from_identity(
        references[0],
        unit_field=unit_field,
        delta=-self.include_neighbors,
        template=self.canonical_ref_template,
    )
    next_ref = _neighbor_reference_from_identity(
        references[0],
        unit_field=unit_field,
        delta=self.include_neighbors,
        template=self.canonical_ref_template,
    )
    if previous_ref:
        metadata["previous_ref"] = previous_ref
    if next_ref:
        metadata["next_ref"] = next_ref
```

- [x] **Step 4: Add generic hybrid scoring test**

Append to `backend/tests/test_hybrid_chunk_search_arabic.py` or a narrower existing hybrid scoring test file:

```python
from ragstudio.services.hybrid_chunk_search import HybridChunkScorer


def test_hybrid_scoring_uses_generic_reference_ranges():
    scorer = HybridChunkScorer()
    chunk = _chunk(
        text="Part 7 Item 104 Body text",
        metadata_json={
            "domain_metadata": {
                "custom_json": {
                    "reference_schema": {
                        "type": "parent_item",
                        "canonical_ref_template": "{parent_ref}:{unit_ref}",
                        "fields": {"parent_ref": "parent", "unit_ref": "unit"},
                    },
                    "reference_resolution": {"enabled": True, "build_canonical_units": True},
                }
            },
            "reference_metadata": {
                "references": ["7:104"],
                "identity_ranges": {
                    "parent_ref": {"start": 7, "end": 7},
                    "unit_ref": {"start": 104, "end": 104},
                },
                "previous_ref": "7:103",
                "next_ref": "7:105",
            },
            "quality_action_policy": {"vector_index": "allow", "search": "allow"},
        },
    )

    score = scorer.score("7:104", chunk)

    assert score.breakdown["reference_exact"] == scorer.policy.reference_exact
```

Use the local chunk factory in the target test file. If the file has no factory, add:

```python
def _chunk(text: str, metadata_json: dict[str, object]):
    return type(
        "ChunkStub",
        (),
        {
            "text": text,
            "metadata_json": metadata_json,
        },
    )()
```

- [x] **Step 5: Update hybrid scorer to use generic ranges first**

In `backend/src/ragstudio/services/hybrid_chunk_search.py`, add helpers:

```python
def _reference_in_identity_ranges(
    query_ref: dict[str, Any],
    reference_metadata: dict[str, Any],
) -> bool:
    ranges = reference_metadata.get("identity_ranges")
    if not isinstance(ranges, dict):
        return False
    for key, value in query_ref.items():
        if key == "ref" or not isinstance(value, int):
            continue
        item_range = ranges.get(key)
        if not isinstance(item_range, dict):
            return False
        start = item_range.get("start")
        end = item_range.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            return False
        if not start <= value <= end:
            return False
    return True
```

Before the current chapter/verse scoring branch, add:

```python
if (
    quality_allows_reference_boost
    and semantics
    and semantics.exact_reference_top1
    and isinstance(query_ref, dict)
    and _reference_in_identity_ranges(query_ref, reference_metadata)
):
    reference_exact = self.policy.reference_exact
```

Keep the existing chapter/verse path as compatibility fallback for one release.

- [x] **Step 6: Rename scoring policy fields with compatibility aliases**

In `backend/src/ragstudio/services/retrieval_policy.py`, change:

```python
same_chapter_reference_query: float = 60.0
same_chapter_with_verse_query: float = 5.0
```

to:

```python
same_parent_reference_query: float = 60.0
same_parent_with_unit_query: float = 5.0

@property
def same_chapter_reference_query(self) -> float:
    return self.same_parent_reference_query

@property
def same_chapter_with_verse_query(self) -> float:
    return self.same_parent_with_unit_query
```

- [x] **Step 7: Run focused tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_reference_metadata.py backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_retrieval_policy.py -q
```

Expected: PASS.

- [x] **Step 8: Commit**

```powershell
git add backend/src/ragstudio/services/reference_metadata.py backend/src/ragstudio/services/hybrid_chunk_search.py backend/src/ragstudio/services/retrieval_policy.py backend/tests/test_reference_metadata.py backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_retrieval_policy.py
git commit -m "feat: use generic reference coordinates for scoring"
```

---

### Task 4: Gate Legacy Reference Parsing Behind Verified Profiles

**Files:**
- Modify: `backend/src/ragstudio/services/reference_regex_registry.py`
- Modify: `backend/src/ragstudio/services/reference_query_parser.py`
- Modify: `backend/src/ragstudio/services/chunk_lexical_search_repository.py`
- Modify: `backend/tests/test_chunk_lexical_search_repository.py`
- Modify: `backend/tests/test_reference_query_parser.py`

- [x] **Step 1: Add legacy fallback tests**

Append to `backend/tests/test_reference_query_parser.py`:

```python
from ragstudio.services.reference_query_parser import (
    parse_legacy_reference_query,
    parse_query_references,
)


def test_query_reference_parser_ignores_unverified_contracts():
    references = parse_query_references(
        "Find 7:104",
        [
            {
                "reference_contract": {
                    "verified": False,
                    "canonical_ref_template": "{parent_ref}:{unit_ref}",
                }
            }
        ],
    )

    assert references == []


def test_legacy_reference_query_requires_enabled_profile():
    assert parse_legacy_reference_query("Find 7:104", enabled_profiles=set()) == []
    assert parse_legacy_reference_query("Find 7:104", enabled_profiles={"chapter_verse"}) == [
        "7:104"
    ]
```

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_reference_query_parser.py -q
```

Expected: FAIL because `parse_legacy_reference_query()` does not accept `enabled_profiles`.

- [x] **Step 3: Change legacy parser signature**

In `backend/src/ragstudio/services/reference_query_parser.py`, change:

```python
def parse_legacy_reference_query(query: str) -> list[str]:
```

to:

```python
def parse_legacy_reference_query(
    query: str,
    *,
    enabled_profiles: set[str] | None = None,
) -> list[str]:
    profiles = enabled_profiles or set()
    references: list[str] = []
    if "chapter_verse" in profiles:
        references.extend(re.findall(r"\b\d{1,4}:\d{1,6}\b", query))
    if "book_hadith" in profiles:
        references.extend(
            f"book:{int(match.group('book'))}:hadith:{int(match.group('hadith'))}"
            for match in re.finditer(
                r"\bBook\s+(?P<book>\d{1,4})\s*,?\s*Hadith\s+(?P<hadith>\d{1,6})\b",
                query,
                flags=re.IGNORECASE,
            )
        )
        references.extend(
            f"book:{int(match.group('book'))}:hadith:{int(match.group('hadith'))}"
            for match in re.finditer(
                r"\bbook:(?P<book>\d{1,4}):hadith:(?P<hadith>\d{1,6})\b",
                query,
                flags=re.IGNORECASE,
            )
        )
    return list(dict.fromkeys(references))
```

- [x] **Step 4: Add profile extraction helper**

In `backend/src/ragstudio/services/chunk_lexical_search_repository.py`, add:

```python
def _legacy_reference_profiles(contracts: list[dict[str, object]]) -> set[str]:
    profiles: set[str] = set()
    for contract in contracts:
        reference_contract = contract.get("reference_contract")
        if not isinstance(reference_contract, dict):
            continue
        schema_type = reference_contract.get("schema_type")
        if isinstance(schema_type, str) and reference_contract.get("verified") is True:
            profiles.add(schema_type)
    return profiles
```

Then change fallback parsing:

```python
if not references:
    references = parse_legacy_reference_query(
        query,
        enabled_profiles=_legacy_reference_profiles(reference_contracts),
    )
```

- [x] **Step 5: Classify legacy regex registry**

In `backend/src/ragstudio/services/reference_regex_registry.py`, add:

```python
LEGACY_REFERENCE_PATTERN_PROFILES = {
    "chapter_verse": ("REFERENCE_PATTERN", "CHAPTER_ONLY_PATTERN"),
    "book_hadith": ("BOOK_HADITH_PATTERN",),
    "legal_section": ("LEGAL_SECTION_PATTERN",),
    "page_line": ("PAGE_LINE_PATTERN",),
}
```

This records that these patterns are adapter compatibility, not generic enforcement.

- [x] **Step 6: Run focused tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_reference_query_parser.py backend/tests/test_chunk_lexical_search_repository.py -q
```

Expected: PASS.

- [x] **Step 7: Commit**

```powershell
git add backend/src/ragstudio/services/reference_regex_registry.py backend/src/ragstudio/services/reference_query_parser.py backend/src/ragstudio/services/chunk_lexical_search_repository.py backend/tests/test_reference_query_parser.py backend/tests/test_chunk_lexical_search_repository.py
git commit -m "fix: gate legacy reference parsing by profile"
```

---

### Task 5: Make Query Hypotheses And Answers Contract-Display Driven

**Files:**
- Modify: `backend/src/ragstudio/services/query_hypothesis_service.py`
- Modify: `backend/src/ragstudio/services/evidence_first_answer_service.py`
- Modify: `backend/src/ragstudio/services/query_hypothesis_verifier.py`
- Modify: `backend/src/ragstudio/services/metadata_retrieval_service.py`
- Modify: `backend/src/ragstudio/services/reference_query_parser.py`
- Modify: `backend/tests/test_query_hypothesis_service.py`
- Modify: `backend/tests/test_query_hypothesis_verifier.py`
- Modify: `backend/tests/test_retrieval_orchestrator.py`

- [x] **Step 1: Add generic probable-answer parsing test**

Append to `backend/tests/test_query_hypothesis_service.py`:

```python
from ragstudio.services.query_hypothesis_service import parse_query_hypothesis_payload


def test_probable_answer_uses_contract_identity_fields():
    payload = {
        "intent": "find_word_occurrence",
        "answer_shape": "reference",
        "probable_answer": {
            "parent_ref": "7",
            "unit_ref": "104",
            "matched_term": "mercy",
        },
    }
    contracts = [
        {
            "reference_contract": {
                "verified": True,
                "canonical_ref_template": "{parent_ref}:{unit_ref}",
                "required_groups": ["parent_ref", "unit_ref"],
            }
        }
    ]

    hypothesis = parse_query_hypothesis_payload(payload, reference_contracts=contracts)

    assert hypothesis.probable_answer is not None
    assert hypothesis.probable_answer.reference == "7:104"
    assert hypothesis.probable_answer.matched_term == "mercy"
```

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_query_hypothesis_service.py::test_probable_answer_uses_contract_identity_fields -q
```

Expected: FAIL because probable answers still privilege `surah_number` and `ayah`.

- [x] **Step 3: Add generic group storage to ProbableAnswer**

In `backend/src/ragstudio/services/query_hypothesis_service.py`, update `ProbableAnswer`:

```python
@dataclass(frozen=True)
class ProbableAnswer:
    matched_term: str | None = None
    reference: str | None = None
    reference_groups: dict[str, str] | None = None
    display_label: str | None = None
    surah: str | None = None
    surah_number: int | None = None
    ayah: int | None = None
```

In `_probable_answer()`, build generic groups before legacy fields:

```python
reference_groups = _reference_groups_from_contracts(raw, reference_contracts)
contract_reference = (
    canonical_reference_from_groups(reference_groups, _first_verified_template(reference_contracts))
    if reference_groups
    else None
)
reference = contract_reference or _safe_reference(raw.get("reference"), reference_contracts=reference_contracts)
```

Add helpers:

```python
def _reference_groups_from_contracts(
    raw: dict[str, Any],
    reference_contracts: list[dict[str, Any]],
) -> dict[str, str] | None:
    for contract in reference_contracts:
        reference_contract = _reference_contract_payload(contract)
        if reference_contract.get("verified") is False:
            continue
        fields = _string_list(reference_contract.get("required_groups"))
        if not fields:
            template = _string_value(reference_contract.get("canonical_ref_template"))
            fields = sorted(_template_fields(template) or set())
        groups: dict[str, str] = {}
        for field in fields:
            value = _safe_reference_group(raw.get(field))
            if value is None:
                break
            groups[field] = value
        if len(groups) == len(fields):
            return groups
    return None


def _first_verified_template(reference_contracts: list[dict[str, Any]]) -> str | None:
    for contract in reference_contracts:
        reference_contract = _reference_contract_payload(contract)
        if reference_contract.get("verified") is False:
            continue
        template = _string_value(reference_contract.get("canonical_ref_template"))
        if template:
            return template
    return None
```

- [x] **Step 4: Add answer rendering test**

Append to `backend/tests/test_query_hypothesis_verifier.py` or the existing answer-service test file:

```python
from ragstudio.services.evidence_first_answer_service import EvidenceFirstAnswerService


def test_evidence_first_answer_uses_generic_reference_label():
    verification = type(
        "Verification",
        (),
        {
            "evidence_label": "S1",
            "matched_terms": ["mercy"],
            "reference": "7:104",
            "reference_label": "Part 7, item 104",
            "surah": None,
            "surah_number": None,
            "ayah": None,
        },
    )()

    answer, trace = EvidenceFirstAnswerService().answer_confirmed_hypothesis(
        "Where is mercy mentioned?",
        [],
        verification=verification,
    )

    assert answer == "The word mercy is mentioned at Part 7, item 104. [S1]"
    assert trace["reference"] == "7:104"
```

- [x] **Step 5: Update answer renderer**

In `backend/src/ragstudio/services/evidence_first_answer_service.py`, prefer `reference_label`:

```python
reference_label = getattr(verification, "reference_label", None)
if reference and reference_label:
    answer = f"The word {matched_term} is mentioned at {reference_label}. [{label}]"
elif surah and surah_number and ayah:
    answer = (
        f"The word {matched_term} is mentioned in Surah {surah}, "
        f"{surah_number}:{ayah}. [{label}]"
    )
elif reference:
    answer = f"The word {matched_term} is mentioned at {reference}. [{label}]"
```

Remove the generic use of `_surah_reference_label(reference)` for any `n:n` reference. Keep `_surah_reference_label()` only if verification explicitly carries a Quran display role.

- [x] **Step 6: Run focused tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_query_hypothesis_service.py backend/tests/test_query_hypothesis_verifier.py backend/tests/test_retrieval_orchestrator.py -q
```

Expected: PASS.

- [x] **Step 7: Commit**

```powershell
git add backend/src/ragstudio/services/query_hypothesis_service.py backend/src/ragstudio/services/evidence_first_answer_service.py backend/src/ragstudio/services/query_hypothesis_verifier.py backend/src/ragstudio/services/metadata_retrieval_service.py backend/src/ragstudio/services/reference_query_parser.py backend/tests/test_query_hypothesis_service.py backend/tests/test_query_hypothesis_verifier.py backend/tests/test_retrieval_orchestrator.py
git commit -m "fix: render query answers from verified contract display"
```

Execution note: focused verification also exposed canonical-reference drift in metadata
retrieval, where display references from `source_location` could override canonical
`reference_metadata.references`. The implementation now preserves the canonical
reference first and falls back to display/source references only when no canonical
reference is available.

---

### Task 6: Move Stage Display Metadata To The Backend Contract

**Files:**
- Modify: `backend/src/ragstudio/schemas/document_pipeline_timeline.py`
- Modify: `backend/src/ragstudio/services/document_pipeline_timeline_service.py`
- Modify: `frontend/src/api/generated.ts`
- Modify: `frontend/src/features/document-evidence/document-pipeline-stage-flow.tsx`
- Modify: `backend/tests/test_document_pipeline_timeline.py`
- Modify: `frontend/tests/document-pipeline-stage-flow.test.tsx`

- [x] **Step 1: Add backend stage metadata test**

Append to `backend/tests/test_document_pipeline_timeline.py`:

```python
def test_pipeline_stage_contract_includes_display_metadata():
    stage = _stage(
        stage_id="contract",
        label="Contract",
        state="metadata_only",
        detail="Reference structure is metadata only and is not enforced.",
    )

    assert stage.category == "domain"
    assert stage.icon_hint == "contract"
    assert stage.inspector_kind == "contract"


def test_unknown_pipeline_stage_gets_neutral_display_metadata():
    stage = _stage(
        stage_id="model_compiler",
        label="Model compiler",
        state="complete",
        detail="Executed model-generated contract candidates.",
    )

    assert stage.category == "custom"
    assert stage.icon_hint == "stage"
    assert stage.inspector_kind == "generic"
```

If there is no local `_stage()` helper, add:

```python
from ragstudio.services.document_pipeline_timeline_service import _stage_display_metadata


def _stage(stage_id: str, label: str, state: str, detail: str):
    category, icon_hint, inspector_kind = _stage_display_metadata(stage_id)
    return type(
        "StageStub",
        (),
        {
            "id": stage_id,
            "label": label,
            "state": state,
            "detail": detail,
            "category": category,
            "icon_hint": icon_hint,
            "inspector_kind": inspector_kind,
        },
    )()
```

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_document_pipeline_timeline.py -q
```

Expected: FAIL because stage display metadata is not exposed.

- [x] **Step 3: Add schema fields**

In `backend/src/ragstudio/schemas/document_pipeline_timeline.py`, add fields to `DocumentPipelineStageOut`:

```python
    category: str = "custom"
    icon_hint: str = "stage"
    inspector_kind: str = "generic"
```

- [x] **Step 4: Add backend display metadata helper**

In `backend/src/ragstudio/services/document_pipeline_timeline_service.py`, add:

```python
_STAGE_DISPLAY_METADATA: dict[str, tuple[str, str, str]] = {
    "uploaded": ("layout", "upload", "generic"),
    "vision": ("domain", "vision", "generic"),
    "contract": ("domain", "contract", "contract"),
    "queued": ("runtime", "queue", "generic"),
    "worker_claimed": ("runtime", "worker", "generic"),
    "mineru_parsing": ("layout", "parser", "generic"),
    "mineru_validated": ("layout", "parser", "generic"),
    "chunks_persisting": ("context", "chunks", "generic"),
    "chunks_persisted": ("context", "chunks", "generic"),
    "quality_gates": ("domain", "quality", "warnings"),
    "search_ready": ("context", "search", "generic"),
    "runtime_enriching": ("context", "runtime", "generic"),
    "graph_enriching": ("context", "graph", "generic"),
    "materialization": ("context", "database", "generic"),
    "ready": ("context", "ready", "generic"),
    "ready_with_warnings": ("context", "warning", "warnings"),
    "failed": ("runtime", "failed", "generic"),
    "proof_readiness": ("context", "proof", "generic"),
}


def _stage_display_metadata(stage_id: str) -> tuple[str, str, str]:
    return _STAGE_DISPLAY_METADATA.get(stage_id, ("custom", "stage", "generic"))
```

When constructing `DocumentPipelineStageOut`, set:

```python
category, icon_hint, inspector_kind = _stage_display_metadata(stage_id)
```

and pass:

```python
category=category,
icon_hint=icon_hint,
inspector_kind=inspector_kind,
```

- [x] **Step 5: Update frontend icon and inspector selection**

In `frontend/src/features/document-evidence/document-pipeline-stage-flow.tsx`, update `iconForStage()` to prefer `stage.icon_hint`:

```tsx
function iconForStage(stage: DocumentPipelineStageOut) {
  if (stage.state === "warning" || stage.warning_count > 0) {
    return AlertTriangle;
  }
  if (stage.state === "running") {
    return Clock;
  }
  switch (stage.icon_hint) {
    case "contract":
      return ShieldCheck;
    case "graph":
      return GitBranch;
    case "chunks":
    case "database":
      return Database;
    case "ready":
      return CheckCircle2;
    case "upload":
    case "vision":
      return FileCheck2;
    default:
      return Circle;
  }
}
```

Update inspector checks:

```tsx
{stage.inspector_kind === "contract" ? <ContractInspector contract={contract} /> : null}
{stage.inspector_kind === "warnings" ? <WarningGroupList warningGroups={warningGroups} /> : null}
```

- [x] **Step 6: Add frontend regression test**

Append to `frontend/tests/document-pipeline-stage-flow.test.tsx`:

```tsx
it("renders backend-provided unknown stages with generic inspector", () => {
  render(
    <DocumentPipelineStageFlow
      timeline={{
        document_id: "doc-generic",
        filename: "generic-reference.pdf",
        status: "completed",
        latest_job_id: "job-generic",
        contract_version: 1,
        stages: [
          {
            id: "model_compiler",
            label: "Model compiler",
            state: "complete",
            detail: "Executed generated contract candidates.",
            order: 25,
            source: "job",
            progress: null,
            is_current: false,
            event_count: 1,
            warning_count: 0,
            chunk_count: null,
            started_at: null,
            completed_at: null,
            category: "custom",
            icon_hint: "stage",
            inspector_kind: "generic",
          },
        ],
        events: [
          {
            sequence: 1,
            stage_id: "model_compiler",
            label: "Model compiler",
            detail: "Executed generated contract candidates.",
            state: "complete",
            progress: null,
            occurred_at: null,
            source: "job",
            job_id: "job-generic",
            chunk_count: null,
            warning: null,
            evidence_refs: [],
            detail_payload: {},
          },
        ],
        contract: {
          contract_status: "metadata_only",
          verified: false,
          canonical_units: false,
          schema_type: "parent_item",
          repair_status: "unverified",
          validation_status: "unverified",
          validation_matched_units: 0,
          selected_strategy: null,
          rejection_reasons: [],
          detail_payload: {},
        },
        warning_groups: [],
        totals: {
          jobs: 1,
          chunks: 0,
          warnings: 0,
          graph_nodes: 0,
          graph_edges: 0,
          index_records: 0,
          graph_records: 0,
        },
        missing_sections: ["chunks"],
      }}
    />,
  );

  expect(screen.getByRole("button", { name: /Model compiler complete/i })).toBeInTheDocument();
  expect(screen.queryByText("Contract proof boundary")).not.toBeInTheDocument();
});
```

- [x] **Step 7: Run focused tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_document_pipeline_timeline.py -q
cd frontend; npm test -- document-pipeline-stage-flow.test.tsx --run
```

Expected: PASS.

- [x] **Step 8: Commit**

```powershell
git add backend/src/ragstudio/schemas/document_pipeline_timeline.py backend/src/ragstudio/services/document_pipeline_timeline_service.py frontend/src/api/generated.ts frontend/src/features/document-evidence/document-pipeline-stage-flow.tsx backend/tests/test_document_pipeline_timeline.py frontend/tests/document-pipeline-stage-flow.test.tsx
git commit -m "feat: expose backend stage display metadata"
```

---

### Task 7: Require Verified Contracts For Quality-Gate Reference Extraction

**Files:**
- Modify: `backend/src/ragstudio/services/domain_metadata_quality_gate.py`
- Modify: `backend/tests/test_domain_metadata_quality_gate.py`

- [x] **Step 1: Add failing regression for built-in reference extraction drift**

Append to `backend/tests/test_domain_metadata_quality_gate.py`:

```python
def test_metadata_only_hint_does_not_extract_builtin_colon_reference_units():
    metadata = DomainMetadata(
        domain="archive",
        language="mixed",
        custom_json={
            "reference_schema": {
                "type": "parent_item",
                "fields": {"parent_ref": "parent", "unit_ref": "unit"},
                "canonical_ref_template": "{parent_ref}:{unit_ref}",
            },
            "contract_status": "metadata_only",
            "quality_policy": {
                "required_scripts": ["arabic"],
                "missing_required_script_action": "warn",
            },
        },
    )
    chunk = AdapterChunk(
        text="[7:104] English-only body that looks like a reference.",
        source_location={"page": 1},
        metadata={},
    )

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        [chunk],
        domain_metadata=metadata,
    )

    assert report["index_quality_report"]["references"] == []
    assert "reference_unit_missing_expected_script" not in report["parser_quality"][
        "warning_counts"
    ]
```

- [x] **Step 2: Run the focused test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_domain_metadata_quality_gate.py::test_metadata_only_hint_does_not_extract_builtin_colon_reference_units -q
```

Expected: FAIL while `_labelled_reference_units()` still uses `CHAPTER_VERSE_PATTERN` without a verified executable contract.

- [x] **Step 3: Remove generic built-in reference fallbacks**

In `backend/src/ragstudio/services/domain_metadata_quality_gate.py`:

- Delete `CHAPTER_VERSE_PATTERN` from generic quality-gate extraction.
- Keep `BOOK_HADITH_PATTERN` only behind a legacy adapter path that is selected by a verified profile.
- Change `_reference_units()` so it calls `_contract_reference_units()` only when `semantics.reference_capability == "verified"` or an equivalent helper reports verified canonical-unit execution.
- Remove the unconditional `_labelled_reference_units(text)` branch from `_reference_units()`.
- Change `_has_reference()` so text patterns come from verified contract extractors or `profile.reference_patterns`; it must not return true because a generic `n:n` token exists in text.

- [x] **Step 4: Preserve verified-contract behavior**

Add a companion test in `backend/tests/test_domain_metadata_quality_gate.py` using a verified `domain_structure.primary_anchor` with named groups:

```python
def test_verified_contract_still_extracts_reference_units_for_quality_gate():
    metadata = DomainMetadata(
        domain="archive",
        language="mixed",
        custom_json={
            "reference_schema": {
                "type": "parent_item",
                "fields": {"parent_ref": "parent", "unit_ref": "unit"},
                "canonical_ref_template": "{parent_ref}:{unit_ref}",
            },
            "domain_structure": {
                "primary_anchor": {
                    "regex": r"Part\s+(?P<parent_ref>\d+)\s+Item\s+(?P<unit_ref>\d+)",
                    "unit": "item",
                    "verified": True,
                }
            },
            "reference_resolution": {"enabled": True, "build_canonical_units": True},
            "quality_policy": {
                "required_scripts": ["latin"],
                "missing_required_script_action": "warn",
            },
        },
    )
    chunk = AdapterChunk(
        text="Part 7 Item 104",
        source_location={"page": 1},
        metadata={},
    )

    report = DomainMetadataQualityGate().validate_adapter_chunks(
        [chunk],
        domain_metadata=metadata,
    )

    assert [
        record["reference"] for record in report["index_quality_report"]["references"]
    ] == ["7:104"]
```

- [x] **Step 5: Run focused tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_domain_metadata_quality_gate.py -q
```

Expected: PASS.

- [x] **Step 6: Commit**

```powershell
git add backend/src/ragstudio/services/domain_metadata_quality_gate.py backend/tests/test_domain_metadata_quality_gate.py
git commit -m "fix: require verified contracts for reference quality extraction"
```

---

### Task 8: Make Parser Script And Quality-Language Policy Explicit

**Files:**
- Modify: `backend/src/ragstudio/services/document_parser_service.py`
- Modify: `backend/src/ragstudio/services/parser_normalization.py`
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Modify: `backend/src/ragstudio/services/index_lifecycle_service.py`
- Create: `backend/src/ragstudio/services/domain_quality_policy.py`
- Modify: `backend/tests/test_document_parser_service.py`
- Modify: `backend/tests/test_parser_normalization.py`

- [x] **Step 1: Add failing parser language regression**

Append to `backend/tests/test_document_parser_service.py`:

```python
def test_expected_language_does_not_use_domain_name_substrings(tmp_path):
    service = DocumentParserService(EventSession(), tmp_path)
    options = IndexDocumentIn(
        domain_metadata=DomainMetadata(
            domain="quranic_archive_without_script_policy",
            language="",
            script="",
            tags=[],
        )
    )

    assert service._expected_language(options) == ""


def test_expected_language_uses_explicit_script_metadata(tmp_path):
    service = DocumentParserService(EventSession(), tmp_path)
    options = IndexDocumentIn(
        domain_metadata=DomainMetadata(
            domain="archive",
            language="mixed",
            script="arabic",
        )
    )

    assert service._expected_language(options) == "arabic"
```

- [x] **Step 2: Run parser language tests to verify the first test fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_document_parser_service.py::test_expected_language_does_not_use_domain_name_substrings backend/tests/test_document_parser_service.py::test_expected_language_uses_explicit_script_metadata -q
```

Expected: FAIL because `_expected_language()` currently returns `arabic` when `quran` or `arabic` appears in the domain name.

- [x] **Step 3: Remove domain-substring parser language inference**

In `backend/src/ragstudio/services/document_parser_service.py`, change `_expected_language()` to:

- Return `arabic` only when `metadata.script` or `metadata.language` explicitly declares `arabic` or `ar`.
- Return `metadata.language` otherwise.
- Do not read `metadata.domain`, `document_type`, `collection`, `content_role`, or `tags` for extraction-language enforcement.

- [x] **Step 4: Add parser normalization recovery-label regression**

Append to `backend/tests/test_parser_normalization.py`:

```python
def test_parser_normalization_recovery_messages_are_domain_neutral():
    source = (
        Path("backend/src/ragstudio/services/parser_normalization.py")
        .read_text(encoding="utf-8")
        .casefold()
    )

    assert "verse header" not in source
    assert "reference header and its body text" in source
```

Then replace the hardcoded warning text in `parser_normalization.py` with:

```python
"Recovered omitted reference text from the PDF text layer between "
"a reference header and its body text."
```

- [x] **Step 5: Share quality-language policy instead of duplicating domain checks**

Create or reuse a small helper in a service module such as `backend/src/ragstudio/services/domain_quality_policy.py`:

```python
from ragstudio.schemas.parsing import DomainMetadata


def quality_language_from_metadata(metadata: DomainMetadata) -> str:
    if metadata.script and metadata.script.casefold() in {"arabic", "ar"}:
        return "arabic"
    if metadata.language and metadata.language.casefold() in {"arabic", "ar"}:
        return "arabic"
    quality_policy = metadata.custom_json.get("quality_policy")
    if isinstance(quality_policy, dict):
        scripts = quality_policy.get("required_scripts")
        if isinstance(scripts, list) and "arabic" in {str(item).casefold() for item in scripts}:
            return "arabic"
    return "unknown"
```

Update both `chunk_service.py` and `index_lifecycle_service.py` to call this helper. Remove their duplicate `"quran" in combined or "arabic" in combined` logic.

- [x] **Step 6: Add focused quality-language tests**

Add tests near the chunk and lifecycle service helpers or in a new focused test file:

```python
def test_quality_language_does_not_use_domain_name_substrings():
    assert quality_language_from_metadata(
        DomainMetadata(domain="quranic_archive_without_script_policy")
    ) == "unknown"


def test_quality_language_uses_declared_script_policy():
    assert quality_language_from_metadata(
        DomainMetadata(
            domain="archive",
            custom_json={"quality_policy": {"required_scripts": ["arabic"]}},
        )
    ) == "arabic"
```

- [x] **Step 7: Run focused tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_document_parser_service.py backend/tests/test_parser_normalization.py -q
python -m ruff check backend/src/ragstudio/services/document_parser_service.py backend/src/ragstudio/services/parser_normalization.py backend/src/ragstudio/services/chunk_service.py backend/src/ragstudio/services/index_lifecycle_service.py
```

Expected: PASS.

- [x] **Step 8: Commit**

```powershell
git add backend/src/ragstudio/services/document_parser_service.py backend/src/ragstudio/services/parser_normalization.py backend/src/ragstudio/services/chunk_service.py backend/src/ragstudio/services/index_lifecycle_service.py backend/src/ragstudio/services/domain_quality_policy.py backend/tests/test_document_parser_service.py backend/tests/test_parser_normalization.py
git commit -m "fix: make parser script policy explicit"
```

---

### Task 9: Make Graph Relationship Vocabulary Contract-Declared

**Files:**
- Modify: `backend/src/ragstudio/services/mineru_relationship_builder.py`
- Modify: `backend/src/ragstudio/services/metadata_json_schema.py`
- Modify: `backend/tests/test_mineru_relationship_builder.py`
- Modify: `backend/tests/test_metadata_json_schema.py`

- [x] **Step 1: Add failing generic graph edge test**

Append to `backend/tests/test_mineru_relationship_builder.py`:

```python
def test_mineru_relationship_builder_uses_generic_reference_neighbor_edges():
    chunks = [
        AdapterChunk(
            text="[113:1] First unit.",
            source_location={"page": 1},
            metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
        ),
        AdapterChunk(
            text="[113:2] Second unit.",
            source_location={"page": 1},
            metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 1}},
        ),
    ]

    annotated = MinerURelationshipBuilder().annotate(
        chunks,
        quran_metadata(edge_types=["references", "previous_reference", "next_reference"]),
    )

    relationships = annotated[0].metadata["relationship_metadata"]["graph_relationships"]
    assert {
        "type": "next_reference",
        "source": "ref:113:1",
        "target": "ref:113:2",
        "evidence": "reference_metadata",
    } in relationships
    assert all(item["type"] != "next_ayah" for item in relationships)
```

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_mineru_relationship_builder.py::test_mineru_relationship_builder_uses_generic_reference_neighbor_edges -q
```

Expected: FAIL because `_reference_neighbor_edge_type()` currently checks `next_ayah`, `next_verse`, and `next_hadith` before generic forms and does not select `next_reference`.

- [x] **Step 3: Replace default edge candidates**

In `backend/src/ragstudio/services/mineru_relationship_builder.py`, change `_reference_neighbor_edge_type()` so generic policy names are the default:

```python
candidates = (
    f"{direction}_reference",
    f"{direction}_ref",
    direction,
)
```

If bundled profiles still need old edge names, migrate the profile metadata to generic edge names instead of keeping alias literals in `mineru_relationship_builder.py`. Legacy naming can be documented in fixtures or migration notes, but generic graph construction must not carry domain-shaped edge vocabulary.

- [x] **Step 4: Normalize schema examples**

In `backend/src/ragstudio/services/metadata_json_schema.py`, update `REFERENCE_CUSTOM_JSON_EXAMPLE`:

- Replace `boost_same_chapter` with `boost_same_parent_reference`.
- Replace `boost_neighbor_verses` with `boost_neighbor_references`.
- Replace graph `node_types` values `chapter` and `verse` with `reference_parent` and `reference_unit`.
- Prefer generic edge names `previous_reference` and `next_reference`.

- [x] **Step 5: Add schema example test**

Append to `backend/tests/test_metadata_json_schema.py`:

```python
def test_reference_custom_json_example_uses_generic_reference_vocabulary():
    from ragstudio.services.metadata_json_schema import REFERENCE_CUSTOM_JSON_EXAMPLE

    text = repr(REFERENCE_CUSTOM_JSON_EXAMPLE).casefold()

    assert "boost_same_chapter" not in text
    assert "boost_neighbor_verses" not in text
    assert "chapter" not in REFERENCE_CUSTOM_JSON_EXAMPLE["graph"]["node_types"]
    assert "verse" not in REFERENCE_CUSTOM_JSON_EXAMPLE["graph"]["node_types"]
```

- [x] **Step 6: Run focused tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_mineru_relationship_builder.py backend/tests/test_metadata_json_schema.py -q
python -m ruff check backend/src/ragstudio/services/mineru_relationship_builder.py backend/src/ragstudio/services/metadata_json_schema.py
```

Expected: PASS.

- [x] **Step 7: Commit**

```powershell
git add backend/src/ragstudio/services/mineru_relationship_builder.py backend/src/ragstudio/services/metadata_json_schema.py backend/tests/test_mineru_relationship_builder.py backend/tests/test_metadata_json_schema.py
git commit -m "fix: make graph reference edges contract-declared"
```

---

### Task 10: Make Query Understanding Consume Verified Contract Hints

**Files:**
- Modify: `backend/src/ragstudio/services/query_understanding.py`
- Modify: `backend/src/ragstudio/services/retrieval_evidence.py`
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Modify: `backend/src/ragstudio/services/reference_contracts.py`
- Modify: `backend/src/ragstudio/services/reference_query_parser.py`
- Modify: `backend/tests/test_query_understanding.py`
- Modify: `backend/tests/test_retrieval_orchestrator.py`

- [x] **Step 1: Add failing generic reference-query tests**

Append to `backend/tests/test_query_understanding.py`:

```python
def test_understanding_does_not_treat_bare_colon_reference_as_global_contract():
    understanding = understand_query("show 19:13")

    assert understanding.intent != "reference"
    assert understanding.reference_hints == []


def test_understanding_uses_verified_reference_contract_patterns():
    understanding = understand_query(
        "show Article 12.7",
        reference_contracts=[
            {
                "reference_contract": {
                    "verified": True,
                    "canonical_units": True,
                    "canonical_ref_template": "article:{article}:clause:{clause}",
                    "required_groups": ["article", "clause"],
                    "patterns": [
                        r"Article\s+(?P<article>\d+)\.(?P<clause>\d+)"
                    ],
                }
            }
        ],
    )

    assert understanding.intent == "reference"
    assert understanding.reference_hints == ["article:12:clause:7"]
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_query_understanding.py::test_understanding_does_not_treat_bare_colon_reference_as_global_contract backend/tests/test_query_understanding.py::test_understanding_uses_verified_reference_contract_patterns -q
```

Expected: FAIL because `understand_query()` currently uses the global `REFERENCE_PATTERN` and has no `reference_contracts` input.

- [x] **Step 3: Extend query understanding inputs**

In `backend/src/ragstudio/services/query_understanding.py`:

- Add an optional `reference_contracts: list[dict[str, Any]] | None = None` argument to `understand_query()`.
- Replace `_reference_hints(query)` with `_reference_hints(query, reference_contracts=reference_contracts)`.
- Implement `_reference_hints()` through `parse_query_references()` from `reference_query_parser.py`.
- Keep legacy `REFERENCE_PATTERN` only behind an explicit compatibility flag supplied by a verified profile or caller option.

- [x] **Step 4: Gate compact Arabic exact-token intent through script evidence**

Change the compact Arabic branch so it activates only when one of these is true:

- `domain_expansion` has an `arabic` script expansion.
- The caller passes a declared script policy that includes `arabic`.
- The query is already inside a document scope whose metadata declares Arabic script support.

If none of those is true, preserve Arabic text as a semantic query with optional normalized variants, but do not force `reference_first_hybrid`.

- [x] **Step 5: Update callers and tests**

Update callers that already have document metadata, query expansion, or reference contracts so they pass the new argument. Keep existing Quran and Hadith tests passing by passing verified contracts from the document metadata, not by relying on global patterns.

- [x] **Step 6: Run focused tests**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_query_understanding.py backend/tests/test_reference_query_parser.py backend/tests/test_retrieval_orchestrator.py -q
python -m ruff check backend/src/ragstudio/services/query_understanding.py
```

Expected: PASS.

- [x] **Step 7: Commit**

```powershell
git add backend/src/ragstudio/services/query_understanding.py backend/src/ragstudio/services/retrieval_evidence.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/src/ragstudio/services/reference_contracts.py backend/src/ragstudio/services/reference_query_parser.py backend/tests/test_query_understanding.py backend/tests/test_retrieval_orchestrator.py
git commit -m "fix: make query understanding contract-aware"
```

---

### Task 11: Add Architecture Drift Guards And Documentation

**Files:**
- Create: `backend/tests/test_architecture_drift_guards.py`
- Modify: `docs/architecture/hardcoded-policy-inventory.md`

- [ ] **Step 1: Add architecture drift guard tests**

Create `backend/tests/test_architecture_drift_guards.py`:

```python
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

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
]

DOMAIN_TERMS = [
    "quran",
    "surah",
    "ayah",
    "chapter_verse",
    "same_chapter",
    "boost_neighbor_verses",
    "verse header",
    "next_ayah",
    "previous_ayah",
    "\"quran\" in",
    "\"arabic\" in combined",
]


def test_generic_pipeline_files_do_not_reintroduce_domain_specific_terms():
    offenders: list[str] = []
    for relative_path in GENERIC_FILES:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        lowered = text.casefold()
        for term in DOMAIN_TERMS:
            if term.casefold() in lowered:
                offenders.append(f"{relative_path}: {term}")

    assert offenders == []


def test_reference_contract_inventory_records_proof_boundary():
    inventory = (
        REPO_ROOT / "docs/architecture/hardcoded-policy-inventory.md"
    ).read_text(encoding="utf-8")

    assert "identity.fields" in inventory
    assert "verified executable reference contracts" in inventory
    assert "metadata-only reference hints" in inventory
```

- [ ] **Step 2: Run guard tests to verify they fail**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_architecture_drift_guards.py -q
```

Expected: FAIL until the previous tasks remove generic-file domain terms and the inventory text is updated.

- [ ] **Step 3: Update hardcoded policy inventory**

In `docs/architecture/hardcoded-policy-inventory.md`, add this section:

```markdown
## Reference Contract Proof Boundary

- `reference_schema` and `domain_structure` are metadata-only reference hints until an executable contract is verified.
- Verified executable reference contracts require model-declared `identity.fields`, matching regex named groups, a valid `canonical_ref_template`, and successful execution on sampled pages.
- Generic retrieval and scoring code must consume verified contract capability, canonical references, identity ranges, and neighbor references. Domain-specific names such as `chapter`, `verse`, `surah`, and `ayah` belong in adapter fixtures or display adapters.
- Legacy reference regexes are compatibility adapters. They must be selected by an explicit verified profile and must not run as global fallback enforcement.
- Stage-flow UI metadata is backend-owned. React may provide fallback icons, but it must not be the source of truth for pipeline stage vocabulary.
```

- [ ] **Step 4: Run full focused validation**

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_reference_contracts.py backend/tests/test_domain_classifier.py backend/tests/test_reference_metadata.py backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_reference_query_parser.py backend/tests/test_query_hypothesis_service.py backend/tests/test_document_pipeline_timeline.py backend/tests/test_domain_metadata_quality_gate.py backend/tests/test_document_parser_service.py backend/tests/test_parser_normalization.py backend/tests/test_mineru_relationship_builder.py backend/tests/test_metadata_json_schema.py backend/tests/test_query_understanding.py backend/tests/test_architecture_drift_guards.py -q
cd frontend; npm test -- document-pipeline-stage-flow.test.tsx --run
python -m ruff check backend/src/ragstudio/services/reference_contracts.py backend/src/ragstudio/services/domain_classifier.py backend/src/ragstudio/services/reference_metadata.py backend/src/ragstudio/services/hybrid_chunk_search.py backend/src/ragstudio/services/reference_query_parser.py backend/src/ragstudio/services/query_hypothesis_service.py backend/src/ragstudio/services/evidence_first_answer_service.py backend/src/ragstudio/services/document_pipeline_timeline_service.py backend/src/ragstudio/services/domain_metadata_quality_gate.py backend/src/ragstudio/services/document_parser_service.py backend/src/ragstudio/services/parser_normalization.py backend/src/ragstudio/services/chunk_service.py backend/src/ragstudio/services/index_lifecycle_service.py backend/src/ragstudio/services/mineru_relationship_builder.py backend/src/ragstudio/services/metadata_json_schema.py backend/src/ragstudio/services/query_understanding.py backend/src/ragstudio/services/domain_quality_policy.py backend/tests/test_architecture_drift_guards.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/tests/test_architecture_drift_guards.py docs/architecture/hardcoded-policy-inventory.md
git commit -m "test: guard generic pipeline against architecture drift"
```

---

## Final Verification

Run:

```powershell
$env:PYTHONPATH='backend/src'; python -m pytest backend/tests/test_reference_contracts.py backend/tests/test_domain_classifier.py backend/tests/test_reference_metadata.py backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_reference_query_parser.py backend/tests/test_query_hypothesis_service.py backend/tests/test_query_hypothesis_verifier.py backend/tests/test_document_pipeline_timeline.py backend/tests/test_domain_metadata_quality_gate.py backend/tests/test_document_parser_service.py backend/tests/test_parser_normalization.py backend/tests/test_mineru_relationship_builder.py backend/tests/test_metadata_json_schema.py backend/tests/test_query_understanding.py backend/tests/test_architecture_drift_guards.py -q
python -m ruff check backend/src/ragstudio/services/reference_contracts.py backend/src/ragstudio/services/domain_classifier.py backend/src/ragstudio/services/retrieval_evidence.py backend/src/ragstudio/services/chunk_lexical_search_repository.py backend/src/ragstudio/services/reference_metadata.py backend/src/ragstudio/services/hybrid_chunk_search.py backend/src/ragstudio/services/retrieval_policy.py backend/src/ragstudio/services/reference_query_parser.py backend/src/ragstudio/services/query_hypothesis_service.py backend/src/ragstudio/services/query_hypothesis_verifier.py backend/src/ragstudio/services/evidence_first_answer_service.py backend/src/ragstudio/services/document_pipeline_timeline_service.py backend/src/ragstudio/services/domain_metadata_quality_gate.py backend/src/ragstudio/services/document_parser_service.py backend/src/ragstudio/services/parser_normalization.py backend/src/ragstudio/services/chunk_service.py backend/src/ragstudio/services/index_lifecycle_service.py backend/src/ragstudio/services/mineru_relationship_builder.py backend/src/ragstudio/services/metadata_json_schema.py backend/src/ragstudio/services/query_understanding.py backend/src/ragstudio/services/domain_quality_policy.py backend/tests/test_architecture_drift_guards.py
cd frontend; npm test -- document-pipeline-stage-flow.test.tsx --run
```

Expected: all commands pass.

---

## Self-Review

**Spec coverage:** The plan covers the three pillars. Domain-aware behavior is covered by Tasks 1, 2, 4, 5, 7, 8, 9, and 10. Layout-aware stage flow and parser recovery wording are covered by Tasks 6 and 8. Context-aware retrieval, query parsing, neighbor expansion, graph edges, and answer rendering are covered by Tasks 3, 4, 5, 9, and 10. Drift prevention is covered by Task 11.

**Placeholder scan:** This plan contains no placeholder implementation steps. Every code-changing step identifies exact files, code blocks, commands, and expected results.

**Type consistency:** The new reference capability helpers are named consistently across tasks: `metadata_has_reference_hint`, `metadata_has_verified_reference_contract`, `metadata_list_has_reference_hint`, and `metadata_list_has_verified_reference_contract`. Stage metadata fields are consistently named `category`, `icon_hint`, and `inspector_kind` across backend schema, backend service, and frontend rendering. Shared parser and quality policy helpers use the explicit name `quality_language_from_metadata`.

---

Plan complete and saved to `docs/superpowers/plans/2026-05-25-three-pillar-architecture-drift-cleanup.md`. Two execution options:

**1. Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, with checkpoints for review.

Which approach?
