# MinerU Postgres Arabic Search Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Ragstudio's production document workflow MinerU-only, Postgres-only, and Arabic-searchable so words such as `وحنانا` retrieve validated Quran evidence instead of returning zero results.

**Architecture:** Product indexing must fail closed unless MinerU returns validated extracted text. Postgres stores canonical chunks plus Arabic-normalized search material, while PGVector and Neo4j remain the semantic and graph stores. SQLite and local parser fallback are not product dependencies and must not be used by runtime indexing, query execution, upload, reindex, settings, or UI flows. Temporary compatibility code may exist only for one-way migration cleanup and isolated tests, with explicit removal tasks.

**Tech Stack:** FastAPI backend, SQLAlchemy async, Postgres with JSONB/GIN/pg_trgm/PGVector, MinerU sidecar API, Neo4j, pytest/pytest-asyncio, React/Vite.

---

## File Structure

- Modify `backend/src/ragstudio/services/runtime_policy.py`
  - Product policy: only `postgres_pgvector_neo4j` storage and `mineru_strict` parser are valid for user-triggered indexing and query execution.
  - Legacy fallback values are rejected at product boundaries and are not normalized into product settings.
- Modify `backend/src/ragstudio/schemas/parsing.py`
  - Keep the broad parser literal temporarily for backwards-compatible request validation, but add product validators that reject non-`mineru_strict` modes on upload/reindex routes.
- Modify `backend/src/ragstudio/schemas/runtime.py`
  - Remove product use of `fallback_local` and `fallback`; keep any legacy value handling inside migration-only code until cleanup is complete.
- Modify `backend/src/ragstudio/services/document_parser_service.py`
  - Remove production fallback parsing path from `parse()`.
  - Keep the existing local parser only where tests construct it directly.
- Create `backend/src/ragstudio/services/mineru_extraction_validator.py`
  - Validates MinerU output before chunk splitting or persistence.
  - Rejects raw PDF syntax, empty text, insufficient page coverage, missing Arabic text when Arabic is expected, and wrong parser backend.
- Create `backend/src/ragstudio/services/arabic_text.py`
  - Owns Arabic normalization, tokenization, and query variants.
- Create `backend/src/ragstudio/services/document_chunking_policy.py`
  - Owns MinerU-aware chunk boundaries, Quran/reference-aware split rules, overlap limits, and metadata preservation.
- Modify `backend/src/ragstudio/db/models.py`
  - Add Postgres search columns to `Chunk`: `text_search_ar`, `tokens_ar`, `extraction_quality`.
  - Add Postgres-only indexes through SQLAlchemy with guarded dialect support.
  - Add Postgres indexes for Arabic lexical search.
- Modify `backend/src/ragstudio/db/engine.py`
  - Create `pg_trgm` and `vector` extensions during Postgres initialization.
  - Backfill new chunk search columns and stop normalizing settings profiles to fallback runtime values.
- Modify `backend/src/ragstudio/services/chunk_service.py`
  - Validate MinerU output.
  - Persist Arabic search material.
  - Run index quality gate before marking indexing successful.
- Modify `backend/src/ragstudio/services/index_lifecycle_service.py`
  - Apply the same MinerU validation, Arabic materialization, and quality gate to runtime-backed indexing.
- Create `backend/src/ragstudio/services/chunk_lexical_search_repository.py`
  - Uses Postgres filters for Arabic token and normalized text retrieval before Python scoring.
- Create `backend/src/ragstudio/services/vector_index_policy.py`
  - Validates embedding dimensions, PGVector extension/index readiness, and profile compatibility before semantic search runs.
- Create `backend/src/ragstudio/services/retrieval_fusion.py`
  - Combines Arabic lexical, reference metadata, PGVector semantic, reranker, and graph candidates with deterministic priority and Reciprocal Rank Fusion.
- Create `backend/src/ragstudio/services/context_assembly_service.py`
  - Builds answer context from fused candidates with direct evidence first, dedupe, source diversity, and token-budget enforcement.
- Create `backend/src/ragstudio/services/retrieval_observability.py`
  - Emits per-stage retrieval traces for candidate counts, latency, cache decisions, gates, and final evidence ordering.
- Modify `backend/src/ragstudio/services/retrieval_orchestrator.py`
  - Treats Arabic single-token queries as exact lexical lookup before semantic retrieval.
  - Adds fusion/eval traces for candidate source, rank, direct-match features, and final ordering.
- Create `backend/src/ragstudio/services/index_quality_gate.py`
  - Probes persisted chunks for searchability and rejects failed indexes.
- Create `backend/tests/test_rag_retrieval_fusion.py`
  - Gates exact Arabic/reference candidates outranking broad semantic candidates.
- Create `backend/tests/test_rag_evaluation_gates.py`
  - Gates Precision@K, MRR, Recall@K, faithfulness, and latency traces for Quran cases.
- Modify `backend/src/ragstudio/services/hybrid_chunk_search.py`
  - Score Arabic normalized exact token and phrase matches.
- Modify `frontend/src/api/generated.ts`, `frontend/src/features/settings/settings-page.tsx`, and `frontend/src/features/documents/documents-page.tsx`
  - Remove product choices for local fallback, MinerU with fallback, and fallback local storage.
- Modify `docs/workflows.md` and `docs/user-guide.md`
  - Document MinerU-only and Postgres-only architecture.

## Target Architecture

```mermaid
flowchart TD
  upload["Upload PDF"] --> settings["Runtime profile: Postgres + MinerU strict"]
  settings --> mineru["MinerU parse job"]
  mineru --> contract["Extraction contract validator"]
  contract -->|"fail"| fail["Index failed with quality report"]
  contract -->|"pass"| chunking["Document-aware chunking policy"]
  chunking --> normalize["Arabic normalization"]
  normalize --> chunks["Postgres chunks"]
  chunks --> indexes["GIN + trigram + PGVector + Neo4j"]
  indexes --> vectorGate["Embedding dimension + PGVector index gate"]
  vectorGate --> gate["Index quality gate"]
  gate -->|"fail"| fail
  gate -->|"pass"| ready["Document ready"]
  ready --> query["Query understanding"]
  query --> lexical["Arabic lexical retrieval"]
  query --> vector["PGVector semantic retrieval"]
  vector --> vectorReady["Vector compatibility gate"]
  lexical --> fusion["Candidate fusion"]
  vectorReady --> fusion
  fusion --> context["Context assembly"]
  context --> answer["Grounded answer orchestrator"]
```

## Tuned Architecture Corrections

The first architecture direction was right, but the implementation plan needed tighter boundaries. These corrections are mandatory:

1. **Remove product fallback while preserving one-way migration safety.**
   Existing rows, tests, generated frontend types, and migration helpers still mention `fallback`, `fallback_local`, `local_fallback`, and `mineru_with_fallback`. Runtime behavior must reject these immediately at product entry points. Any remaining references must be limited to migration cleanup or isolated tests and removed in the final cleanup task.

2. **Enforce product policy at boundaries, not only in helpers.**
   The real gates are upload, reindex, runtime profile save, index lifecycle, and query readiness. `normalize_*()` helpers should not be the only line of defense.

3. **Index lifecycle is the primary production path.**
   The previous draft focused too much on `ChunkService.index_document()`. Production runtime indexing also writes chunks in `IndexLifecycleService.reindex_document()`, so Arabic fields and quality reports must be materialized there too.

4. **Postgres indexes must be used by search.**
   Adding columns and indexes is not enough if `ChunkService.search()` still loads every chunk and scores in Python. Add a small repository that runs a bounded Postgres lexical prefilter for Arabic exact/token queries, then apply existing scoring and fusion.

5. **SQLite removal means no runtime dependency.**
   `make_engine()` already rejects non-Postgres metadata URLs. The tuned plan removes SQLite from app/runtime docs, settings, upload, query, and index paths. Tests should use Postgres fixtures for storage behavior; fake repositories are acceptable only for unit tests that do not exercise database runtime behavior.

6. **MinerU validation has two gates.**
   Extraction contract validation runs immediately after MinerU artifact normalization. Index quality validation runs after splitting/relationship annotation, before persistence and before the document becomes ready.

7. **Arabic search must preserve original text.**
   Normalized fields are search aids only. Citations and UI must show original MinerU text, including diacritics, page/source metadata, and reference metadata.

8. **RAG retrieval needs deterministic fusion and eval gates.**
   Exact Arabic and reference evidence must outrank broad semantic candidates. The pipeline needs explicit fusion rules, Precision@K/MRR/Recall@K checks, faithfulness gates, and latency traces before browser smoke tests.

9. **Chunking is part of retrieval quality, not parser plumbing.**
   MinerU extraction can be valid while retrieval still fails because the target word or verse is split away from its reference metadata. Product chunking must be page/reference-aware, preserve MinerU block metadata, avoid splitting inside detected Quran verse spans, and keep a bounded neighbor window for answer context.

10. **PGVector must be compatible before it is trusted.**
    Semantic retrieval should fail with a clear readiness error when the active embedding provider dimension differs from the stored vector dimension or when the PGVector index is absent/unusable. Prefer HNSW for production Postgres builds; allow IVFFlat only as an explicit compatibility path when HNSW is unavailable.

11. **Context assembly must be deterministic and source-preserving.**
    The answer orchestrator should not receive an arbitrary concat of chunks. It needs a context builder that deduplicates candidates, pins exact reference/Arabic matches first, keeps original text for citation, adds limited neighbor context, and records which evidence was included or dropped due to token budget.

12. **Caching must never hide exact-match failures.**
    Cache normalized Arabic text, tokens, embedding vectors, and query-plan traces where useful. Do not serve semantic answer cache hits for exact Arabic tokens or Quran reference queries unless the cache key includes document set, index version, retrieval profile, and direct evidence ids.

## Revised Implementation Order

Build this in safer order than the first draft:

1. Add Arabic normalization and tests.
2. Add MinerU extraction and index quality validators.
3. Add document-aware chunking policy before chunk persistence.
4. Materialize Arabic search fields in both `ChunkService` and `IndexLifecycleService`.
5. Add PGVector index and embedding dimension readiness gates.
6. Add Postgres lexical prefilter and hybrid scoring.
7. Add deterministic retrieval fusion and RAG eval gates.
8. Add context assembly, observability, and cache policy gates.
9. Add product policy gates for upload/reindex/settings.
10. Remove fallback options from UI/docs.
11. Add Quran end-to-end gates.
12. Remove remaining legacy fallback/SQLite compatibility code after migration tests pass.

## Task 1: Product Policy Gates For Runtime And Parser

**Files:**
- Modify: `backend/src/ragstudio/services/runtime_policy.py`
- Modify: `backend/src/ragstudio/routes/documents.py`
- Modify: `backend/src/ragstudio/routes/settings.py`
- Test: `backend/tests/test_runtime_policy.py`
- Test: `backend/tests/test_documents.py`
- Test: `backend/tests/test_settings.py`

- [ ] **Step 1: Write failing product policy tests**

Create or extend `backend/tests/test_runtime_policy.py`:

```python
import pytest

from ragstudio.services.runtime_policy import (
    DEFAULT_PARSER_MODE,
    DEFAULT_RUNTIME_MODE,
    DEFAULT_STORAGE_BACKEND,
    ProductPolicyError,
    enforce_product_index_options,
    enforce_product_runtime_settings,
    normalize_parser_mode,
    normalize_runtime_mode,
    normalize_storage_backend,
)


def test_product_defaults_are_postgres_mineru_runtime():
    assert DEFAULT_RUNTIME_MODE == "runtime"
    assert DEFAULT_STORAGE_BACKEND == "postgres_pgvector_neo4j"
    assert DEFAULT_PARSER_MODE == "mineru_strict"


def test_legacy_normalizers_still_read_old_values_during_migration():
    assert normalize_storage_backend("fallback_local") == "fallback_local"
    assert normalize_runtime_mode("fallback", "fallback_local") == "fallback"
    assert normalize_parser_mode("local_fallback") == "local_fallback"


def test_product_runtime_settings_reject_fallback_storage_and_runtime():
    with pytest.raises(ProductPolicyError, match="fallback_local"):
        enforce_product_runtime_settings(
            storage_backend="fallback_local",
            runtime_mode="fallback",
        )


def test_product_runtime_settings_accept_postgres_runtime():
    enforce_product_runtime_settings(
        storage_backend="postgres_pgvector_neo4j",
        runtime_mode="runtime",
    )


def test_product_index_options_reject_non_mineru_strict():
    with pytest.raises(ProductPolicyError, match="mineru_strict"):
        enforce_product_index_options(parser_mode="local_fallback")
    with pytest.raises(ProductPolicyError, match="mineru_strict"):
        enforce_product_index_options(parser_mode="mineru_with_fallback")


def test_product_index_options_accept_mineru_strict():
    enforce_product_index_options(parser_mode="mineru_strict")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest backend/tests/test_runtime_policy.py -v
```

Expected: FAIL because `ProductPolicyError`, `enforce_product_runtime_settings()`, and `enforce_product_index_options()` do not exist yet.

- [ ] **Step 3: Add explicit product policy gates**

Modify `backend/src/ragstudio/services/runtime_policy.py` without removing legacy literals yet:

```python
from typing import Literal, cast

RuntimeMode = Literal["runtime", "fallback", "degraded"]
StorageBackend = Literal["postgres_pgvector_neo4j", "fallback_local"]
ParserMode = Literal["local_fallback", "mineru_strict", "mineru_with_fallback"]
EmbeddingProvider = Literal["fallback", "vllm_openai"]

DEFAULT_RUNTIME_MODE: RuntimeMode = "runtime"
DEFAULT_STORAGE_BACKEND: StorageBackend = "postgres_pgvector_neo4j"
DEFAULT_PARSER_MODE: ParserMode = "mineru_strict"
DEFAULT_EMBEDDING_PROVIDER: EmbeddingProvider = "vllm_openai"

VALID_RUNTIME_MODES = {"runtime", "fallback", "degraded"}
VALID_STORAGE_BACKENDS = {"postgres_pgvector_neo4j", "fallback_local"}
VALID_PARSER_MODES = {"local_fallback", "mineru_strict", "mineru_with_fallback"}
VALID_EMBEDDING_PROVIDERS = {"fallback", "vllm_openai"}


class ProductPolicyError(ValueError):
    pass


def normalize_storage_backend(value: str | None) -> StorageBackend:
    if value in VALID_STORAGE_BACKENDS:
        return cast(StorageBackend, value)
    return DEFAULT_STORAGE_BACKEND


def normalize_runtime_mode(
    value: str | None,
    storage_backend: str | None,
) -> RuntimeMode:
    if normalize_storage_backend(storage_backend) == "fallback_local":
        return "fallback"
    if value in VALID_RUNTIME_MODES:
        return cast(RuntimeMode, value)
    return DEFAULT_RUNTIME_MODE


def normalize_parser_mode(value: str | None) -> ParserMode:
    if value in VALID_PARSER_MODES:
        return cast(ParserMode, value)
    return DEFAULT_PARSER_MODE


def normalize_embedding_provider(value: str | None) -> EmbeddingProvider:
    if value in VALID_EMBEDDING_PROVIDERS:
        return cast(EmbeddingProvider, value)
    return DEFAULT_EMBEDDING_PROVIDER


def enforce_product_runtime_settings(*, storage_backend: str, runtime_mode: str) -> None:
    if storage_backend != DEFAULT_STORAGE_BACKEND:
        raise ProductPolicyError(
            "fallback_local is not allowed in product settings. "
            "Use postgres_pgvector_neo4j."
        )
    if runtime_mode not in {"runtime", "degraded"}:
        raise ProductPolicyError(
            "fallback runtime mode is not allowed in product settings. "
            "Use runtime with Postgres/PGVector/Neo4j."
        )


def enforce_product_index_options(*, parser_mode: str) -> None:
    if parser_mode != DEFAULT_PARSER_MODE:
        raise ProductPolicyError(
            "Production indexing requires parser_mode=mineru_strict. "
            f"Received {parser_mode!r}."
        )
```

- [ ] **Step 4: Gate upload and reindex routes**

In `backend/src/ragstudio/routes/documents.py`, import:

```python
from ragstudio.services.runtime_policy import ProductPolicyError, enforce_product_index_options
```

After parsing upload/reindex `IndexDocumentIn`, call:

```python
try:
    enforce_product_index_options(parser_mode=options.parser_mode)
except ProductPolicyError as exc:
    raise HTTPException(status_code=422, detail=str(exc)) from exc
```

Add route tests in `backend/tests/test_documents.py`:

```python
async def test_upload_rejects_local_fallback_parser_mode(client):
    response = await client.post(
        "/api/documents",
        files={"file": ("sample.pdf", b"%PDF-1.4", "application/pdf")},
        data={"parser_mode": "local_fallback", "domain_metadata": "{}"},
    )

    assert response.status_code == 422
    assert "mineru_strict" in response.json()["detail"]


async def test_reindex_rejects_mineru_with_fallback(client, seeded_document):
    response = await client.post(
        f"/api/documents/{seeded_document.id}/index",
        json={"parser_mode": "mineru_with_fallback", "domain_metadata": {}},
    )

    assert response.status_code == 422
    assert "mineru_strict" in response.json()["detail"]
```

- [ ] **Step 5: Gate settings writes**

In `backend/src/ragstudio/routes/settings.py`, import:

```python
from ragstudio.services.runtime_policy import ProductPolicyError, enforce_product_runtime_settings
```

Before saving settings, call:

```python
try:
    enforce_product_runtime_settings(
        storage_backend=payload.storage_backend,
        runtime_mode=payload.runtime_mode,
    )
except ProductPolicyError as exc:
    raise HTTPException(status_code=422, detail=str(exc)) from exc
```

Add tests in `backend/tests/test_settings.py`:

```python
async def test_settings_reject_fallback_local_storage(client, settings_payload):
    payload = {**settings_payload, "storage_backend": "fallback_local", "runtime_mode": "fallback"}

    response = await client.put("/api/settings/default", json=payload)

    assert response.status_code == 422
    assert "postgres_pgvector_neo4j" in response.json()["detail"]
```

- [ ] **Step 6: Run product policy tests**

Run:

```bash
uv run pytest backend/tests/test_runtime_policy.py backend/tests/test_documents.py::test_upload_rejects_local_fallback_parser_mode backend/tests/test_documents.py::test_reindex_rejects_mineru_with_fallback backend/tests/test_settings.py::test_settings_reject_fallback_local_storage -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ragstudio/services/runtime_policy.py backend/src/ragstudio/routes/documents.py backend/src/ragstudio/routes/settings.py backend/tests/test_runtime_policy.py backend/tests/test_documents.py backend/tests/test_settings.py
git commit -m "feat: enforce product runtime policy gates"
```

## Task 2: MinerU-Only Parser Contract

**Files:**
- Modify: `backend/src/ragstudio/services/document_parser_service.py`
- Test: `backend/tests/test_document_parser_service.py`

- [ ] **Step 1: Write failing parser contract tests**

Create `backend/tests/test_document_parser_service.py`:

```python
import pytest

from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.document_parser_service import DocumentParserService


class FakeDocument:
    id = "doc-1"
    artifact_path = "/tmp/doc.pdf"
    content_type = "application/pdf"
    sha256 = "abc123"


class FailingMinerUClient:
    pass


class LocalParserShouldNotRun:
    async def index_document(self, artifact_path):
        raise AssertionError("local parser must not run in product indexing")


@pytest.mark.asyncio
async def test_parse_requires_mineru_strict():
    service = DocumentParserService(
        session=None,
        data_dir=None,
        local_parser=LocalParserShouldNotRun(),
        mineru_client_factory=FailingMinerUClient,
    )

    options = IndexDocumentIn(parser_mode="mineru_strict")

    with pytest.raises(RuntimeError, match="MinerU base URL is not configured"):
        await service.parse(FakeDocument(), options)


@pytest.mark.asyncio
async def test_local_parse_entrypoint_is_not_used_by_parse(monkeypatch):
    service = DocumentParserService(
        session=None,
        data_dir=None,
        local_parser=LocalParserShouldNotRun(),
        mineru_client_factory=FailingMinerUClient,
    )

    async def explode_local_parse(document):
        raise AssertionError("parse must not call local_parse")

    monkeypatch.setattr(service, "local_parse", explode_local_parse)

    with pytest.raises(RuntimeError, match="MinerU base URL is not configured"):
        await service.parse(FakeDocument(), IndexDocumentIn(parser_mode="mineru_strict"))
```

- [ ] **Step 2: Run tests to verify current fallback seams fail the new contract**

Run:

```bash
uv run pytest backend/tests/test_document_parser_service.py -v
```

Expected: FAIL until `DocumentParserService.parse()` only allows MinerU strict.

- [ ] **Step 3: Remove production fallback from parse path**

Change `DocumentParserService.parse()` in `backend/src/ragstudio/services/document_parser_service.py` to:

```python
async def parse(
    self,
    document: Document,
    options: IndexDocumentIn,
    *,
    on_mineru_status: MinerUStatusCallback | None = None,
) -> list[AdapterChunk]:
    if options.parser_mode != "mineru_strict":
        raise RuntimeError(f"Unsupported parser mode for production indexing: {options.parser_mode}")
    return await self.mineru_parse(
        document,
        options,
        on_mineru_status=on_mineru_status,
    )
```

Keep `local_parse()` only for isolated tests that call it directly. Delete `local_parse_with_mineru_failure()` after all references are removed.

- [ ] **Step 4: Run parser contract tests**

Run:

```bash
uv run pytest backend/tests/test_document_parser_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/document_parser_service.py backend/tests/test_document_parser_service.py
git commit -m "feat: require mineru strict parsing"
```

## Task 3: MinerU Extraction Contract Validator

**Files:**
- Create: `backend/src/ragstudio/services/mineru_extraction_validator.py`
- Modify: `backend/src/ragstudio/services/document_parser_service.py`
- Test: `backend/tests/test_mineru_extraction_validator.py`

- [ ] **Step 1: Write failing extraction validator tests**

Create `backend/tests/test_mineru_extraction_validator.py`:

```python
import pytest

from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.mineru_extraction_validator import (
    MinerUExtractionContractError,
    MinerUExtractionValidator,
)


def _chunk(text, metadata=None, source_location=None):
    return AdapterChunk(
        text=text,
        source_location=source_location or {"page": 1},
        metadata=metadata or {"parser_metadata": {"backend": "mineru", "parser_mode": "mineru_strict"}},
    )


def test_rejects_raw_pdf_syntax():
    chunks = [_chunk("%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj")]

    with pytest.raises(MinerUExtractionContractError, match="raw_pdf_syntax"):
        MinerUExtractionValidator().validate(chunks, expected_language="arabic")


def test_rejects_empty_extraction():
    with pytest.raises(MinerUExtractionContractError, match="empty_extraction"):
        MinerUExtractionValidator().validate([], expected_language="arabic")


def test_rejects_missing_arabic_when_arabic_expected():
    chunks = [_chunk("This is English text only with no Arabic script.")]

    with pytest.raises(MinerUExtractionContractError, match="arabic_text_missing"):
        MinerUExtractionValidator().validate(chunks, expected_language="arabic")


def test_rejects_non_mineru_backend():
    chunks = [_chunk("وحنانا من لدنا", {"parser_metadata": {"backend": "fallback"}})]

    with pytest.raises(MinerUExtractionContractError, match="non_mineru_backend"):
        MinerUExtractionValidator().validate(chunks, expected_language="arabic")


def test_accepts_valid_mineru_arabic_text():
    chunks = [_chunk("وَحَنَانًا مِّن لَّدُنَّا وَزَكَاةً وَكَانَ تَقِيًّا")]

    report = MinerUExtractionValidator().validate(chunks, expected_language="arabic")

    assert report.status == "passed"
    assert report.chunk_count == 1
    assert report.arabic_character_count > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest backend/tests/test_mineru_extraction_validator.py -v
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement extraction contract validator**

Create `backend/src/ragstudio/services/mineru_extraction_validator.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ragstudio.services.adapter import AdapterChunk


class MinerUExtractionContractError(RuntimeError):
    def __init__(self, reason: str, detail: str):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}")


@dataclass(frozen=True)
class MinerUExtractionReport:
    status: str
    chunk_count: int
    character_count: int
    arabic_character_count: int
    page_count: int

    def model_dump(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "chunk_count": self.chunk_count,
            "character_count": self.character_count,
            "arabic_character_count": self.arabic_character_count,
            "page_count": self.page_count,
        }


class MinerUExtractionValidator:
    raw_pdf_pattern = re.compile(r"(%PDF-\d|\\b\\d+\\s+\\d+\\s+obj\\b|\\bxref\\b|\\bendobj\\b)")
    arabic_pattern = re.compile(r"[\u0600-\u06FF]")

    def validate(
        self,
        chunks: list[AdapterChunk],
        *,
        expected_language: str = "unknown",
    ) -> MinerUExtractionReport:
        if not chunks:
            raise MinerUExtractionContractError("empty_extraction", "MinerU returned no text chunks.")

        text = "\n".join(chunk.text for chunk in chunks).strip()
        if len(text) < 40:
            raise MinerUExtractionContractError("text_too_short", "MinerU text is too short to index.")
        if self.raw_pdf_pattern.search(text):
            raise MinerUExtractionContractError("raw_pdf_syntax", "Extraction contains PDF object syntax.")

        non_mineru = [
            chunk
            for chunk in chunks
            if (chunk.metadata.get("parser_metadata") or {}).get("backend") != "mineru"
        ]
        if non_mineru:
            raise MinerUExtractionContractError(
                "non_mineru_backend",
                "All production chunks must come from MinerU.",
            )

        arabic_count = len(self.arabic_pattern.findall(text))
        if expected_language in {"arabic", "quran"} and arabic_count == 0:
            raise MinerUExtractionContractError(
                "arabic_text_missing",
                "Arabic text was expected but none was extracted.",
            )

        pages = {
            int(chunk.source_location["page"])
            for chunk in chunks
            if isinstance(chunk.source_location.get("page"), int)
        }
        return MinerUExtractionReport(
            status="passed",
            chunk_count=len(chunks),
            character_count=len(text),
            arabic_character_count=arabic_count,
            page_count=len(pages),
        )
```

- [ ] **Step 4: Wire validator after MinerU parse**

In `backend/src/ragstudio/services/document_parser_service.py`, import:

```python
from ragstudio.services.mineru_extraction_validator import MinerUExtractionValidator
```

Add constructor field:

```python
extraction_validator: MinerUExtractionValidator | None = None,
```

Set:

```python
self.extraction_validator = extraction_validator or MinerUExtractionValidator()
```

In `mineru_parse()`, replace the final return with:

```python
chunks = client.normalize_artifact_zip(
    artifact_zip=job_result.artifact_zip,
    extract_dir=artifact_dir / "extracted",
    document_id=document.id,
    parser_mode=options.parser_mode,
    parse_job_id=job_result.parse_job_id,
)
report = self.extraction_validator.validate(
    chunks,
    expected_language=options.domain_metadata.language,
)
return [
    AdapterChunk(
        text=chunk.text,
        source_location=chunk.source_location,
        metadata={**chunk.metadata, "extraction_quality": report.model_dump()},
        runtime_source_id=chunk.runtime_source_id,
        content_type=chunk.content_type,
        preview_ref=chunk.preview_ref,
    )
    for chunk in chunks
]
```

- [ ] **Step 5: Run extraction validator tests**

Run:

```bash
uv run pytest backend/tests/test_mineru_extraction_validator.py backend/tests/test_document_parser_service.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/mineru_extraction_validator.py backend/src/ragstudio/services/document_parser_service.py backend/tests/test_mineru_extraction_validator.py backend/tests/test_document_parser_service.py
git commit -m "feat: validate mineru extraction contract"
```

## Task 4: Arabic Normalization Service

**Files:**
- Create: `backend/src/ragstudio/services/arabic_text.py`
- Test: `backend/tests/test_arabic_text.py`

- [ ] **Step 1: Write failing Arabic normalization tests**

Create `backend/tests/test_arabic_text.py`:

```python
from ragstudio.services.arabic_text import (
    arabic_query_variants,
    arabic_tokens,
    normalize_arabic_text,
)


def test_normalize_removes_diacritics_and_tatweel():
    assert normalize_arabic_text("وَحَنَانًا مِّن لَّدُنَّا") == "وحنانا من لدنا"


def test_normalize_unifies_alef_and_ya_variants():
    assert normalize_arabic_text("إِنَّ ٱلْهُدَىٰ") == "ان الهدي"


def test_tokens_include_prefix_stripped_waw_variant():
    tokens = arabic_tokens("وَحَنَانًا مِّن لَّدُنَّا")

    assert "وحنانا" in tokens
    assert "حنانا" in tokens
    assert "لدنا" in tokens


def test_query_variants_include_original_normalized_and_prefix_stripped():
    assert arabic_query_variants("وحنانا") == ["وحنانا", "حنانا"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest backend/tests/test_arabic_text.py -v
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement Arabic text utilities**

Create `backend/src/ragstudio/services/arabic_text.py`:

```python
from __future__ import annotations

import re

ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
ARABIC_TOKEN = re.compile(r"[\u0600-\u06FF]+")
ALEF_TRANSLATION = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي"})


def normalize_arabic_text(value: str) -> str:
    normalized = value.translate(ALEF_TRANSLATION)
    normalized = normalized.replace("ـ", "")
    normalized = ARABIC_DIACRITICS.sub("", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def arabic_tokens(value: str) -> list[str]:
    normalized = normalize_arabic_text(value)
    tokens: list[str] = []
    for match in ARABIC_TOKEN.finditer(normalized):
        token = match.group(0)
        if token not in tokens:
            tokens.append(token)
        if token.startswith("و") and len(token) > 2 and token[1:] not in tokens:
            tokens.append(token[1:])
    return tokens


def arabic_query_variants(query: str) -> list[str]:
    normalized = normalize_arabic_text(query)
    variants = [normalized] if normalized else []
    if normalized.startswith("و") and len(normalized) > 2:
        variants.append(normalized[1:])
    return list(dict.fromkeys(variants))
```

- [ ] **Step 4: Run Arabic normalization tests**

Run:

```bash
uv run pytest backend/tests/test_arabic_text.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/arabic_text.py backend/tests/test_arabic_text.py
git commit -m "feat: add arabic text normalization"
```

## Task 5: Postgres Chunk Search Materialization

**Files:**
- Modify: `backend/src/ragstudio/db/models.py`
- Modify: `backend/src/ragstudio/db/engine.py`
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Modify: `backend/src/ragstudio/services/index_lifecycle_service.py`
- Test: `backend/tests/test_chunk_service_arabic_search.py`

- [ ] **Step 1: Write failing chunk persistence test**

Create `backend/tests/test_chunk_service_arabic_search.py`:

```python
import pytest
from ragstudio.db.models import Chunk, Document
from ragstudio.schemas.chunks import ChunkSearchIn
from ragstudio.services.chunk_service import ChunkService


@pytest.mark.asyncio
async def test_chunk_persistence_materializes_arabic_search_fields(session, tmp_path):
    document = Document(
        id="doc-quran",
        filename="quran.pdf",
        content_type="application/pdf",
        sha256="sha",
        artifact_path=str(tmp_path / "quran.pdf"),
        status="ready",
    )
    session.add(document)
    session.add(
        Chunk(
            id="chunk-19-13",
            document_id="doc-quran",
            text="وَحَنَانًا مِّن لَّدُنَّا وَزَكَاةً وَكَانَ تَقِيًّا",
            source_location={"page": 312},
            metadata_json={"parser_metadata": {"backend": "mineru", "parser_mode": "mineru_strict"}},
        )
    )
    await session.commit()

    result = await ChunkService(session, tmp_path).search(
        ChunkSearchIn(query="وحنانا", document_ids=["doc-quran"], limit=5)
    )

    assert result.total == 1
    assert result.items[0].id == "chunk-19-13"
```

- [ ] **Step 2: Run test to verify current search misses normalized Arabic**

Run:

```bash
uv run pytest backend/tests/test_chunk_service_arabic_search.py -v
```

Expected: FAIL until Arabic materialization and scoring exist.

- [ ] **Step 3: Add Postgres search fields to `Chunk`**

In `backend/src/ragstudio/db/models.py`, add imports:

```python
from sqlalchemy.dialects.postgresql import ARRAY
```

Add fields to `Chunk`:

```python
text_search_ar: Mapped[str] = mapped_column(Text, default="")
tokens_ar: Mapped[list[str]] = mapped_column(
    MutableList.as_mutable(JSON().with_variant(ARRAY(String), "postgresql")),
    default=list,
)
extraction_quality: Mapped[dict[str, Any]] = mapped_column(JsonDictType, default=dict)
```

Add indexes to `Chunk.__table_args__`:

```python
__table_args__ = (
    Index("ix_chunks_document_id", "document_id"),
    Index("ix_chunks_text_search_ar_trgm", "text_search_ar", postgresql_using="gin", postgresql_ops={"text_search_ar": "gin_trgm_ops"}),
    Index("ix_chunks_tokens_ar_gin", "tokens_ar", postgresql_using="gin"),
)
```

Keep SQLite-specific test compatibility out of new product indexes. The active-job uniqueness index may keep `sqlite_where` only if existing isolated tests still rely on SQLite fixtures, but product verification must exercise the `postgresql_where` path.

- [ ] **Step 4: Add extension and column backfills**

In `backend/src/ragstudio/db/engine.py`, update `init_db()`:

```python
if connection.dialect.name == "postgresql":
    await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    await connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
```

In `_ensure_runtime_columns()`, add chunk columns:

```python
"text_search_ar": "TEXT DEFAULT '' NOT NULL",
"tokens_ar": _json_array_column(connection),
"extraction_quality": _json_object_column(connection),
```

After adding columns, backfill existing rows:

```python
if "chunks" in table_names:
    _backfill_chunk_search_columns(connection)
```

Add:

```python
def _backfill_chunk_search_columns(connection) -> None:
    connection.execute(
        text(
            """
            UPDATE chunks
            SET text_search_ar = COALESCE(text_search_ar, ''),
                tokens_ar = COALESCE(tokens_ar, CAST('[]' AS JSONB)),
                extraction_quality = COALESCE(extraction_quality, CAST('{}' AS JSONB))
            WHERE text_search_ar IS NULL
               OR tokens_ar IS NULL
               OR extraction_quality IS NULL
            """
        )
    )
```

- [ ] **Step 5: Materialize Arabic fields on chunk writes**

In `backend/src/ragstudio/services/chunk_service.py`, import:

```python
from ragstudio.services.arabic_text import arabic_tokens, normalize_arabic_text
```

When constructing each `Chunk`, add:

```python
text_search_ar=normalize_arabic_text(adapter_chunk.text),
tokens_ar=arabic_tokens(adapter_chunk.text),
extraction_quality=adapter_chunk.metadata.get("extraction_quality", {}),
```

Apply the same fields in `backend/src/ragstudio/services/index_lifecycle_service.py` when constructing `Chunk` from runtime-normalized chunks:

```python
text_search_ar=normalize_arabic_text(adapter_chunk.text),
tokens_ar=arabic_tokens(adapter_chunk.text),
extraction_quality=adapter_chunk.metadata.get("extraction_quality", {}),
```

For existing chunks loaded directly in tests, update `_chunk_out_with_score()` to surface generated search material when columns are empty:

```python
if not output.metadata.get("text_search_ar"):
    metadata["text_search_ar"] = normalize_arabic_text(output.text)
if not output.metadata.get("tokens_ar"):
    metadata["tokens_ar"] = arabic_tokens(output.text)
```

- [ ] **Step 6: Run Arabic chunk search test**

Run:

```bash
uv run pytest backend/tests/test_chunk_service_arabic_search.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ragstudio/db/models.py backend/src/ragstudio/db/engine.py backend/src/ragstudio/services/chunk_service.py backend/src/ragstudio/services/index_lifecycle_service.py backend/tests/test_chunk_service_arabic_search.py
git commit -m "feat: materialize arabic search fields in postgres chunks"
```

## Task 5A: Document-Aware Chunking Policy

**Files:**
- Create: `backend/src/ragstudio/services/document_chunking_policy.py`
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Modify: `backend/src/ragstudio/services/index_lifecycle_service.py`
- Test: `backend/tests/test_document_chunking_policy.py`

- [ ] **Step 1: Write failing chunk boundary tests**

Create tests that prove:
- A Quran verse span such as `19:13` is not split across two persisted chunks when MinerU text and metadata expose the verse/reference boundary.
- Original MinerU text, page, block id, reference metadata, and preview refs survive chunk normalization.
- Neighbor context is bounded to zero or one adjacent verse/block on each side and never causes unrelated pages to be pulled into the answer context.
- Very large MinerU blocks are split by sentence/verse-aware boundaries first, then by hard token/character limits only when no safer boundary exists.

Run:

```bash
uv run pytest backend/tests/test_document_chunking_policy.py -v
```

Expected: FAIL until the policy exists.

- [ ] **Step 2: Implement the chunking policy**

Create `DocumentChunkingPolicy` with:
- `split_mineru_chunks(chunks, domain_metadata) -> list[AdapterChunk]`
- Reference-aware split points from `reference_metadata.references`.
- Arabic-aware text limits based on normalized and original text lengths.
- Metadata merge rules that keep MinerU provenance and source locations.
- A hard cap that prevents one chunk from dominating context assembly.

Do not place Quran-specific constants deep inside generic split code. Use a small policy table keyed by `domain_metadata.domain` or explicit detected reference metadata.

- [ ] **Step 3: Wire the policy before persistence**

Use `DocumentChunkingPolicy` after MinerU extraction validation and before Arabic materialization in both:
- `ChunkService`
- `IndexLifecycleService`

The order must be:

```text
MinerU output -> extraction validator -> chunking policy -> Arabic materialization -> persistence -> index quality gate
```

- [ ] **Step 4: Run chunking and Arabic persistence tests**

Run:

```bash
uv run pytest backend/tests/test_document_chunking_policy.py backend/tests/test_chunk_service_arabic_search.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/document_chunking_policy.py backend/src/ragstudio/services/chunk_service.py backend/src/ragstudio/services/index_lifecycle_service.py backend/tests/test_document_chunking_policy.py
git commit -m "feat: add document aware chunking policy"
```

## Task 5B: PGVector Index And Embedding Dimension Gate

**Files:**
- Create: `backend/src/ragstudio/services/vector_index_policy.py`
- Modify: `backend/src/ragstudio/db/engine.py`
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Test: `backend/tests/test_vector_index_policy.py`

- [ ] **Step 1: Write failing vector readiness tests**

Create tests that prove:
- Stored vector dimension must match the active embedding profile dimension.
- Query embeddings must be generated with the same dimension used at indexing time.
- Missing `vector` extension or missing PGVector index produces a readiness error before retrieval returns low-quality semantic results.
- HNSW is preferred when the local Postgres/PGVector version supports it; IVFFlat is allowed only as an explicit compatibility result in the readiness report.

Run:

```bash
uv run pytest backend/tests/test_vector_index_policy.py -v
```

Expected: FAIL until the policy exists.

- [ ] **Step 2: Implement vector index policy**

Create `VectorIndexPolicy` with:
- `validate_embedding_profile(document_id, active_profile)`.
- `validate_pgvector_ready(connection)`.
- `assert_query_dimension(query_vector, expected_dimension)`.
- Readiness report fields: `expected_dimension`, `observed_dimension`, `index_type`, `extension_available`, `profile_id`, and `status`.

The policy must hard-fail exact document-scoped queries when vector compatibility is broken. It may allow lexical-only Arabic search to continue, but the response trace must say semantic retrieval was skipped due to vector readiness.

- [ ] **Step 3: Add database index initialization**

In `backend/src/ragstudio/db/engine.py`, create the PGVector extension and the production vector index during Postgres initialization/backfill:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw
ON chunks USING hnsw (embedding vector_cosine_ops);
```

If HNSW is unsupported, emit a compatibility report and create the explicit IVFFlat fallback index only in that branch.

- [ ] **Step 4: Gate orchestrator semantic retrieval**

In `retrieval_orchestrator.py`, run `VectorIndexPolicy` before PGVector/native semantic retrieval. Add trace fields:
- `semantic_retrieval_status`
- `embedding_expected_dimension`
- `embedding_observed_dimension`
- `vector_index_type`
- `semantic_candidates`

- [ ] **Step 5: Run vector policy tests**

Run:

```bash
uv run pytest backend/tests/test_vector_index_policy.py backend/tests/test_rag_evaluation_gates.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/vector_index_policy.py backend/src/ragstudio/db/engine.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_vector_index_policy.py
git commit -m "feat: gate pgvector embedding compatibility"
```

## Task 6: Arabic Lexical Search Repository And Scoring

**Files:**
- Create: `backend/src/ragstudio/services/chunk_lexical_search_repository.py`
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Modify: `backend/src/ragstudio/services/hybrid_chunk_search.py`
- Test: `backend/tests/test_chunk_lexical_search_repository.py`
- Test: `backend/tests/test_hybrid_chunk_search_arabic.py`

- [ ] **Step 1: Write failing Arabic search scoring tests**

Create `backend/tests/test_hybrid_chunk_search_arabic.py`:

```python
from ragstudio.db.models import Chunk
from ragstudio.services.hybrid_chunk_search import HybridChunkSearch


def test_arabic_query_matches_diacritized_chunk_text():
    chunk = Chunk(
        id="chunk-1",
        document_id="doc-1",
        text="وَحَنَانًا مِّن لَّدُنَّا وَزَكَاةً",
        source_location={"page": 1},
        metadata_json={},
    )

    score = HybridChunkSearch().score("وحنانا", chunk)

    assert score.score > 0
    assert score.breakdown["arabic_exact"] >= 40.0


def test_arabic_query_matches_prefix_stripped_token():
    chunk = Chunk(
        id="chunk-1",
        document_id="doc-1",
        text="حَنَانًا مِّن لَّدُنَّا",
        source_location={"page": 1},
        metadata_json={},
    )

    score = HybridChunkSearch().score("وحنانا", chunk)

    assert score.score > 0
    assert score.breakdown["arabic_token"] >= 20.0
```

Create `backend/tests/test_chunk_lexical_search_repository.py`:

```python
import pytest

from ragstudio.db.models import Chunk, Document
from ragstudio.services.arabic_text import arabic_tokens, normalize_arabic_text
from ragstudio.services.chunk_lexical_search_repository import ChunkLexicalSearchRepository


@pytest.mark.asyncio
async def test_repository_prefilters_arabic_token_with_postgres_columns(session, tmp_path):
    document = Document(
        id="doc-quran",
        filename="quran.pdf",
        content_type="application/pdf",
        sha256="sha",
        artifact_path=str(tmp_path / "quran.pdf"),
        status="ready",
    )
    text = "وَحَنَانًا مِّن لَّدُنَّا وَزَكَاةً"
    session.add(document)
    session.add(
        Chunk(
            id="chunk-19-13",
            document_id="doc-quran",
            text=text,
            text_search_ar=normalize_arabic_text(text),
            tokens_ar=arabic_tokens(text),
            source_location={"page": 312},
            metadata_json={},
        )
    )
    await session.commit()

    chunks = await ChunkLexicalSearchRepository(session).arabic_prefilter(
        query="وحنانا",
        document_ids=["doc-quran"],
        limit=5,
    )

    assert [chunk.id for chunk in chunks] == ["chunk-19-13"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_chunk_lexical_search_repository.py -v
```

Expected: FAIL because Arabic normalized exact scoring and the Postgres lexical repository are not implemented.

- [ ] **Step 3: Add Postgres lexical repository**

Create `backend/src/ragstudio/services/chunk_lexical_search_repository.py`:

```python
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.db.models import Chunk
from ragstudio.services.arabic_text import arabic_query_variants


class ChunkLexicalSearchRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def arabic_prefilter(
        self,
        *,
        query: str,
        document_ids: list[str],
        limit: int,
    ) -> list[Chunk]:
        variants = arabic_query_variants(query)
        if not variants:
            return []

        statement = select(Chunk)
        if document_ids:
            statement = statement.where(Chunk.document_id.in_(document_ids))

        token_filters = [Chunk.tokens_ar.contains([variant]) for variant in variants]
        text_filters = [Chunk.text_search_ar.ilike(f"%{variant}%") for variant in variants]
        statement = statement.where(or_(*token_filters, *text_filters))
        statement = statement.order_by(Chunk.created_at.asc(), Chunk.id.asc()).limit(limit)

        result = await self.session.execute(statement)
        return list(result.scalars().all())
```

In `backend/src/ragstudio/services/chunk_service.py`, construct the repository and merge prefiltered chunks with the existing full ranking path:

```python
prefiltered = await ChunkLexicalSearchRepository(self.session).arabic_prefilter(
    query=search_in.query,
    document_ids=search_in.document_ids,
    limit=max(search_in.limit, 20),
)
prefiltered_ids = {chunk.id for chunk in prefiltered}
chunks = [*prefiltered, *[chunk for chunk in chunks if chunk.id not in prefiltered_ids]]
```

- [ ] **Step 4: Add Arabic scoring**

In `backend/src/ragstudio/services/hybrid_chunk_search.py`, import:

```python
from ragstudio.services.arabic_text import arabic_query_variants, arabic_tokens, normalize_arabic_text
```

Inside `score()`, after `chunk_text = chunk.text.lower()`, add:

```python
arabic_exact = self._arabic_exact_score(query, chunk)
arabic_token = self._arabic_token_score(query, chunk)
```

Add to `breakdown`:

```python
"arabic_exact": arabic_exact,
"arabic_token": arabic_token,
```

Add methods:

```python
def _arabic_exact_score(self, query: str, chunk: Chunk) -> float:
    variants = arabic_query_variants(query)
    if not variants:
        return 0.0
    searchable = str(getattr(chunk, "text_search_ar", "") or normalize_arabic_text(chunk.text))
    if any(variant and variant in searchable for variant in variants):
        return 40.0
    return 0.0


def _arabic_token_score(self, query: str, chunk: Chunk) -> float:
    variants = set(arabic_query_variants(query))
    if not variants:
        return 0.0
    stored_tokens = getattr(chunk, "tokens_ar", None)
    tokens = set(stored_tokens if isinstance(stored_tokens, list) else arabic_tokens(chunk.text))
    if variants & tokens:
        return 24.0
    return 0.0
```

- [ ] **Step 5: Run Arabic search tests**

Run:

```bash
uv run pytest backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_chunk_lexical_search_repository.py backend/tests/test_chunk_service_arabic_search.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/chunk_lexical_search_repository.py backend/src/ragstudio/services/chunk_service.py backend/src/ragstudio/services/hybrid_chunk_search.py backend/tests/test_chunk_lexical_search_repository.py backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_chunk_service_arabic_search.py
git commit -m "feat: score arabic normalized lexical matches"
```

## Task 6A: Hybrid Retrieval Fusion And RAG Evaluation Gates

**Files:**
- Create: `backend/src/ragstudio/services/retrieval_fusion.py`
- Modify: `backend/src/ragstudio/services/retrieval_evidence.py`
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Test: `backend/tests/test_rag_retrieval_fusion.py`
- Test: `backend/tests/test_rag_evaluation_gates.py`

- [ ] **Step 1: Write failing fusion priority tests**

Create `backend/tests/test_rag_retrieval_fusion.py`:

```python
from ragstudio.services.retrieval_evidence import EvidenceCandidate
from ragstudio.services.retrieval_fusion import RetrievalFusion


def _candidate(tool, chunk_id, text, score, features=None, references=None):
    return EvidenceCandidate(
        candidate_id=f"{tool}:{chunk_id}",
        text=text,
        document_id="doc-quran",
        chunk_id=chunk_id,
        source_location={"page": 1},
        metadata={"reference_metadata": {"references": references or []}},
        tool=tool,
        tool_rank=1,
        base_score=score,
        match_features=features or {},
    )


def test_exact_arabic_token_outranks_broad_semantic_match():
    semantic = _candidate(
        "pgvector",
        "semantic-1",
        "Allah guides people in many passages.",
        0.91,
    )
    lexical = _candidate(
        "arabic_lexical",
        "quran-19-13",
        "[19:13] وَحَنَانًا مِّن لَّدُنَّا وَزَكَاةً",
        0.5,
        features={"arabic_exact": True, "arabic_token": "وحنانا"},
        references=["19:13"],
    )

    fused = RetrievalFusion().fuse([[semantic], [lexical]], limit=5)

    assert fused[0].chunk_id == "quran-19-13"
    assert "direct_arabic_match" in fused[0].reasons


def test_exact_reference_outranks_exact_arabic_when_reference_requested():
    reference = _candidate(
        "reference_exact",
        "quran-24-35",
        "[24:35] Allah is the Light of the heavens and the earth.",
        0.4,
        features={"reference_exact": True},
        references=["24:35"],
    )
    lexical = _candidate(
        "arabic_lexical",
        "quran-19-13",
        "[19:13] وَحَنَانًا مِّن لَّدُنَّا",
        0.8,
        features={"arabic_exact": True},
        references=["19:13"],
    )

    fused = RetrievalFusion().fuse([[lexical], [reference]], limit=5)

    assert fused[0].chunk_id == "quran-24-35"
    assert "exact_reference_match" in fused[0].reasons
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest backend/tests/test_rag_retrieval_fusion.py -v
```

Expected: FAIL with missing `ragstudio.services.retrieval_fusion`.

- [ ] **Step 3: Implement deterministic fusion**

Create `backend/src/ragstudio/services/retrieval_fusion.py`:

```python
from __future__ import annotations

from dataclasses import replace

from ragstudio.services.retrieval_evidence import EvidenceCandidate


class RetrievalFusion:
    def fuse(
        self,
        ranked_lists: list[list[EvidenceCandidate]],
        *,
        limit: int,
    ) -> list[EvidenceCandidate]:
        by_key: dict[str, EvidenceCandidate] = {}
        scores: dict[str, float] = {}
        tools: dict[str, list[str]] = {}

        for ranked in ranked_lists:
            for rank, candidate in enumerate(ranked, start=1):
                key = _candidate_key(candidate)
                if key not in by_key or _direct_priority(candidate) > _direct_priority(by_key[key]):
                    by_key[key] = candidate
                scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank)
                tool_list = tools.setdefault(key, [])
                if candidate.tool not in tool_list:
                    tool_list.append(candidate.tool)

        fused: list[EvidenceCandidate] = []
        for key, candidate in by_key.items():
            direct_boost, reason = _direct_boost(candidate)
            metadata = {**candidate.metadata, "retrieval_passes": tools[key]}
            reasons = [*candidate.reasons]
            if reason:
                reasons.append(reason)
            fused.append(
                replace(
                    candidate,
                    metadata=metadata,
                    boost_score=candidate.boost_score + direct_boost,
                    final_score=scores[key] + direct_boost + candidate.base_score,
                    reasons=reasons,
                )
            )

        return sorted(
            fused,
            key=lambda candidate: (
                _direct_priority(candidate),
                candidate.final_score,
                -candidate.tool_rank,
            ),
            reverse=True,
        )[:limit]


def _candidate_key(candidate: EvidenceCandidate) -> str:
    if candidate.chunk_id:
        return f"chunk:{candidate.chunk_id}"
    return f"text:{candidate.document_id}:{candidate.text.strip().casefold()}"


def _direct_priority(candidate: EvidenceCandidate) -> int:
    if candidate.match_features.get("reference_exact"):
        return 100
    if candidate.match_features.get("arabic_exact"):
        return 90
    if candidate.match_features.get("target_phrase"):
        return 80
    if candidate.tool == "pgvector":
        return 20
    return 10


def _direct_boost(candidate: EvidenceCandidate) -> tuple[float, str | None]:
    if candidate.match_features.get("reference_exact"):
        return 100.0, "exact_reference_match"
    if candidate.match_features.get("arabic_exact"):
        return 90.0, "direct_arabic_match"
    if candidate.match_features.get("target_phrase"):
        return 80.0, "target_phrase_match"
    return 0.0, None
```

- [ ] **Step 4: Route orchestrator candidate lists through fusion**

In `backend/src/ragstudio/services/retrieval_orchestrator.py`, replace direct list concatenation for final candidate ordering with:

```python
fused = RetrievalFusion().fuse(
    [
        reference_candidates,
        arabic_lexical_candidates,
        metadata_candidates,
        native_candidates,
        graph_candidates,
    ],
    limit=plan.candidate_limit,
)
```

If a candidate list does not exist yet in the current implementation, use an empty list and add the trace field anyway:

```python
{
    "stage": "retrieval_fusion",
    "reference_candidates": len(reference_candidates),
    "arabic_lexical_candidates": len(arabic_lexical_candidates),
    "metadata_candidates": len(metadata_candidates),
    "native_candidates": len(native_candidates),
    "graph_candidates": len(graph_candidates),
    "fused_candidates": len(fused),
}
```

- [ ] **Step 5: Write RAG evaluation gate tests**

Create `backend/tests/test_rag_evaluation_gates.py`:

```python
from ragstudio.services.retrieval_evidence import EvidenceCandidate


def _source(reference, chunk_id, rank):
    return EvidenceCandidate(
        candidate_id=f"test:{chunk_id}",
        text=f"[{reference}] sample text",
        document_id="doc-quran",
        chunk_id=chunk_id,
        source_location={"page": rank},
        metadata={"reference_metadata": {"references": [reference]}},
        tool="test",
        tool_rank=rank,
        base_score=1.0,
        final_score=1.0,
    )


def precision_at_k(results, expected_reference, k):
    top = results[:k]
    return sum(_has_reference(item, expected_reference) for item in top) / max(len(top), 1)


def reciprocal_rank(results, expected_reference):
    for index, item in enumerate(results, start=1):
        if _has_reference(item, expected_reference):
            return 1 / index
    return 0.0


def _has_reference(candidate, expected_reference):
    refs = candidate.metadata.get("reference_metadata", {}).get("references", [])
    return expected_reference in refs


def test_quran_arabic_word_gate_metrics():
    results = [
        _source("19:13", "quran-19-13", 1),
        _source("19:12", "quran-19-12", 2),
    ]

    assert precision_at_k(results, "19:13", 5) >= 0.5
    assert reciprocal_rank(results, "19:13") == 1.0


def test_quran_light_reference_gate_metrics():
    results = [
        _source("24:35", "quran-24-35", 1),
        _source("24:36", "quran-24-36", 2),
    ]

    assert precision_at_k(results, "24:35", 5) >= 0.5
    assert reciprocal_rank(results, "24:35") == 1.0
```

- [ ] **Step 6: Add runtime eval expectations**

Add these expected gates to experiment/evaluation docs or fixtures:

```json
[
  {
    "query": "وحنانا",
    "expected_reference": "19:13",
    "required_top_k": 5,
    "preferred_top_1": true,
    "must_include_original_text": "وَحَنَانًا",
    "metrics": ["precision_at_5", "mrr"]
  },
  {
    "query": "Find the verse that says Allah is the Light of the heavens and the earth. Summarize the image used",
    "expected_reference": "24:35",
    "required_top_k": 5,
    "preferred_top_1": true,
    "must_not_answer": "not included in the provided evidence",
    "metrics": ["precision_at_5", "mrr", "faithfulness"]
  }
]
```

- [ ] **Step 7: Run fusion and eval tests**

Run:

```bash
uv run pytest backend/tests/test_rag_retrieval_fusion.py backend/tests/test_rag_evaluation_gates.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/src/ragstudio/services/retrieval_fusion.py backend/src/ragstudio/services/retrieval_evidence.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_rag_retrieval_fusion.py backend/tests/test_rag_evaluation_gates.py
git commit -m "feat: add rag retrieval fusion gates"
```

## Task 6B: Context Assembly, Observability, And Cache Policy

**Files:**
- Create: `backend/src/ragstudio/services/context_assembly_service.py`
- Create: `backend/src/ragstudio/services/retrieval_observability.py`
- Modify: `backend/src/ragstudio/services/retrieval_orchestrator.py`
- Test: `backend/tests/test_context_assembly_service.py`
- Test: `backend/tests/test_retrieval_observability.py`

- [ ] **Step 1: Write failing context assembly tests**

Create tests that prove:
- Exact reference candidates and exact Arabic lexical candidates are placed first in answer context.
- Duplicate chunks from lexical, vector, graph, and reranker passes are included once with merged reasons.
- Original text is preserved for citations; normalized Arabic is trace metadata only.
- Token budget drops lower-value semantic candidates before direct evidence.
- Neighbor context can be included when it shares the same document/reference family and stays inside the configured budget.
- If no direct evidence survives context assembly, the answer orchestrator must return a grounded "not enough evidence" response instead of guessing.

Run:

```bash
uv run pytest backend/tests/test_context_assembly_service.py -v
```

Expected: FAIL until the service exists.

- [ ] **Step 2: Implement context assembly**

Create `ContextAssemblyService` with:
- `assemble(candidates, query_plan, budget) -> AssembledContext`.
- Deterministic sorting from fused candidate order.
- Dedupe by `chunk_id`, then by normalized text hash.
- Evidence sections with `source_id`, `reference`, `document_id`, `page`, `original_text`, `included_reason`, and `retrieval_passes`.
- Drop report with `candidate_id`, `drop_reason`, and `estimated_tokens`.

The service must never compress or paraphrase direct evidence before the model sees it. Compression can only apply to lower-priority neighbor context.

- [ ] **Step 3: Add retrieval observability**

Create `RetrievalObservability` that records:
- Query classification: exact Arabic token, reference query, semantic question, mixed query.
- Per-stage latency: query planning, lexical retrieval, metadata/reference lookup, vector retrieval, graph retrieval, reranking, fusion, context assembly, generation.
- Candidate counts at each stage.
- Cache decisions and skipped cache reasons.
- Final evidence ids and answer grounding status.

Write the trace into the existing response trace/debug payload so UI tests can see why `وحنانا` matched or failed.

- [ ] **Step 4: Add cache policy gates**

Add explicit cache rules:
- Cache Arabic normalization and tokenization by raw text hash.
- Cache document embeddings by document id, chunk id, model id, dimension, and index version.
- Do not use answer-level semantic cache for exact Arabic token queries or exact Quran reference queries.
- Any retrieval cache key must include document ids, index version, runtime profile, parser mode, embedding model id, embedding dimension, and reranker state.

Add tests that exact Arabic and exact reference queries bypass answer cache while still using safe normalization/embedding caches.

- [ ] **Step 5: Run context and observability tests**

Run:

```bash
uv run pytest backend/tests/test_context_assembly_service.py backend/tests/test_retrieval_observability.py backend/tests/test_rag_evaluation_gates.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/context_assembly_service.py backend/src/ragstudio/services/retrieval_observability.py backend/src/ragstudio/services/retrieval_orchestrator.py backend/tests/test_context_assembly_service.py backend/tests/test_retrieval_observability.py backend/tests/test_rag_evaluation_gates.py
git commit -m "feat: add retrieval context assembly traces"
```

## Task 7: Index Quality Gate

**Files:**
- Create: `backend/src/ragstudio/services/index_quality_gate.py`
- Modify: `backend/src/ragstudio/services/chunk_service.py`
- Modify: `backend/src/ragstudio/services/index_lifecycle_service.py`
- Test: `backend/tests/test_index_quality_gate.py`

- [ ] **Step 1: Write failing quality gate tests**

Create `backend/tests/test_index_quality_gate.py`:

```python
import pytest

from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.index_quality_gate import IndexQualityGate, IndexQualityGateError


def _chunk(text):
    return AdapterChunk(
        text=text,
        source_location={"page": 1},
        metadata={
            "parser_metadata": {"backend": "mineru", "parser_mode": "mineru_strict"},
            "extraction_quality": {"status": "passed"},
        },
    )


def test_gate_rejects_raw_pdf_chunks():
    with pytest.raises(IndexQualityGateError, match="raw_pdf_persisted"):
        IndexQualityGate().validate_adapter_chunks([_chunk("%PDF-1.4\n1 0 obj")], language="arabic")


def test_gate_rejects_arabic_document_without_arabic_tokens():
    with pytest.raises(IndexQualityGateError, match="arabic_tokens_missing"):
        IndexQualityGate().validate_adapter_chunks([_chunk("English only text from a parser")], language="arabic")


def test_gate_accepts_arabic_mineru_chunks():
    report = IndexQualityGate().validate_adapter_chunks(
        [_chunk("وَحَنَانًا مِّن لَّدُنَّا وَزَكَاةً")],
        language="arabic",
    )

    assert report["status"] == "passed"
    assert report["arabic_token_count"] >= 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest backend/tests/test_index_quality_gate.py -v
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement quality gate**

Create `backend/src/ragstudio/services/index_quality_gate.py`:

```python
from __future__ import annotations

import re
from typing import Any

from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.arabic_text import arabic_tokens


class IndexQualityGateError(RuntimeError):
    def __init__(self, reason: str, detail: str):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}")


class IndexQualityGate:
    raw_pdf_pattern = re.compile(r"(%PDF-\d|\b\d+\s+\d+\s+obj\b|\bxref\b|\bendobj\b)")

    def validate_adapter_chunks(
        self,
        chunks: list[AdapterChunk],
        *,
        language: str = "unknown",
    ) -> dict[str, Any]:
        text = "\n".join(chunk.text for chunk in chunks)
        if self.raw_pdf_pattern.search(text):
            raise IndexQualityGateError("raw_pdf_persisted", "Raw PDF syntax reached chunk persistence.")

        tokens = arabic_tokens(text)
        if language in {"arabic", "quran"} and not tokens:
            raise IndexQualityGateError(
                "arabic_tokens_missing",
                "Arabic document has no normalized Arabic search tokens.",
            )

        return {
            "status": "passed",
            "chunk_count": len(chunks),
            "arabic_token_count": len(tokens),
        }
```

- [ ] **Step 4: Run quality gate before persistence**

In `backend/src/ragstudio/services/chunk_service.py`, import:

```python
from ragstudio.services.index_quality_gate import IndexQualityGate
```

Add constructor field:

```python
index_quality_gate: IndexQualityGate | None = None,
```

Set:

```python
self.index_quality_gate = index_quality_gate or IndexQualityGate()
```

In `index_document()`, after `adapter_chunks = self.relationship_builder.annotate(...)`, add:

```python
quality_report = self.index_quality_gate.validate_adapter_chunks(
    adapter_chunks,
    language=options.domain_metadata.language,
)
adapter_chunks = [
    AdapterChunk(
        text=adapter_chunk.text,
        source_location=adapter_chunk.source_location,
        metadata={**adapter_chunk.metadata, "index_quality": quality_report},
        runtime_source_id=adapter_chunk.runtime_source_id,
        content_type=adapter_chunk.content_type,
        preview_ref=adapter_chunk.preview_ref,
    )
    for adapter_chunk in adapter_chunks
]
```

Apply the same gate in `backend/src/ragstudio/services/index_lifecycle_service.py` after `ChunkSplitter().split(...)` and `MinerURelationshipBuilder().annotate(...)`, before deleting old chunks:

```python
quality_report = IndexQualityGate().validate_adapter_chunks(
    adapter_chunks,
    language=options.domain_metadata.language,
)
adapter_chunks = [
    AdapterChunk(
        text=adapter_chunk.text,
        source_location=adapter_chunk.source_location,
        metadata={**adapter_chunk.metadata, "index_quality": quality_report},
        runtime_source_id=adapter_chunk.runtime_source_id,
        content_type=adapter_chunk.content_type,
        preview_ref=adapter_chunk.preview_ref,
    )
    for adapter_chunk in adapter_chunks
]
```

- [ ] **Step 5: Run quality gate tests**

Run:

```bash
uv run pytest backend/tests/test_index_quality_gate.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/index_quality_gate.py backend/src/ragstudio/services/chunk_service.py backend/src/ragstudio/services/index_lifecycle_service.py backend/tests/test_index_quality_gate.py
git commit -m "feat: add index quality gate"
```

## Task 8: Remove Product Fallback Options From UI And Docs

**Files:**
- Modify: `frontend/src/api/generated.ts`
- Modify: `frontend/src/features/settings/settings-page.tsx`
- Modify: `frontend/src/features/documents/documents-page.tsx`
- Modify: `docs/workflows.md`
- Modify: `docs/user-guide.md`
- Test: `frontend/src/features/settings/settings-page.test.tsx`
- Test: `frontend/src/features/documents/documents-page.test.tsx`

- [ ] **Step 1: Write failing UI tests for removed fallback choices**

In `frontend/src/features/settings/settings-page.test.tsx`, add:

```tsx
it("does not offer fallback local storage", async () => {
  render(<SettingsPage />);

  expect(screen.queryByText("Fallback local")).not.toBeInTheDocument();
  expect(await screen.findByText("Postgres + PGVector + Neo4j")).toBeVisible();
});
```

In `frontend/src/features/documents/documents-page.test.tsx`, add:

```tsx
it("uses MinerU strict as the only parser mode", async () => {
  render(<DocumentsPage />);

  expect(screen.queryByText("Local fallback")).not.toBeInTheDocument();
  expect(screen.queryByText("MinerU with fallback")).not.toBeInTheDocument();
  expect(await screen.findByText("MinerU strict")).toBeVisible();
});
```

- [ ] **Step 2: Run UI tests to verify they fail**

Run:

```bash
npm --prefix frontend test -- settings-page documents-page
```

Expected: FAIL if fallback options are still rendered.

- [ ] **Step 3: Update generated API types**

In `frontend/src/api/generated.ts`, change:

```ts
export type StorageBackend = "postgres_pgvector_neo4j";
export type RuntimeMode = "runtime" | "degraded";
export type ParserMode = "mineru_strict";
```

- [ ] **Step 4: Remove fallback options from settings UI**

In `frontend/src/features/settings/settings-page.tsx`, remove the `Fallback local` option and default form state to:

```tsx
storage_backend: "postgres_pgvector_neo4j",
runtime_mode: "runtime",
```

The storage selector options should be:

```tsx
[
  { value: "postgres_pgvector_neo4j", label: "Postgres + PGVector + Neo4j" },
]
```

- [ ] **Step 5: Remove fallback parser options from documents UI**

In `frontend/src/features/documents/documents-page.tsx`, make parser options:

```tsx
const parserOptions: Array<{ value: ParserMode; label: string }> = [
  { value: "mineru_strict", label: "MinerU strict" },
];
```

Ensure upload and reindex requests always send:

```tsx
parser_mode: "mineru_strict",
```

- [ ] **Step 6: Update docs**

In `docs/workflows.md`, replace the MinerU parsing workflow introduction with:

```markdown
Ragstudio production indexing is MinerU-only. Upload and reindex jobs send documents to the configured MinerU sidecar and fail closed if MinerU is unavailable, returns invalid artifacts, or produces text that fails extraction quality checks. Local fallback parsing is not part of the production workflow.

Postgres is the source of truth for document metadata, chunks, lexical search material, and run records. PGVector stores semantic vectors in Postgres, and Neo4j stores graph state. SQLite is not part of the target architecture.
```

In `docs/user-guide.md`, replace the parser mode list with:

```markdown
Upload and Index actions use `MinerU strict`. The document is sent to MinerU and indexing fails if MinerU fails or returns invalid extracted text. Ragstudio does not silently fall back to local PDF parsing in the production workflow.
```

- [ ] **Step 7: Run UI and docs checks**

Run:

```bash
npm --prefix frontend test -- settings-page documents-page
rg -n "Local fallback|MinerU with fallback|fallback local|SQLite is not part" docs/workflows.md docs/user-guide.md
```

Expected:
- UI tests PASS.
- `rg` shows no product instructions recommending local fallback or MinerU with fallback.
- `rg` shows the new Postgres-only architecture sentence.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/generated.ts frontend/src/features/settings/settings-page.tsx frontend/src/features/documents/documents-page.tsx frontend/src/features/settings/settings-page.test.tsx frontend/src/features/documents/documents-page.test.tsx docs/workflows.md docs/user-guide.md
git commit -m "feat: remove product fallback options"
```

## Task 9: Postgres-Only Product Verification Gate

**Files:**
- Modify: `backend/src/ragstudio/db/engine.py`
- Modify: `backend/tests/test_db_engine.py`
- Modify: `backend/tests/test_mineru_reindex_jobs.py`
- Test: existing backend suites

- [ ] **Step 1: Add tests that product engines reject SQLite**

In `backend/tests/test_db_engine.py`, add:

```python
import pytest

from ragstudio.db.engine import make_engine


def test_product_engine_rejects_sqlite_database_url():
    with pytest.raises(ValueError, match="requires PostgreSQL"):
        make_engine("sqlite+aiosqlite:////tmp/ragstudio.sqlite3")
```

- [ ] **Step 2: Run test**

Run:

```bash
uv run pytest backend/tests/test_db_engine.py::test_product_engine_rejects_sqlite_database_url -v
```

Expected: PASS if the existing product engine guard is already active. If it fails, add the guard in `make_engine()` rather than blocking `AppSettings`, because tests and migration tooling may still construct settings objects without opening a product database connection.

- [ ] **Step 3: Stop fallback normalization in Postgres settings rows**

In `backend/src/ragstudio/db/engine.py`, update `_normalize_settings_profile_values()` so unknown or legacy values become product defaults, not fallback:

```python
UPDATE settings_profiles
SET storage_backend = 'postgres_pgvector_neo4j'
WHERE storage_backend IS NULL
   OR storage_backend = ''
   OR storage_backend NOT IN ('postgres_pgvector_neo4j')
```

```python
UPDATE settings_profiles
SET runtime_mode = 'runtime'
WHERE runtime_mode IS NULL
   OR runtime_mode = ''
   OR runtime_mode NOT IN ('runtime', 'degraded')
```

In `backend/tests/test_db_engine.py`, update `test_init_db_backfills_runtime_columns_for_existing_postgres_tables()` so the legacy row still inserts `storage_backend='local'`, but the assertions expect product defaults:

```python
assert settings_row["runtime_mode"] == "runtime"
assert settings_row["storage_backend"] == "postgres_pgvector_neo4j"
assert settings.storage_backend == "postgres_pgvector_neo4j"
assert settings.runtime_mode == "runtime"
assert runtime_profile.storage_backend == "postgres_pgvector_neo4j"
assert runtime_profile.runtime_mode == "runtime"
```

Remove the local fallback upload/query assertions from this test and replace them with a focused assertion that default settings normalize to production runtime values. Product upload/reindex behavior is covered by Task 1 route tests.

- [ ] **Step 4: Run Postgres policy tests**

Run:

```bash
uv run pytest backend/tests/test_runtime_policy.py backend/tests/test_db_engine.py::test_product_engine_rejects_sqlite_database_url backend/tests/test_db_engine.py::test_init_db_backfills_runtime_columns_for_existing_postgres_tables -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/db/engine.py backend/tests/test_db_engine.py
git commit -m "feat: verify postgres only product runtime"
```

## Task 10: End-To-End Quran Search Gate

**Files:**
- Create: `backend/tests/test_quran_arabic_search_gate.py`
- Test: backend integration

- [ ] **Step 1: Write failing Quran search gate**

Create `backend/tests/test_quran_arabic_search_gate.py`:

```python
import pytest

from ragstudio.db.models import Chunk, Document
from ragstudio.schemas.chunks import ChunkSearchIn
from ragstudio.services.arabic_text import arabic_tokens, normalize_arabic_text
from ragstudio.services.chunk_service import ChunkService


@pytest.mark.asyncio
async def test_quran_word_wahanan_is_searchable_after_mineru_index(session, tmp_path):
    document = Document(
        id="quran-doc",
        filename="quran_arabic_english.pdf",
        content_type="application/pdf",
        sha256="quran-sha",
        artifact_path=str(tmp_path / "quran_arabic_english.pdf"),
        status="succeeded",
    )
    session.add(document)
    text = "[19:13] وَحَنَانًا مِّن لَّدُنَّا وَزَكَاةً وَكَانَ تَقِيًّا"
    session.add(
        Chunk(
            id="quran-19-13",
            document_id="quran-doc",
            text=text,
            text_search_ar=normalize_arabic_text(text),
            tokens_ar=arabic_tokens(text),
            source_location={"page": 307},
            metadata_json={
                "parser_metadata": {"backend": "mineru", "parser_mode": "mineru_strict"},
                "reference_metadata": {"references": ["19:13"]},
            },
        )
    )
    await session.commit()

    result = await ChunkService(session, tmp_path).search(
        ChunkSearchIn(query="وحنانا", document_ids=["quran-doc"], limit=5)
    )

    assert result.total == 1
    assert result.items[0].id == "quran-19-13"
    assert result.items[0].metadata["reference_metadata"]["references"] == ["19:13"]
```

- [ ] **Step 2: Run Quran gate**

Run:

```bash
uv run pytest backend/tests/test_quran_arabic_search_gate.py -v
```

Expected: PASS after Tasks 4-6.

- [ ] **Step 3: Run targeted backend regression set**

Run:

```bash
uv run pytest \
  backend/tests/test_runtime_policy.py \
  backend/tests/test_document_parser_service.py \
  backend/tests/test_mineru_extraction_validator.py \
  backend/tests/test_arabic_text.py \
  backend/tests/test_chunk_service_arabic_search.py \
  backend/tests/test_hybrid_chunk_search_arabic.py \
  backend/tests/test_index_quality_gate.py \
  backend/tests/test_quran_arabic_search_gate.py \
  -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_quran_arabic_search_gate.py
git commit -m "test: gate quran arabic word search"
```

## Task 11: Remove Legacy SQLite And Fallback Compatibility

**Files:**
- Modify: `backend/src/ragstudio/services/runtime_policy.py`
- Modify: `backend/src/ragstudio/schemas/parsing.py`
- Modify: `backend/src/ragstudio/schemas/runtime.py`
- Modify: `backend/src/ragstudio/db/engine.py`
- Modify: `backend/tests/test_runtime_policy.py`
- Modify: `backend/tests/test_db_engine.py`
- Test: backend policy and database suites

- [ ] **Step 1: Add final cleanup tests**

Update `backend/tests/test_runtime_policy.py`:

```python
import pytest

from ragstudio.services.runtime_policy import (
    normalize_parser_mode,
    normalize_runtime_mode,
    normalize_storage_backend,
)


def test_legacy_fallback_values_are_no_longer_accepted_after_migration():
    with pytest.raises(ValueError, match="fallback_local"):
        normalize_storage_backend("fallback_local")
    with pytest.raises(ValueError, match="fallback"):
        normalize_runtime_mode("fallback", "postgres_pgvector_neo4j")
    with pytest.raises(ValueError, match="local_fallback"):
        normalize_parser_mode("local_fallback")
    with pytest.raises(ValueError, match="mineru_with_fallback"):
        normalize_parser_mode("mineru_with_fallback")
```

- [ ] **Step 2: Run cleanup test to verify it fails before type cleanup**

Run:

```bash
uv run pytest backend/tests/test_runtime_policy.py::test_legacy_fallback_values_are_no_longer_accepted_after_migration -v
```

Expected: FAIL while compatibility values are still accepted.

- [ ] **Step 3: Shrink runtime policy literals**

In `backend/src/ragstudio/services/runtime_policy.py`, set:

```python
RuntimeMode = Literal["runtime", "degraded"]
StorageBackend = Literal["postgres_pgvector_neo4j"]
ParserMode = Literal["mineru_strict"]
EmbeddingProvider = Literal["vllm_openai"]

VALID_RUNTIME_MODES = {"runtime", "degraded"}
VALID_STORAGE_BACKENDS = {"postgres_pgvector_neo4j"}
VALID_PARSER_MODES = {"mineru_strict"}
VALID_EMBEDDING_PROVIDERS = {"vllm_openai"}
```

Change normalizers to raise on removed fallback values:

```python
def normalize_storage_backend(value: str | None) -> StorageBackend:
    if value == "fallback_local":
        raise ValueError("fallback_local has been removed from product runtime")
    if value in VALID_STORAGE_BACKENDS:
        return cast(StorageBackend, value)
    return DEFAULT_STORAGE_BACKEND
```

Apply the same pattern for `fallback`, `local_fallback`, and `mineru_with_fallback`.

- [ ] **Step 4: Shrink public schemas**

In `backend/src/ragstudio/schemas/parsing.py`:

```python
ParserMode = Literal["mineru_strict"]
```

In `backend/src/ragstudio/schemas/runtime.py`:

```python
RuntimeMode = Literal["runtime", "degraded"]
RuntimeOverallStatus = Literal["ready", "degraded", "failed"]
StorageBackend = Literal["postgres_pgvector_neo4j"]
```

- [ ] **Step 5: Remove fallback normalization from database startup**

In `backend/src/ragstudio/db/engine.py`, remove SQL branches that set:

```text
storage_backend = 'fallback_local'
runtime_mode = 'fallback'
```

Keep only migration SQL that converts old values to product defaults:

```text
storage_backend = 'postgres_pgvector_neo4j'
runtime_mode = 'runtime'
```

- [ ] **Step 6: Run cleanup suites**

Run:

```bash
uv run pytest backend/tests/test_runtime_policy.py backend/tests/test_db_engine.py backend/tests/test_documents.py backend/tests/test_settings.py -v
```

Expected: PASS with no product fallback values accepted.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ragstudio/services/runtime_policy.py backend/src/ragstudio/schemas/parsing.py backend/src/ragstudio/schemas/runtime.py backend/src/ragstudio/db/engine.py backend/tests/test_runtime_policy.py backend/tests/test_db_engine.py backend/tests/test_documents.py backend/tests/test_settings.py
git commit -m "feat: remove legacy fallback runtime compatibility"
```

## Task 12: Browser Smoke Test

**Files:**
- No code changes expected.

- [ ] **Step 1: Start production-local services**

Run:

```bash
docker compose up -d postgres neo4j backend frontend
```

Expected: services start, and backend uses `RAGSTUDIO_DATABASE_URL=postgresql+asyncpg://ragstudio:ragstudio@postgres:5432/ragstudio`.

- [ ] **Step 2: Confirm no SQLite runtime**

Run:

```bash
docker compose exec backend python - <<'PY'
from ragstudio.config import AppSettings
settings = AppSettings()
print(settings.database_url)
assert settings.database_url.startswith("postgresql+asyncpg://")
PY
```

Expected: prints a Postgres URL and exits successfully.

- [ ] **Step 3: Upload and index Quran PDF with MinerU strict**

Use the UI at:

```text
http://localhost:53250/
```

Upload:

```text
/Users/meet/Downloads/quran_arabic_english.pdf
```

Expected:
- Parser mode is `MinerU strict`.
- Index job shows MinerU progress.
- Job fails if MinerU is unavailable.
- Job succeeds only when extraction quality and index quality reports pass.

- [ ] **Step 4: Search `وحنانا` from UI**

Open Chunks or Query and search:

```text
وحنانا
```

Expected:
- At least one result returns.
- Top result includes Quran reference `19:13`.
- The displayed text contains the original Arabic form, likely `وَحَنَانًا`.
- Trace or metadata includes normalized Arabic material such as `وحنانا` and token `حنانا`.

- [ ] **Step 5: Search English reference queries**

Run:

```text
Find the verse that says Allah is the Light of the heavens and the earth. Summarize the image used
Which verse asks for guidance to the straight path?
```

Expected:
- First query cites `24:35`.
- Second query cites the document reference for the straight path.
- Neither query reports that evidence is missing when the indexed chunk exists.

## Self-Review Checklist

- Spec coverage:
  - MinerU-only extraction: Tasks 1-3 and 8.
  - Postgres-only storage with no SQLite product dependency: Tasks 1, 5, 8, 9, 11, and 12.
  - Arabic normalization: Tasks 4-6.
  - Document-aware chunk boundaries and metadata preservation: Task 5A.
  - PGVector readiness and embedding dimension compatibility: Task 5B.
  - Hybrid retrieval fusion and RAG eval: Task 6A.
  - Context assembly, traceability, and cache policy: Task 6B.
  - Search quality gate for `وحنانا`: Tasks 6A, 7, 10, and 12.
  - UI/docs removal of fallback choices: Task 8.
  - Final fallback/SQLite cleanup: Task 9, Task 11, and Task 12 verification.
- Marker scan:
  - No unresolved task markers or cross-task shorthand remain.
- Type consistency:
  - Product route validators accept only `parser_mode="mineru_strict"`.
  - Product settings validators accept only `storage_backend="postgres_pgvector_neo4j"` and runtime/degraded runtime modes.
  - `normalize_arabic_text()`, `arabic_tokens()`, and `arabic_query_variants()` are used by chunk persistence and search scoring.
  - `RetrievalFusion.fuse()` receives ranked candidate lists and returns direct-evidence-first fused candidates.
  - `ContextAssemblyService.assemble()` receives fused candidates and returns source-preserving context plus a drop report.
  - `VectorIndexPolicy` verifies active embedding profile dimensions before semantic retrieval.
  - `MinerUExtractionValidator.validate()` returns `MinerUExtractionReport`.
  - `IndexQualityGate.validate_adapter_chunks()` returns a dict report or raises `IndexQualityGateError`.
