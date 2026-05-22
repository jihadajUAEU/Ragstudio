# Arabic Recovery Gate Order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Arabic/Quran PDFs whose Arabic text is classified by MinerU as image blocks continue into PDF text-layer or vision recovery before required-script quality gates decide whether to block materialization.

**Architecture:** Keep MinerU strict as the required parser, but narrow the early extraction validator to parser health checks only: empty output, raw PDF syntax, non-MinerU backend, and page coverage. Compile domain metadata into an executable parser/layout contract so Quran-style uploads send OCR-oriented hints (`lang=arabic`, `table=false`, `formula=false`) while preserving image blocks as recovery candidates. Apply final Arabic/Latin required-script enforcement after content-list normalization and recovery in the existing domain quality gate.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy async ORM, pytest, Docker Compose backend test runner.

---

## File Structure

- Modify `backend/src/ragstudio/services/domain_metadata_contract_compiler.py`
  - Add parser hint compilation for Arabic chapter/verse contracts.
  - Preserve explicit `mineru_parse_options` from caller.
- Modify `backend/src/ragstudio/services/document_contract.py`
  - Persist the compiled parser contract and layout contract in `Document.index_contract`.
- Modify `backend/src/ragstudio/services/mineru_extraction_validator.py`
  - Remove early hard failure for `arabic_text_missing`.
  - Keep Arabic character counts for diagnostics.
- Modify `backend/src/ragstudio/services/document_parser_service.py`
  - Stop passing required language as an early blocking validator decision.
- Modify `backend/tests/test_document_contract.py`
  - Assert Quran/Arabic contracts persist parser and layout hints.
- Modify `backend/tests/test_domain_metadata_contract_compiler.py`
  - Assert compiled Quran options produce `MinerUParseOptionsIn(parse_method="ocr", lang="arabic", table=False, formula=False)`.
- Modify `backend/tests/test_mineru_extraction_validator.py`
  - Replace the missing-Arabic rejection expectation with a diagnostic count expectation.
- Modify `backend/tests/test_document_parser_service.py`
  - Assert raw MinerU text without Arabic is accepted by the parser service so downstream recovery/quality gates can run.

## Task 1: Compile Parser And Layout Hints Into The Upload Contract

**Files:**
- Modify: `backend/src/ragstudio/services/domain_metadata_contract_compiler.py`
- Modify: `backend/src/ragstudio/services/document_contract.py`
- Test: `backend/tests/test_domain_metadata_contract_compiler.py`
- Test: `backend/tests/test_document_contract.py`

- [ ] **Step 1: Write failing compiler test**

Add this test to `backend/tests/test_domain_metadata_contract_compiler.py`:

```python
def test_compile_quran_reference_contract_adds_mineru_parser_hints():
    options = compile_index_options(
        IndexDocumentIn(
            domain_metadata=DomainMetadata(
                domain="quran",
                language="mixed",
                script="arabic",
                reference_pattern="surah:verse",
                custom_json={"chunking": {"unit": "verse"}},
            )
        )
    )

    assert options.mineru_parse_options is not None
    assert options.mineru_parse_options.parse_method == "ocr"
    assert options.mineru_parse_options.lang == "arabic"
    assert options.mineru_parse_options.table is False
    assert options.mineru_parse_options.formula is False
```

- [ ] **Step 2: Run compiler test to verify it fails**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_domain_metadata_contract_compiler.py::test_compile_quran_reference_contract_adds_mineru_parser_hints -q
```

Expected: FAIL because `mineru_parse_options` is currently `None`.

- [ ] **Step 3: Implement parser hint compilation**

In `backend/src/ragstudio/services/domain_metadata_contract_compiler.py`, update `compile_index_options`:

```python
def compile_index_options(options: IndexDocumentIn) -> IndexDocumentIn:
    domain_metadata = compile_domain_metadata(options.domain_metadata)
    mineru_parse_options = options.mineru_parse_options or _compile_mineru_parse_options(
        domain_metadata
    )
    return options.model_copy(
        update={
            "domain_metadata": domain_metadata,
            "mineru_parse_options": mineru_parse_options,
        },
        deep=True,
    )
```

Add helper:

```python
def _compile_mineru_parse_options(metadata: DomainMetadata) -> MinerUParseOptionsIn | None:
    custom_json = metadata.custom_json if isinstance(metadata.custom_json, dict) else {}
    reference_family = _reference_family(metadata, custom_json)
    values = {
        metadata.domain,
        metadata.language,
        metadata.script,
        metadata.reference_pattern,
        *metadata.tags,
    }
    normalized = {str(value).casefold() for value in values if value}
    if reference_family == "chapter_verse" and (
        "arabic" in normalized or "quran" in normalized or "surah:verse" in normalized
    ):
        return MinerUParseOptionsIn(
            parse_method="ocr",
            lang="arabic",
            formula=False,
            table=False,
        )
    return None
```

Import `MinerUParseOptionsIn` from `ragstudio.schemas.parsing`.

- [ ] **Step 4: Persist parser/layout contract**

In `backend/src/ragstudio/services/document_contract.py`, add:

```python
parser_hints = (
    options.mineru_parse_options.model_dump(mode="json", exclude_none=True)
    if options.mineru_parse_options is not None
    else {}
)
```

Add to the returned contract:

```python
"parser_contract": {
    "mineru_parse_options": parser_hints,
    "required_text_validation_stage": "post_recovery_quality_gate",
},
"layout_context": {
    "vision_recovery_enabled": vision_policy.get("enabled") is True,
    "preserve_original_blocks": bool(
        _dict_value(custom_json.get("provenance")).get("preserve_original_blocks")
    ),
    "expected_tables": parser_hints.get("table"),
    "expected_equations": parser_hints.get("formula"),
    "image_blocks_are_recovery_candidates": vision_policy.get("enabled") is True,
},
```

- [ ] **Step 5: Run contract tests**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_domain_metadata_contract_compiler.py backend/tests/test_document_contract.py -q
```

Expected: PASS.

## Task 2: Move Required-Script Blocking After Recovery

**Files:**
- Modify: `backend/src/ragstudio/services/mineru_extraction_validator.py`
- Modify: `backend/src/ragstudio/services/document_parser_service.py`
- Test: `backend/tests/test_mineru_extraction_validator.py`
- Test: `backend/tests/test_document_parser_service.py`

- [ ] **Step 1: Rewrite validator test for missing Arabic**

Replace `test_rejects_missing_arabic_when_expected` in `backend/tests/test_mineru_extraction_validator.py` with:

```python
def test_reports_missing_arabic_without_blocking_before_recovery():
    chunks = [_chunk("This is extracted English text.")]

    report = MinerUExtractionValidator(min_text_chars=8).validate(
        chunks,
        expected_language="arabic",
    )

    assert report.chunk_count == 1
    assert report.arabic_character_count == 0
```

- [ ] **Step 2: Implement validator change**

In `backend/src/ragstudio/services/mineru_extraction_validator.py`, delete the block:

```python
if expected_language.lower() == "arabic" and arabic_character_count == 0:
    raise MinerUExtractionContractError(
        "arabic_text_missing",
        "Expected Arabic text, but MinerU extraction contained none.",
    )
```

Leave `expected_language` in the signature for compatibility and keep computing `arabic_character_count`.

- [ ] **Step 3: Add parser-service regression**

Add this test to `backend/tests/test_document_parser_service.py`:

```python
@pytest.mark.asyncio
async def test_mineru_parse_allows_missing_arabic_for_downstream_recovery(tmp_path):
    session = EventSession()

    class EnglishOnlyMinerUClient(EventMinerUClient):
        def normalize_artifact_zip(self, **kwargs):
            self.events.append("normalize")
            return [
                AdapterChunk(
                    text="[2:28]\nHow can you disbelieve in Allah?",
                    source_location={"page": 1},
                    metadata={"parser_metadata": {"backend": "mineru"}},
                )
            ]

    def mineru_client_factory(base_url, timeout_ms, poll_interval_ms):
        return EnglishOnlyMinerUClient(
            base_url,
            timeout_ms,
            poll_interval_ms,
            events=session.events,
        )

    document = SimpleNamespace(
        id="doc-1",
        artifact_path=str(tmp_path / "document.pdf"),
        content_type="application/pdf",
        sha256="sha",
    )

    chunks = await DocumentParserService(
        session,
        tmp_path,
        mineru_client_factory=mineru_client_factory,
        extraction_validator=MinerUExtractionValidator(min_text_chars=8),
    ).mineru_parse(
        document,
        IndexDocumentIn(
            parser_mode="mineru_strict",
            domain_metadata=DomainMetadata(domain="quran", script="arabic"),
        ),
    )

    assert [chunk.text for chunk in chunks] == ["[2:28]\nHow can you disbelieve in Allah?"]
```

- [ ] **Step 4: Run parser validation tests**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_mineru_extraction_validator.py backend/tests/test_document_parser_service.py -q
```

Expected: PASS.

## Task 3: Verify Existing Recovery And Quality Gates Still Own The Final Decision

**Files:**
- Test: `backend/tests/test_parser_normalization.py`
- Test: `backend/tests/test_chunk_splitter.py`
- Test: `backend/tests/test_domain_metadata_quality_gate.py`
- Test: `backend/tests/test_index_lifecycle_service.py`

- [ ] **Step 1: Run recovery/gate regression suite**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_parser_normalization.py backend/tests/test_chunk_splitter.py backend/tests/test_domain_metadata_quality_gate.py backend/tests/test_index_lifecycle_service.py -q
```

Expected: PASS. Existing tests should continue proving that image blocks can recover PDF text-layer content and required-script gates still run after chunk normalization.

- [ ] **Step 2: Run focused end-to-end ingestion/retrieval tests**

Run:

```bash
docker compose run --rm backend python -m pytest backend/tests/test_document_contract.py backend/tests/test_document_parser_service.py backend/tests/test_mineru_extraction_validator.py backend/tests/test_domain_metadata_contract_compiler.py backend/tests/test_domain_layout_retrieval_flow.py -q
```

Expected: PASS.

## Self-Review

- Spec coverage: The plan covers parser contract compilation, persisted document contract visibility, early validator gate order, and downstream recovery ownership.
- Placeholder scan: No placeholder steps remain.
- Type consistency: Uses existing `IndexDocumentIn`, `DomainMetadata`, `MinerUParseOptionsIn`, `DocumentParserService`, and `MinerUExtractionValidator` names.
