# AI-Informed Domain Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich every built-in domain profile with conservative AI-informed defaults, make autosuggest refine the selected profile instead of ignoring it, and use MinerU structure to produce relationship-aware chunk metadata.

**Architecture:** Keep built-in profiles in `DomainMetadataService`, add lookup support for selected profiles, and keep profile-aware AI merge logic inside `DomainMetadataAiSuggester`. Add conservative `custom_json.graph` validation and a focused MinerU relationship builder that annotates normalized chunks before persistence. The frontend already sends `profile_id`, so UI changes are limited to regression coverage for the existing contract.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy async tests, pytest/pytest-asyncio, React, Vitest, Testing Library.

**Implementation Status:** Implemented on 2026-05-09. The unchecked task boxes below are preserved as the original execution plan; current verification is tracked in the review results for this change set.

---

## File Structure

- Modify `backend/src/ragstudio/services/domain_metadata_service.py`
  - Owns built-in profile definitions.
  - Adds lookup method for `profile_id`.
- Modify `backend/src/ragstudio/services/domain_metadata_ai_suggester.py`
  - Accepts selected baseline profile metadata.
  - Adds profile-aware prompt context.
  - Adds deterministic metadata merge helpers.
- Modify `backend/src/ragstudio/services/metadata_json_schema.py`
  - Validates conservative `custom_json.graph` semantics.
- Create `backend/src/ragstudio/services/mineru_relationship_builder.py`
  - Converts MinerU-normalized chunk order plus domain profile semantics into evidence-backed relationship metadata.
- Modify `backend/src/ragstudio/services/chunk_service.py`
  - Applies MinerU relationship annotations after chunk splitting and before persistence.
- Modify `backend/src/ragstudio/services/index_lifecycle_service.py`
  - Applies the same relationship annotations for runtime indexing mirrored chunks.
- Modify `backend/src/ragstudio/api/routes/domain_profiles.py`
  - Resolves `profile_id`.
  - Returns `404` for unknown profiles.
  - Passes selected baseline metadata into the suggester.
- Modify `backend/tests/test_domain_metadata.py`
  - Covers built-in profile defaults, lookup, endpoint wiring, merge rules, and errors.
- Create `backend/tests/test_mineru_relationship_builder.py`
  - Covers relationship metadata generated from MinerU-style chunks.
- Modify `backend/tests/test_chunks.py`
  - Covers persisted relationship-aware chunk metadata.
- Modify `frontend/tests/domain-metadata-panel.test.tsx`
  - Verifies selected profile id is sent and returned metadata updates the form.

---

### Task 1: Enrich Built-In Profiles

**Files:**
- Modify: `backend/src/ragstudio/services/domain_metadata_service.py`
- Test: `backend/tests/test_domain_metadata.py`

- [ ] **Step 1: Write failing tests for built-in profile defaults**

Append these tests to `backend/tests/test_domain_metadata.py` near the existing domain profile tests:

```python
from ragstudio.services.domain_metadata_service import DomainMetadataService


def test_builtin_profiles_have_valid_conservative_custom_json(tmp_path):
    profiles = DomainMetadataService(tmp_path).list_profiles()

    assert {profile.id for profile in profiles} == {
        "generic",
        "research_paper",
        "policy_admin",
        "table_spreadsheet",
        "hadith",
        "quran_tafseer",
        "fatwa_fiqh",
    }
    for profile in profiles:
        validate_custom_json(profile.metadata.custom_json)
        assert profile.metadata.source is None
        assert profile.metadata.authority is None
        if profile.id != "generic":
            assert profile.metadata.tags


def test_builtin_hadith_profile_has_book_hadith_reference_semantics(tmp_path):
    profile = DomainMetadataService(tmp_path).get_profile("hadith")

    assert profile is not None
    assert profile.metadata.domain == "hadith"
    assert profile.metadata.citation_style == "book_hadith"
    assert profile.metadata.custom_json == {
        "reference_schema": {
            "type": "book_hadith",
            "display": "Book {book}, Hadith {hadith}",
            "fields": {
                "book": "book_number",
                "hadith": "hadith_number",
                "chapter": "chapter_title",
            },
        },
        "relationships": {
            "previous": ["same_book", "hadith - 1"],
            "next": ["same_book", "hadith + 1"],
            "book": ["same_book"],
            "chapter": ["same_chapter"],
        },
        "chunking": {
            "unit": "hadith",
            "include_neighbors": 1,
            "preserve_parallel_text": True,
        },
        "retrieval": {
            "exact_reference_top1": True,
            "boost_same_chapter": True,
            "boost_neighbor_verses": True,
        },
        "graph": {
            "node_types": ["collection", "book", "chapter", "hadith", "chunk"],
            "edge_types": ["contains", "next_hadith", "same_book", "same_chapter"],
            "materialize_from": ["mineru_structure", "reference_metadata"],
            "confidence_policy": "evidence_required",
        },
    }


def test_builtin_quran_profile_has_chapter_verse_reference_semantics(tmp_path):
    profile = DomainMetadataService(tmp_path).get_profile("quran_tafseer")

    assert profile is not None
    assert profile.metadata.citation_style == "surah_ayah"
    assert profile.metadata.custom_json["reference_schema"]["type"] == "chapter_verse"
    assert profile.metadata.custom_json["chunking"]["unit"] == "verse"
    assert profile.metadata.custom_json["graph"]["node_types"] == [
        "surah",
        "ayah",
        "translation",
        "chunk",
    ]
    assert profile.metadata.custom_json["retrieval"]["exact_reference_top1"] is True
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_domain_metadata.py::test_builtin_profiles_have_valid_conservative_custom_json \
  backend/tests/test_domain_metadata.py::test_builtin_hadith_profile_has_book_hadith_reference_semantics \
  backend/tests/test_domain_metadata.py::test_builtin_quran_profile_has_chapter_verse_reference_semantics \
  -q
```

Expected: FAIL because `get_profile` does not exist and built-ins lack `custom_json`.

- [ ] **Step 3: Implement built-in profile defaults and lookup**

In `backend/src/ragstudio/services/domain_metadata_service.py`, add this helper near imports:

```python
def reference_custom_json(
    *,
    reference_type: str | None = None,
    display: str | None = None,
    fields: dict[str, str] | None = None,
    relationships: dict[str, list[str]] | None = None,
    chunking: dict[str, object] | None = None,
    retrieval: dict[str, bool] | None = None,
    graph: dict[str, object] | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {}
    if reference_type or display or fields:
        schema: dict[str, object] = {}
        if reference_type:
            schema["type"] = reference_type
        if display:
            schema["display"] = display
        if fields:
            schema["fields"] = fields
        value["reference_schema"] = schema
    if relationships:
        value["relationships"] = relationships
    if chunking:
        value["chunking"] = chunking
    if retrieval:
        value["retrieval"] = retrieval
    if graph:
        value["graph"] = graph
    return value
```

Update each built-in `DomainMetadata(...)` with conservative defaults:

```python
metadata=DomainMetadata(
    domain="generic",
    document_type="document",
    tags=["document"],
    expected_structure="sections",
    custom_json=reference_custom_json(chunking={"unit": "section"}),
)
```

```python
metadata=DomainMetadata(
    domain="research",
    document_type="paper",
    tags=["research", "paper", "academic", "figures", "tables"],
    citation_style="academic",
    expected_structure="abstract_sections_references",
    custom_json=reference_custom_json(
        chunking={"unit": "section", "preserve_parallel_text": False},
        retrieval={"boost_same_chapter": True},
    ),
)
```

```python
metadata=DomainMetadata(
    domain="policy",
    document_type="admin_document",
    tags=["policy", "admin", "procedure", "governance"],
    citation_style="section",
    expected_structure="sections",
    reference_pattern="section_number",
    custom_json=reference_custom_json(
        reference_type="section",
        display="Section {section}",
        fields={"section": "section_number"},
        relationships={"section": ["same_section"], "next": ["next_section"]},
        chunking={"unit": "section"},
        retrieval={"exact_reference_top1": True, "boost_same_chapter": True},
    ),
)
```

```python
metadata=DomainMetadata(
    domain="data",
    document_type="table",
    tags=["table", "spreadsheet", "rows", "columns"],
    expected_structure="rows",
    custom_json=reference_custom_json(
        chunking={"unit": "row"},
        retrieval={"exact_reference_top1": False},
    ),
)
```

```python
metadata=DomainMetadata(
    domain="hadith",
    document_type="collection",
    language="mixed",
    tags=["hadith", "islamic_text", "arabic", "english", "religious_text"],
    citation_style="book_hadith",
    expected_structure="book_chapter_hadith",
    reference_pattern="Book N, Hadith N",
    script="mixed",
    content_role="primary_source",
    custom_json=reference_custom_json(
        reference_type="book_hadith",
        display="Book {book}, Hadith {hadith}",
        fields={
            "book": "book_number",
            "hadith": "hadith_number",
            "chapter": "chapter_title",
        },
        relationships={
            "previous": ["same_book", "hadith - 1"],
            "next": ["same_book", "hadith + 1"],
            "book": ["same_book"],
            "chapter": ["same_chapter"],
        },
        chunking={
            "unit": "hadith",
            "include_neighbors": 1,
            "preserve_parallel_text": True,
        },
        retrieval={
            "exact_reference_top1": True,
            "boost_same_chapter": True,
            "boost_neighbor_verses": True,
        },
        graph={
            "node_types": ["collection", "book", "chapter", "hadith", "chunk"],
            "edge_types": ["contains", "next_hadith", "same_book", "same_chapter"],
            "materialize_from": ["mineru_structure", "reference_metadata"],
            "confidence_policy": "evidence_required",
        },
    ),
)
```

```python
metadata=DomainMetadata(
    domain="quran_tafseer",
    document_type="commentary",
    language="mixed",
    tags=["quran", "tafseer", "arabic", "english", "religious_text"],
    citation_style="surah_ayah",
    expected_structure="surah_ayah_sections",
    reference_pattern="surah_number:verse_number",
    script="mixed",
    content_role="tafseer",
    custom_json=reference_custom_json(
        reference_type="chapter_verse",
        display="{chapter}:{verse}",
        fields={
            "chapter": "surah_number",
            "verse": "ayah_number",
            "page": "page_number",
        },
        relationships={
            "previous": ["same_chapter", "verse - 1"],
            "next": ["same_chapter", "verse + 1"],
            "chapter": ["same_chapter"],
            "page": ["same_page"],
        },
        chunking={
            "unit": "verse",
            "include_neighbors": 1,
            "preserve_parallel_text": True,
        },
        retrieval={
            "exact_reference_top1": True,
            "boost_same_chapter": True,
            "boost_neighbor_verses": True,
        },
        graph={
            "node_types": ["surah", "ayah", "translation", "chunk"],
            "edge_types": ["contains", "next_ayah", "same_surah", "translation_of"],
            "materialize_from": ["mineru_structure", "reference_metadata"],
            "confidence_policy": "evidence_required",
        },
    ),
)
```

```python
metadata=DomainMetadata(
    domain="fiqh",
    document_type="fatwa",
    language="mixed",
    tags=["fatwa", "fiqh", "ruling", "islamic_law", "question_answer"],
    citation_style="question_answer",
    expected_structure="question_answer",
    script="mixed",
    content_role="fiqh ruling",
    custom_json=reference_custom_json(
        relationships={
            "topic": ["same_topic"],
            "question": ["answer"],
        },
        chunking={"unit": "question_answer"},
        retrieval={"boost_same_chapter": True},
    ),
)
```

Add this method to `DomainMetadataService`:

```python
def get_profile(self, profile_id: str) -> DomainProfileOut | None:
    return next((profile for profile in self.list_profiles() if profile.id == profile_id), None)
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_domain_metadata.py::test_builtin_profiles_have_valid_conservative_custom_json \
  backend/tests/test_domain_metadata.py::test_builtin_hadith_profile_has_book_hadith_reference_semantics \
  backend/tests/test_domain_metadata.py::test_builtin_quran_profile_has_chapter_verse_reference_semantics \
  -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/domain_metadata_service.py backend/tests/test_domain_metadata.py
git commit -m "feat: enrich builtin domain profiles"
```

---

### Task 2: Wire Selected Profile Into Autosuggest Endpoint

**Files:**
- Modify: `backend/src/ragstudio/api/routes/domain_profiles.py`
- Test: `backend/tests/test_domain_metadata.py`

- [ ] **Step 1: Write failing endpoint tests**

Append these tests to `backend/tests/test_domain_metadata.py`:

```python
@pytest.mark.asyncio
async def test_domain_metadata_suggest_passes_selected_profile_to_suggester(
    client,
    monkeypatch,
):
    captured = {}

    async def fake_suggest(
        self,
        *,
        settings_profile,
        filename,
        content_type,
        pages,
        sampler_warnings,
        baseline_profile=None,
    ):
        captured["baseline_profile"] = baseline_profile
        return DomainMetadataSuggestOut(
            domain_metadata=baseline_profile.model_copy(
                update={"metadata_sources": ["profile", "ai_llm"]}
            ),
            confidence=0.75,
            evidence_pages=[1],
            rationale="Profile was used as baseline.",
            warnings=[],
        )

    monkeypatch.setattr(
        "ragstudio.services.domain_metadata_ai_suggester.DomainMetadataAiSuggester.suggest",
        fake_suggest,
    )

    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="vision-model",
                llm_base_url="http://llm.test/v1",
                llm_capabilities=["vision"],
                embedding_model="embedding-model",
                storage_backend="postgres",
            )
        )
        await session.commit()

    response = await client.post(
        "/api/domain-profiles/suggest",
        data={"profile_id": "hadith"},
        files={"file": ("hadith.txt", b"Book 1, Hadith 1", "text/plain")},
    )

    assert response.status_code == 200
    assert captured["baseline_profile"].domain == "hadith"
    assert response.json()["domain_metadata"]["metadata_sources"] == ["profile", "ai_llm"]


@pytest.mark.asyncio
async def test_domain_metadata_suggest_unknown_profile_returns_404(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        session.add(
            SettingsProfile(
                id="default",
                provider="openai-compatible",
                llm_model="vision-model",
                llm_base_url="http://llm.test/v1",
                llm_capabilities=["vision"],
                embedding_model="embedding-model",
                storage_backend="postgres",
            )
        )
        await session.commit()

    response = await client.post(
        "/api/domain-profiles/suggest",
        data={"profile_id": "missing-profile"},
        files={"file": ("notes.txt", b"plain text", "text/plain")},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Domain profile not found."
```

Also import `DomainMetadataSuggestOut` at the top of the file:

```python
from ragstudio.schemas.parsing import DomainMetadataSuggestOut
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_domain_metadata.py::test_domain_metadata_suggest_passes_selected_profile_to_suggester \
  backend/tests/test_domain_metadata.py::test_domain_metadata_suggest_unknown_profile_returns_404 \
  -q
```

Expected: FAIL because the route discards `profile_id`.

- [ ] **Step 3: Implement endpoint profile lookup**

In `backend/src/ragstudio/api/routes/domain_profiles.py`, replace `del request, profile_id` with:

```python
    service = DomainMetadataService(request.app.state.settings.data_dir)
    baseline_profile = None
    if profile_id:
        profile = service.get_profile(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="Domain profile not found.")
        baseline_profile = profile.metadata
```

Then update the suggester call:

```python
        return await DomainMetadataAiSuggester().suggest(
            settings_profile=settings_profile,
            filename=filename,
            content_type=content_type,
            pages=pages,
            sampler_warnings=sampler.warnings,
            baseline_profile=baseline_profile,
        )
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_domain_metadata.py::test_domain_metadata_suggest_passes_selected_profile_to_suggester \
  backend/tests/test_domain_metadata.py::test_domain_metadata_suggest_unknown_profile_returns_404 \
  -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/api/routes/domain_profiles.py backend/tests/test_domain_metadata.py
git commit -m "feat: pass selected profile to autosuggest"
```

---

### Task 3: Add Profile-Aware Merge Logic

**Files:**
- Modify: `backend/src/ragstudio/services/domain_metadata_ai_suggester.py`
- Test: `backend/tests/test_domain_metadata.py`

- [ ] **Step 1: Write failing merge tests**

Append these tests to `backend/tests/test_domain_metadata.py`:

```python
def test_ai_metadata_merge_fills_empty_fields_and_unions_tags():
    suggester = DomainMetadataAiSuggester()
    baseline = DomainMetadata(
        domain="hadith",
        document_type="collection",
        language="unknown",
        tags=["hadith", "arabic"],
        metadata_sources=["profile"],
    )
    ai = DomainMetadata(
        domain="islamic_hadith",
        document_type="hadith_collection",
        language="arabic",
        tags=["hadith", "sahih_al_bukhari"],
        collection="sahih_al_bukhari",
        metadata_sources=["ai_vision"],
    )

    merged = suggester.merge_with_baseline(ai, baseline)

    assert merged.domain == "hadith"
    assert merged.document_type == "collection"
    assert merged.language == "arabic"
    assert merged.collection == "sahih_al_bukhari"
    assert merged.tags == ["hadith", "arabic", "sahih_al_bukhari"]
    assert merged.metadata_sources == ["profile", "ai_vision"]


def test_ai_metadata_merge_deep_merges_custom_json():
    suggester = DomainMetadataAiSuggester()
    baseline = DomainMetadata(
        custom_json={
            "reference_schema": {
                "type": "book_hadith",
                "display": "Book {book}, Hadith {hadith}",
                "fields": {"book": "book_number", "hadith": "hadith_number"},
            },
            "chunking": {"unit": "hadith", "include_neighbors": 1},
            "retrieval": {"exact_reference_top1": True},
            "graph": {
                "node_types": ["collection", "book", "chapter", "hadith", "chunk"],
                "edge_types": ["contains", "next_hadith"],
                "materialize_from": ["mineru_structure"],
                "confidence_policy": "evidence_required",
            },
        }
    )
    ai = DomainMetadata(
        custom_json={
            "reference_schema": {
                "type": "book_hadith",
                "fields": {"chapter": "chapter_title"},
            },
            "chunking": {"preserve_parallel_text": True},
            "retrieval": {"boost_same_chapter": True},
            "graph": {"edge_types": ["same_chapter"]},
        }
    )

    merged = suggester.merge_with_baseline(ai, baseline)

    assert merged.custom_json == {
        "reference_schema": {
            "type": "book_hadith",
            "display": "Book {book}, Hadith {hadith}",
            "fields": {
                "book": "book_number",
                "hadith": "hadith_number",
                "chapter": "chapter_title",
            },
        },
        "chunking": {
            "unit": "hadith",
            "include_neighbors": 1,
            "preserve_parallel_text": True,
        },
        "retrieval": {
            "exact_reference_top1": True,
            "boost_same_chapter": True,
        },
        "graph": {
            "node_types": ["collection", "book", "chapter", "hadith", "chunk"],
            "edge_types": ["contains", "next_hadith", "same_chapter"],
            "materialize_from": ["mineru_structure"],
            "confidence_policy": "evidence_required",
        },
    }
```

Also import `DomainMetadata` at the top:

```python
from ragstudio.schemas.parsing import DomainMetadata, DomainMetadataSuggestOut
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_domain_metadata.py::test_ai_metadata_merge_fills_empty_fields_and_unions_tags \
  backend/tests/test_domain_metadata.py::test_ai_metadata_merge_deep_merges_custom_json \
  -q
```

Expected: FAIL because `merge_with_baseline` does not exist.

- [ ] **Step 3: Implement merge helper**

In `backend/src/ragstudio/services/domain_metadata_ai_suggester.py`, update the `suggest`
signature:

```python
    async def suggest(
        self,
        *,
        settings_profile: SettingsProfile,
        filename: str,
        content_type: str,
        pages: list[SampledPage],
        sampler_warnings: list[str],
        baseline_profile: DomainMetadata | None = None,
    ) -> DomainMetadataSuggestOut:
```

After model validation and custom JSON normalization, merge with baseline:

```python
        metadata = suggestion.domain_metadata
        metadata.custom_json = self._normalize_custom_json(metadata.custom_json)
        if baseline_profile is not None:
            metadata = self.merge_with_baseline(metadata, baseline_profile)
        validate_custom_json(metadata.custom_json)
        ai_source = "ai_vision" if target.supports_images else "ai_llm"
        metadata.metadata_sources = self._merge_unique_strings(
            metadata.metadata_sources,
            [ai_source],
        )
```

Add these methods to the class:

```python
    def merge_with_baseline(
        self,
        ai_metadata: DomainMetadata,
        baseline: DomainMetadata,
    ) -> DomainMetadata:
        merged = baseline.model_copy(deep=True)
        for field in (
            "language",
            "authority",
            "source",
            "collection",
            "citation_style",
            "expected_structure",
            "reference_pattern",
            "script",
            "content_role",
        ):
            before = getattr(merged, field)
            after = getattr(ai_metadata, field)
            if self._is_empty_metadata_value(before) and not self._is_empty_metadata_value(after):
                setattr(merged, field, after)

        merged.tags = self._merge_unique_strings(baseline.tags, ai_metadata.tags)
        merged.metadata_sources = self._merge_unique_strings(
            ["profile", *baseline.metadata_sources],
            ai_metadata.metadata_sources,
        )
        merged.custom_json = self._merge_custom_json(
            baseline.custom_json,
            ai_metadata.custom_json,
        )
        return merged

    def _is_empty_metadata_value(self, value: object) -> bool:
        return value is None or value == "" or value == "unknown"

    def _merge_unique_strings(self, first: list[str], second: list[str]) -> list[str]:
        merged: list[str] = []
        for item in [*first, *second]:
            if isinstance(item, str) and item and item not in merged:
                merged.append(item)
        return merged

    def _merge_custom_json(
        self,
        baseline: dict[str, object],
        ai_value: dict[str, object],
    ) -> dict[str, object]:
        merged = self._normalize_custom_json(baseline)
        ai = self._normalize_custom_json(ai_value)
        for key in ("reference_schema", "relationships", "chunking", "retrieval", "graph"):
            base_section = merged.get(key)
            ai_section = ai.get(key)
            if isinstance(base_section, dict) and isinstance(ai_section, dict):
                merged[key] = self._deep_merge_dicts(base_section, ai_section)
            elif ai_section is not None and key not in merged:
                merged[key] = ai_section
        return merged

    def _deep_merge_dicts(
        self,
        first: dict[str, object],
        second: dict[str, object],
    ) -> dict[str, object]:
        merged = dict(first)
        for key, value in second.items():
            existing = merged.get(key)
            if isinstance(existing, dict) and isinstance(value, dict):
                merged[key] = self._deep_merge_dicts(existing, value)
            elif isinstance(existing, list) and isinstance(value, list):
                merged[key] = self._merge_unique_strings(existing, value)
            elif key not in merged or self._is_empty_metadata_value(existing):
                merged[key] = value
            elif key == "fields" and isinstance(existing, dict) and isinstance(value, dict):
                merged[key] = self._deep_merge_dicts(existing, value)
        return merged
```

In `_normalize_custom_json()`, preserve validated graph sections by adding this block after retrieval normalization:

```python
        graph = value.get("graph")
        if isinstance(graph, dict):
            graph_values: dict[str, object] = {}
            for key in ("node_types", "edge_types", "materialize_from"):
                items = graph.get(key)
                if isinstance(items, list):
                    strings = [item for item in items if isinstance(item, str) and item]
                    if strings:
                        graph_values[key] = strings
            confidence_policy = graph.get("confidence_policy")
            if confidence_policy == "evidence_required":
                graph_values["confidence_policy"] = confidence_policy
            if graph_values:
                normalized["graph"] = graph_values
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_domain_metadata.py::test_ai_metadata_merge_fills_empty_fields_and_unions_tags \
  backend/tests/test_domain_metadata.py::test_ai_metadata_merge_deep_merges_custom_json \
  -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/domain_metadata_ai_suggester.py backend/tests/test_domain_metadata.py
git commit -m "feat: merge autosuggest with selected profile"
```

---

### Task 4: Add Baseline Context To AI Prompt

**Files:**
- Modify: `backend/src/ragstudio/services/domain_metadata_ai_suggester.py`
- Test: `backend/tests/test_domain_metadata.py`

- [ ] **Step 1: Write failing prompt-context test**

Append this test to `backend/tests/test_domain_metadata.py`:

```python
@pytest.mark.asyncio
async def test_ai_domain_metadata_prompt_includes_selected_profile_context(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": """{
                              "domain_metadata": {
                                "domain": "hadith",
                                "document_type": "collection",
                                "tags": ["hadith"]
                              },
                              "confidence": 0.8,
                              "evidence_pages": [1],
                              "rationale": "The sample shows hadith references.",
                              "warnings": []
                            }"""
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            calls.append(json)
            return FakeResponse()

    monkeypatch.setattr(
        "ragstudio.services.domain_metadata_ai_suggester.httpx.AsyncClient",
        FakeClient,
    )

    await DomainMetadataAiSuggester().suggest(
        settings_profile=SettingsProfile(
            id="default",
            provider="openai-compatible",
            llm_model="vision-capable-model",
            llm_base_url="http://llm.test/v1",
            llm_capabilities=["vision"],
            embedding_model="embedding-model",
            storage_backend="postgres",
        ),
        filename="hadith.pdf",
        content_type="application/pdf",
        pages=[SampledPage(page_number=1, text="Book 1, Hadith 1")],
        sampler_warnings=[],
        baseline_profile=DomainMetadata(
            domain="hadith",
            document_type="collection",
            citation_style="book_hadith",
            tags=["hadith"],
        ),
    )

    prompt = calls[0]["messages"][0]["content"][0]["text"]
    assert "Selected baseline profile metadata" in prompt
    assert '"domain": "hadith"' in prompt
    assert '"citation_style": "book_hadith"' in prompt
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_domain_metadata.py::test_ai_domain_metadata_prompt_includes_selected_profile_context \
  -q
```

Expected: FAIL because the prompt does not include baseline metadata.

- [ ] **Step 3: Implement prompt context**

Change `_payload()` signature in `backend/src/ragstudio/services/domain_metadata_ai_suggester.py`:

```python
    def _payload(
        self,
        *,
        target: LlmTarget,
        filename: str,
        content_type: str,
        pages: list[SampledPage],
        baseline_profile: DomainMetadata | None = None,
    ) -> dict[str, object]:
```

Pass it from `suggest()`:

```python
        payload = self._payload(
            target=target,
            filename=filename,
            content_type=content_type,
            pages=pages,
            baseline_profile=baseline_profile,
        )
```

Change `_prompt()` signature:

```python
    def _prompt(
        self,
        *,
        filename: str,
        content_type: str,
        pages: list[SampledPage],
        baseline_profile: DomainMetadata | None = None,
    ) -> str:
```

Add this before the returned prompt:

```python
        baseline_text = (
            "No selected baseline profile."
            if baseline_profile is None
            else json.dumps(
                baseline_profile.model_dump(exclude_none=True),
                ensure_ascii=False,
                indent=2,
            )
        )
```

Include this paragraph inside the prompt:

```text
Selected baseline profile metadata:
{baseline_text}

When a baseline profile is provided, treat it as conservative domain guidance.
Fill empty fields from file evidence. Preserve strong baseline semantics unless
the sampled pages clearly contradict them. Do not copy file-specific values into
reusable profile assumptions.
```

- [ ] **Step 4: Run test to verify pass**

Run:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_domain_metadata.py::test_ai_domain_metadata_prompt_includes_selected_profile_context \
  -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/domain_metadata_ai_suggester.py backend/tests/test_domain_metadata.py
git commit -m "feat: include profile context in autosuggest prompt"
```

---

### Task 5: Verify Frontend Profile Autosuggest Contract

**Files:**
- Modify: `frontend/tests/domain-metadata-panel.test.tsx`

- [ ] **Step 1: Add regression test for selected profile and returned metadata**

Append this test to `frontend/tests/domain-metadata-panel.test.tsx`:

```tsx
it("sends selected profile id and applies profile-refined autosuggest metadata", async () => {
  const file = new File(["Book 1, Hadith 1"], "hadith.pdf", { type: "application/pdf" });
  vi.mocked(apiClient.suggestDomainMetadata).mockResolvedValue({
    domain_metadata: {
      domain: "hadith",
      document_type: "collection",
      language: "arabic",
      tags: ["hadith", "arabic"],
      citation_style: "book_hadith",
      custom_json: {
        chunking: { unit: "hadith" },
      },
      metadata_sources: ["profile", "ai_vision"],
    },
    confidence: 0.95,
    evidence_pages: [1, 2],
    rationale: "Selected Hadith profile refined by sampled pages.",
    warnings: [],
  });
  const onChange = vi.fn();

  render(
    <DomainMetadataPanel
      profiles={[
        {
          id: "hadith",
          name: "Hadith",
          description: "Hadith collection or commentary.",
          metadata: { domain: "hadith", document_type: "collection", tags: ["hadith"] },
        },
      ]}
      value={{
        parser_mode: "mineru_strict",
        domain_metadata: { domain: "generic", document_type: "document", tags: [] },
      }}
      onChange={onChange}
      suggestContext={{ filename: "hadith.pdf", content_type: "application/pdf", file }}
    />,
  );

  fireEvent.change(screen.getByLabelText("Domain profile"), {
    target: { value: "hadith" },
  });
  fireEvent.click(screen.getByRole("button", { name: /auto-suggest/i }));

  await waitFor(() => {
    expect(apiClient.suggestDomainMetadata).toHaveBeenCalledWith({
      file,
      profile_id: "hadith",
    });
  });
  await waitFor(() => {
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        domain_metadata: expect.objectContaining({
          domain: "hadith",
          language: "arabic",
          metadata_sources: ["profile", "ai_vision"],
          custom_json: { chunking: { unit: "hadith" } },
        }),
      }),
    );
  });
});
```

- [ ] **Step 2: Run test**

Run:

```bash
cd frontend && npm run test -- --run tests/domain-metadata-panel.test.tsx
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/domain-metadata-panel.test.tsx
git commit -m "test: cover profile-aware autosuggest contract"
```

---

### Task 6: Validate Graph Semantics In Custom JSON

**Files:**
- Modify: `backend/src/ragstudio/services/metadata_json_schema.py`
- Test: `backend/tests/test_domain_metadata.py`

- [ ] **Step 1: Write failing graph validation tests**

Append these tests to `backend/tests/test_domain_metadata.py` near the existing custom JSON validation tests:

```python
def test_validate_custom_json_accepts_graph_semantics():
    payload = {
        "graph": {
            "node_types": ["surah", "ayah", "chunk"],
            "edge_types": ["contains", "next_ayah", "references"],
            "materialize_from": ["mineru_structure", "reference_metadata"],
            "confidence_policy": "evidence_required",
        }
    }

    assert validate_custom_json(payload) == payload


def test_validate_custom_json_rejects_invalid_graph_node_types():
    with pytest.raises(ValueError, match="custom_json.graph.node_types"):
        validate_custom_json({"graph": {"node_types": ["chunk", 42]}})


def test_validate_custom_json_rejects_invalid_graph_confidence_policy():
    with pytest.raises(ValueError, match="custom_json.graph.confidence_policy"):
        validate_custom_json({"graph": {"confidence_policy": "guess_allowed"}})
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_domain_metadata.py::test_validate_custom_json_accepts_graph_semantics \
  backend/tests/test_domain_metadata.py::test_validate_custom_json_rejects_invalid_graph_node_types \
  backend/tests/test_domain_metadata.py::test_validate_custom_json_rejects_invalid_graph_confidence_policy \
  -q
```

Expected: FAIL because invalid `custom_json.graph` shapes are not rejected yet.

- [ ] **Step 3: Implement graph validation**

In `backend/src/ragstudio/services/metadata_json_schema.py`, add a graph example to `REFERENCE_CUSTOM_JSON_EXAMPLE`:

```python
    "graph": {
        "node_types": ["chapter", "verse", "chunk"],
        "edge_types": ["contains", "next", "references"],
        "materialize_from": ["mineru_structure", "reference_metadata"],
        "confidence_policy": "evidence_required",
    },
```

Update `validate_custom_json()`:

```python
    _validate_reference_schema(value.get("reference_schema"))
    _validate_relationships(value.get("relationships"))
    _validate_chunking(value.get("chunking"))
    _validate_retrieval(value.get("retrieval"))
    _validate_graph(value.get("graph"))
    return value
```

Add these helpers after `_validate_retrieval()`:

```python
def _validate_graph(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("custom_json.graph must be an object.")

    for key in ("node_types", "edge_types", "materialize_from"):
        _validate_string_list(value.get(key), f"custom_json.graph.{key}")

    confidence_policy = value.get("confidence_policy")
    if confidence_policy is not None and confidence_policy != "evidence_required":
        raise ValueError(
            "custom_json.graph.confidence_policy must be 'evidence_required'."
        )


def _validate_string_list(value: Any, name: str) -> None:
    if value is None:
        return
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings.")
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_domain_metadata.py::test_validate_custom_json_accepts_graph_semantics \
  backend/tests/test_domain_metadata.py::test_validate_custom_json_rejects_invalid_graph_node_types \
  backend/tests/test_domain_metadata.py::test_validate_custom_json_rejects_invalid_graph_confidence_policy \
  -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/metadata_json_schema.py backend/tests/test_domain_metadata.py
git commit -m "feat: validate graph metadata semantics"
```

---

### Task 7: Add MinerU Relationship-Aware Chunk Metadata

**Files:**
- Create: `backend/src/ragstudio/services/mineru_relationship_builder.py`
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Modify: `backend/src/ragstudio/services/index_lifecycle_service.py`
- Test: `backend/tests/test_mineru_relationship_builder.py`
- Test: `backend/tests/test_chunks.py`

- [ ] **Step 1: Write failing relationship builder tests**

Create `backend/tests/test_mineru_relationship_builder.py`:

```python
from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.mineru_relationship_builder import MinerURelationshipBuilder


def quran_metadata():
    return DomainMetadata(
        domain="quran_tafseer",
        document_type="commentary",
        citation_style="surah_ayah",
        expected_structure="surah_ayah_sections",
        tags=["quran", "religious_text"],
        custom_json={
            "reference_schema": {
                "type": "chapter_verse",
                "display": "{chapter}:{verse}",
                "fields": {"chapter": "surah_number", "verse": "ayah_number"},
            },
            "chunking": {"unit": "verse", "include_neighbors": 1},
            "graph": {
                "node_types": ["surah", "ayah", "chunk"],
                "edge_types": ["contains", "next_ayah", "references"],
                "materialize_from": ["mineru_structure", "reference_metadata"],
                "confidence_policy": "evidence_required",
            },
        },
    )


def test_mineru_relationship_builder_adds_reference_and_neighbor_edges():
    chunks = [
        AdapterChunk(
            text="[113:1] Say, I seek refuge in the Lord of daybreak.",
            source_location={"page": 1},
            metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
        ),
        AdapterChunk(
            text="[113:2] From the evil of that which He created.",
            source_location={"page": 1},
            metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 1}},
        ),
    ]

    annotated = MinerURelationshipBuilder().annotate(chunks, quran_metadata())

    first_relationships = annotated[0].metadata["relationship_metadata"]
    second_relationships = annotated[1].metadata["relationship_metadata"]
    assert first_relationships["references"] == ["113:1"]
    assert first_relationships["graph_relationships"] == [
        {
            "type": "references",
            "source": "chunk:0",
            "target": "ref:113:1",
            "evidence": "reference_metadata",
        },
        {
            "type": "next_ref",
            "source": "ref:113:1",
            "target": "ref:113:2",
            "evidence": "reference_metadata",
        },
        {
            "type": "next_chunk",
            "source": "chunk:0",
            "target": "chunk:1",
            "evidence": "mineru_order",
        },
    ]
    assert second_relationships["references"] == ["113:2"]
    assert second_relationships["graph_relationships"][1] == {
        "type": "previous_ref",
        "source": "ref:113:2",
        "target": "ref:113:1",
        "evidence": "reference_metadata",
    }


def test_mineru_relationship_builder_leaves_chunks_without_graph_profile_unchanged():
    chunk = AdapterChunk(
        text="[1:1] In the name of Allah.",
        source_location={"page": 1},
        metadata={"parser_metadata": {"backend": "mineru", "chunk_index": 0}},
    )

    annotated = MinerURelationshipBuilder().annotate([chunk], DomainMetadata())

    assert annotated == [chunk]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_mineru_relationship_builder.py -q
```

Expected: FAIL because `MinerURelationshipBuilder` does not exist.

- [ ] **Step 3: Implement relationship builder**

Create `backend/src/ragstudio/services/mineru_relationship_builder.py`:

```python
from __future__ import annotations

from typing import Any

from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.reference_metadata import ReferenceSemantics
from ragstudio.services.runtime_types import RuntimeChunk


class MinerURelationshipBuilder:
    def annotate(
        self,
        chunks: list[AdapterChunk],
        domain_metadata: DomainMetadata,
    ) -> list[AdapterChunk]:
        graph = self._graph(domain_metadata)
        if graph is None:
            return chunks

        semantics = ReferenceSemantics.from_metadata(domain_metadata)
        annotated: list[AdapterChunk] = []
        node_refs = [self._chunk_node_ref(chunk, index) for index, chunk in enumerate(chunks)]

        for index, chunk in enumerate(chunks):
            graph_relationships: list[dict[str, str]] = []
            references = [str(ref["ref"]) for ref in semantics.extract_chunk_references(chunk.text)]
            reference_metadata = semantics.derive_reference_metadata(
                chunk.text,
                chunk.source_location,
            )
            source = node_refs[index]

            for reference in references:
                graph_relationships.append(
                    {
                        "type": "references",
                        "source": source,
                        "target": f"ref:{reference}",
                        "evidence": "reference_metadata",
                    }
                )

            previous_ref = reference_metadata.get("previous_ref")
            if isinstance(previous_ref, str) and references:
                graph_relationships.append(
                    {
                        "type": "previous_ref",
                        "source": f"ref:{references[0]}",
                        "target": f"ref:{previous_ref}",
                        "evidence": "reference_metadata",
                    }
                )

            next_ref = reference_metadata.get("next_ref")
            if isinstance(next_ref, str) and references:
                graph_relationships.append(
                    {
                        "type": "next_ref",
                        "source": f"ref:{references[-1]}",
                        "target": f"ref:{next_ref}",
                        "evidence": "reference_metadata",
                    }
                )

            if index + 1 < len(chunks):
                graph_relationships.append(
                    {
                        "type": "next_chunk",
                        "source": source,
                        "target": node_refs[index + 1],
                        "evidence": "mineru_order",
                    }
                )

            if not graph_relationships and not references:
                annotated.append(chunk)
                continue

            metadata = dict(chunk.metadata)
            metadata["relationship_metadata"] = {
                "references": references,
                "graph_relationships": graph_relationships,
                "graph_profile": graph,
            }
            annotated.append(
                RuntimeChunk(
                    text=chunk.text,
                    source_location=chunk.source_location,
                    metadata=metadata,
                    runtime_source_id=chunk.runtime_source_id,
                    content_type=chunk.content_type,
                    preview_ref=chunk.preview_ref,
                )
            )

        return annotated

    def _graph(self, domain_metadata: DomainMetadata) -> dict[str, Any] | None:
        custom_json = domain_metadata.custom_json
        if not isinstance(custom_json, dict):
            return None
        graph = custom_json.get("graph")
        if not isinstance(graph, dict):
            return None
        materialize_from = graph.get("materialize_from")
        if isinstance(materialize_from, list) and not (
            "mineru_structure" in materialize_from
            or "reference_metadata" in materialize_from
        ):
            return None
        return graph

    def _chunk_node_ref(self, chunk: AdapterChunk, index: int) -> str:
        parser_metadata = chunk.metadata.get("parser_metadata")
        if isinstance(parser_metadata, dict):
            chunk_index = parser_metadata.get("chunk_index")
            if isinstance(chunk_index, int):
                return f"chunk:{chunk_index}"
        return f"chunk:{index}"
```

- [ ] **Step 4: Run relationship builder tests**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_mineru_relationship_builder.py -q
```

Expected: PASS.

- [ ] **Step 5: Wire builder into local and runtime indexing**

In `backend/src/ragstudio/services/chunk_service.py`, add this import:

```python
from ragstudio.services.mineru_relationship_builder import MinerURelationshipBuilder
```

Update `ChunkService.__init__()`:

```python
        relationship_builder: MinerURelationshipBuilder | None = None,
```

Set the instance property:

```python
        self.relationship_builder = relationship_builder or MinerURelationshipBuilder()
```

After `self.chunk_splitter.split(...)` in `index_document()`, add:

```python
        adapter_chunks = self.relationship_builder.annotate(
            adapter_chunks,
            options.domain_metadata,
        )
```

In `backend/src/ragstudio/services/index_lifecycle_service.py`, add this import:

```python
from ragstudio.services.mineru_relationship_builder import MinerURelationshipBuilder
```

After `ChunkSplitter().split(...)` in `reindex_document()`, add:

```python
        adapter_chunks = MinerURelationshipBuilder().annotate(
            adapter_chunks,
            options.domain_metadata,
        )
```

- [ ] **Step 6: Write persisted metadata regression test**

Append this test to `backend/tests/test_chunks.py`:

```python
@pytest.mark.asyncio
async def test_index_document_persists_relationship_aware_chunk_metadata(client):
    upload_response = await client.post(
        "/api/documents",
        files={
            "file": (
                "quran.txt",
                b"[113:1] Say, I seek refuge in the Lord of daybreak.\n"
                b"[113:2] From the evil of that which He created.",
                "text/plain",
            )
        },
    )
    document_id = upload_response.json()["id"]

    index_response = await client.post(
        f"/api/chunks/index/{document_id}",
        json={
            "parser_mode": "local_fallback",
            "domain_metadata": {
                "domain": "quran_tafseer",
                "document_type": "commentary",
                "citation_style": "surah_ayah",
                "expected_structure": "surah_ayah_sections",
                "tags": ["quran", "religious_text"],
                "custom_json": {
                    "reference_schema": {
                        "type": "chapter_verse",
                        "display": "{chapter}:{verse}",
                        "fields": {
                            "chapter": "surah_number",
                            "verse": "ayah_number",
                        },
                    },
                    "chunking": {"unit": "verse", "include_neighbors": 1},
                    "graph": {
                        "node_types": ["surah", "ayah", "chunk"],
                        "edge_types": ["contains", "next_ayah", "references"],
                        "materialize_from": [
                            "mineru_structure",
                            "reference_metadata",
                        ],
                        "confidence_policy": "evidence_required",
                    },
                },
            },
        },
    )

    assert index_response.status_code == 200
    chunks = index_response.json()
    assert chunks[0]["metadata"]["relationship_metadata"]["references"] == ["113:1"]
    assert {
        "type": "next_ref",
        "source": "ref:113:1",
        "target": "ref:113:2",
        "evidence": "reference_metadata",
    } in chunks[0]["metadata"]["relationship_metadata"]["graph_relationships"]
```

- [ ] **Step 7: Run persisted metadata test**

Run:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_chunks.py::test_index_document_persists_relationship_aware_chunk_metadata \
  -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add \
  backend/src/ragstudio/services/mineru_relationship_builder.py \
  backend/src/ragstudio/services/chunk_service.py \
  backend/src/ragstudio/services/index_lifecycle_service.py \
  backend/tests/test_mineru_relationship_builder.py \
  backend/tests/test_chunks.py
git commit -m "feat: add mineru relationship aware chunk metadata"
```

---

### Task 8: Full Verification

**Files:**
- Verify all files changed in Tasks 1-7.

- [ ] **Step 1: Run backend focused tests**

Run:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_domain_metadata.py \
  backend/tests/test_mineru_relationship_builder.py \
  backend/tests/test_chunks.py::test_index_document_persists_relationship_aware_chunk_metadata \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run backend lint**

Run:

```bash
.venv/bin/python -m ruff check \
  backend/src/ragstudio/services/domain_metadata_service.py \
  backend/src/ragstudio/services/domain_metadata_ai_suggester.py \
  backend/src/ragstudio/services/metadata_json_schema.py \
  backend/src/ragstudio/services/mineru_relationship_builder.py \
  backend/src/ragstudio/services/chunk_service.py \
  backend/src/ragstudio/services/index_lifecycle_service.py \
  backend/src/ragstudio/api/routes/domain_profiles.py \
  backend/tests/test_domain_metadata.py \
  backend/tests/test_mineru_relationship_builder.py \
  backend/tests/test_chunks.py
```

Expected: `All checks passed!`

- [ ] **Step 3: Run frontend domain metadata panel tests**

Run:

```bash
cd frontend && npm run test -- --run tests/domain-metadata-panel.test.tsx
```

Expected: PASS.

- [ ] **Step 4: Run frontend lint**

Run:

```bash
cd frontend && npm run lint -- --max-warnings=0
```

Expected: PASS.

- [ ] **Step 5: Smoke test profile list endpoint**

Run:

```bash
curl -sS http://127.0.0.1:8000/api/domain-profiles \
  | .venv/bin/python -m json.tool
```

Expected: Response includes seven profiles. The `hadith` profile includes
`custom_json.chunking.unit` as `hadith` and `custom_json.graph.edge_types` containing
`next_hadith`. The `quran_tafseer` profile includes `custom_json.chunking.unit` as
`verse` and `custom_json.graph.edge_types` containing `next_ayah`.

- [ ] **Step 6: Final commit if verification required fixes**

If Task 8 caused any additional edits, commit them:

```bash
git add backend frontend
git commit -m "test: verify ai informed domain profiles"
```
