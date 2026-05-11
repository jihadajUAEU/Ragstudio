# MinerU Postgres Arabic Search Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Ragstudio's production document workflow MinerU-only, Postgres-only, and Arabic-searchable so words such as `وحنانا` retrieve validated Quran evidence instead of returning zero results.

**Architecture:** Product indexing must fail closed unless MinerU returns validated extracted text. Postgres stores canonical chunks plus Arabic-normalized search material, while PGVector and Neo4j remain the semantic and graph stores. SQLite and local parser fallback are removed from the product architecture; any remaining local fallback behavior must be isolated to explicit test fixtures or legacy migration code.

**Tech Stack:** FastAPI backend, SQLAlchemy async, Postgres with JSONB/GIN/pg_trgm/PGVector, MinerU sidecar API, Neo4j, pytest/pytest-asyncio, React/Vite.

---

## File Structure

- Modify `backend/src/ragstudio/services/runtime_policy.py`
  - Product policy: only `postgres_pgvector_neo4j` storage and `mineru_strict` parser are valid defaults.
  - Legacy fallback values are no longer accepted by normalizers.
- Modify `backend/src/ragstudio/schemas/parsing.py`
  - Public parser mode becomes `Literal["mineru_strict"]`.
- Modify `backend/src/ragstudio/schemas/runtime.py`
  - Public storage backend becomes `Literal["postgres_pgvector_neo4j"]`.
- Modify `backend/src/ragstudio/services/document_parser_service.py`
  - Remove production fallback parsing path from `parse()`.
  - Keep the existing local parser only where tests construct it directly.
- Create `backend/src/ragstudio/services/mineru_extraction_validator.py`
  - Validates MinerU output before chunk splitting or persistence.
  - Rejects raw PDF syntax, empty text, insufficient page coverage, missing Arabic text when Arabic is expected, and wrong parser backend.
- Create `backend/src/ragstudio/services/arabic_text.py`
  - Owns Arabic normalization, tokenization, and query variants.
- Modify `backend/src/ragstudio/db/models.py`
  - Add Postgres search columns to `Chunk`: `text_search_ar`, `tokens_ar`, `extraction_quality`.
  - Remove SQLite-specific product indexes.
  - Add Postgres indexes for Arabic lexical search.
- Modify `backend/src/ragstudio/services/chunk_service.py`
  - Validate MinerU output.
  - Persist Arabic search material.
  - Run index quality gate before marking indexing successful.
- Create `backend/src/ragstudio/services/index_quality_gate.py`
  - Probes persisted chunks for searchability and rejects failed indexes.
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
  contract -->|"pass"| normalize["Arabic normalization"]
  normalize --> chunks["Postgres chunks"]
  chunks --> indexes["GIN + trigram + PGVector + Neo4j"]
  indexes --> gate["Index quality gate"]
  gate -->|"fail"| fail
  gate -->|"pass"| ready["Document ready"]
  ready --> query["Query understanding"]
  query --> lexical["Arabic lexical retrieval"]
  query --> vector["PGVector semantic retrieval"]
  lexical --> fusion["Candidate fusion"]
  vector --> fusion
  fusion --> answer["Grounded answer orchestrator"]
```

## Task 1: Runtime Policy Removes Product Fallbacks

**Files:**
- Modify: `backend/src/ragstudio/services/runtime_policy.py`
- Modify: `backend/src/ragstudio/schemas/parsing.py`
- Modify: `backend/src/ragstudio/schemas/runtime.py`
- Test: `backend/tests/test_runtime_policy.py`

- [ ] **Step 1: Write failing runtime policy tests**

Create `backend/tests/test_runtime_policy.py`:

```python
import pytest

from ragstudio.services.runtime_policy import (
    DEFAULT_PARSER_MODE,
    DEFAULT_RUNTIME_MODE,
    DEFAULT_STORAGE_BACKEND,
    normalize_parser_mode,
    normalize_runtime_mode,
    normalize_storage_backend,
)


def test_product_defaults_are_postgres_mineru_runtime():
    assert DEFAULT_RUNTIME_MODE == "runtime"
    assert DEFAULT_STORAGE_BACKEND == "postgres_pgvector_neo4j"
    assert DEFAULT_PARSER_MODE == "mineru_strict"


def test_storage_policy_rejects_fallback_local():
    with pytest.raises(ValueError, match="fallback_local is not a product storage backend"):
        normalize_storage_backend("fallback_local")


def test_runtime_policy_rejects_fallback_mode():
    with pytest.raises(ValueError, match="fallback runtime mode is not supported"):
        normalize_runtime_mode("fallback", "postgres_pgvector_neo4j")


def test_parser_policy_rejects_non_mineru_modes():
    with pytest.raises(ValueError, match="local_fallback is not a product parser mode"):
        normalize_parser_mode("local_fallback")
    with pytest.raises(ValueError, match="mineru_with_fallback is not a product parser mode"):
        normalize_parser_mode("mineru_with_fallback")


def test_unknown_values_fall_back_to_product_defaults():
    assert normalize_storage_backend("unknown") == "postgres_pgvector_neo4j"
    assert normalize_runtime_mode("unknown", "postgres_pgvector_neo4j") == "runtime"
    assert normalize_parser_mode("unknown") == "mineru_strict"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest backend/tests/test_runtime_policy.py -v
```

Expected: FAIL because fallback values are still accepted.

- [ ] **Step 3: Update product runtime policy**

Replace `backend/src/ragstudio/services/runtime_policy.py` with:

```python
from typing import Literal, cast

RuntimeMode = Literal["runtime", "degraded"]
StorageBackend = Literal["postgres_pgvector_neo4j"]
ParserMode = Literal["mineru_strict"]
EmbeddingProvider = Literal["vllm_openai"]

DEFAULT_RUNTIME_MODE: RuntimeMode = "runtime"
DEFAULT_STORAGE_BACKEND: StorageBackend = "postgres_pgvector_neo4j"
DEFAULT_PARSER_MODE: ParserMode = "mineru_strict"
DEFAULT_EMBEDDING_PROVIDER: EmbeddingProvider = "vllm_openai"

VALID_RUNTIME_MODES = {"runtime", "degraded"}
VALID_STORAGE_BACKENDS = {"postgres_pgvector_neo4j"}
VALID_PARSER_MODES = {"mineru_strict"}
VALID_EMBEDDING_PROVIDERS = {"vllm_openai"}


def normalize_storage_backend(value: str | None) -> StorageBackend:
    if value == "fallback_local":
        raise ValueError("fallback_local is not a product storage backend")
    if value in VALID_STORAGE_BACKENDS:
        return cast(StorageBackend, value)
    return DEFAULT_STORAGE_BACKEND


def normalize_runtime_mode(
    value: str | None,
    storage_backend: str | None,
) -> RuntimeMode:
    normalize_storage_backend(storage_backend)
    if value == "fallback":
        raise ValueError("fallback runtime mode is not supported")
    if value in VALID_RUNTIME_MODES:
        return cast(RuntimeMode, value)
    return DEFAULT_RUNTIME_MODE


def normalize_parser_mode(value: str | None) -> ParserMode:
    if value == "local_fallback":
        raise ValueError("local_fallback is not a product parser mode")
    if value == "mineru_with_fallback":
        raise ValueError("mineru_with_fallback is not a product parser mode")
    if value in VALID_PARSER_MODES:
        return cast(ParserMode, value)
    return DEFAULT_PARSER_MODE


def normalize_embedding_provider(value: str | None) -> EmbeddingProvider:
    if value in VALID_EMBEDDING_PROVIDERS:
        return cast(EmbeddingProvider, value)
    return DEFAULT_EMBEDDING_PROVIDER
```

Update `backend/src/ragstudio/schemas/parsing.py`:

```python
ParserMode = Literal["mineru_strict"]
```

Update `backend/src/ragstudio/schemas/runtime.py`:

```python
RuntimeMode = Literal["runtime", "degraded"]
RuntimeOverallStatus = Literal["ready", "degraded", "failed"]
StorageBackend = Literal["postgres_pgvector_neo4j"]
```

- [ ] **Step 4: Run runtime policy tests**

Run:

```bash
uv run pytest backend/tests/test_runtime_policy.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/runtime_policy.py backend/src/ragstudio/schemas/parsing.py backend/src/ragstudio/schemas/runtime.py backend/tests/test_runtime_policy.py
git commit -m "feat: enforce postgres mineru runtime policy"
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
- Modify: `backend/src/ragstudio/services/chunk_service.py`
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

Remove product reliance on SQLite-specific indexes. The active-job uniqueness index in `Job.__table_args__` should keep only `postgresql_where`.

- [ ] **Step 4: Materialize Arabic fields on chunk writes**

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

For existing chunks loaded directly in tests, update `_chunk_out_with_score()` to surface generated search material when columns are empty:

```python
if not output.metadata.get("text_search_ar"):
    metadata["text_search_ar"] = normalize_arabic_text(output.text)
if not output.metadata.get("tokens_ar"):
    metadata["tokens_ar"] = arabic_tokens(output.text)
```

- [ ] **Step 5: Run Arabic chunk search test**

Run:

```bash
uv run pytest backend/tests/test_chunk_service_arabic_search.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/db/models.py backend/src/ragstudio/services/chunk_service.py backend/tests/test_chunk_service_arabic_search.py
git commit -m "feat: materialize arabic search fields in postgres chunks"
```

## Task 6: Arabic Lexical Search Scoring

**Files:**
- Modify: `backend/src/ragstudio/services/hybrid_chunk_search.py`
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

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest backend/tests/test_hybrid_chunk_search_arabic.py -v
```

Expected: FAIL because Arabic normalized exact scoring is not implemented.

- [ ] **Step 3: Add Arabic scoring**

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

- [ ] **Step 4: Run Arabic search tests**

Run:

```bash
uv run pytest backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_chunk_service_arabic_search.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/services/hybrid_chunk_search.py backend/tests/test_hybrid_chunk_search_arabic.py backend/tests/test_chunk_service_arabic_search.py
git commit -m "feat: score arabic normalized lexical matches"
```

## Task 7: Index Quality Gate

**Files:**
- Create: `backend/src/ragstudio/services/index_quality_gate.py`
- Modify: `backend/src/ragstudio/services/chunk_service.py`
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

- [ ] **Step 5: Run quality gate tests**

Run:

```bash
uv run pytest backend/tests/test_index_quality_gate.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ragstudio/services/index_quality_gate.py backend/src/ragstudio/services/chunk_service.py backend/tests/test_index_quality_gate.py
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

## Task 9: Postgres-Only Verification Gate

**Files:**
- Modify: `backend/tests/test_db_engine.py`
- Modify: `backend/tests/test_mineru_reindex_jobs.py`
- Test: existing backend suites

- [ ] **Step 1: Add failing tests that reject SQLite product URLs**

In `backend/tests/test_db_engine.py`, add:

```python
import pytest

from ragstudio.config import AppSettings


def test_product_settings_reject_sqlite_database_url():
    with pytest.raises(ValueError, match="SQLite is not supported for product runtime"):
        AppSettings(database_url="sqlite+aiosqlite:////tmp/ragstudio.sqlite3")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest backend/tests/test_db_engine.py::test_product_settings_reject_sqlite_database_url -v
```

Expected: FAIL if `AppSettings` still accepts SQLite as product runtime database.

- [ ] **Step 3: Enforce Postgres database URL in settings**

In `backend/src/ragstudio/config.py`, add a model validator:

```python
from pydantic import model_validator


@model_validator(mode="after")
def require_postgres_database(self):
    if self.database_url.startswith("sqlite"):
        raise ValueError("SQLite is not supported for product runtime")
    return self
```

If tests need SQLite for isolated unit speed, create a separate `TestAppSettings` fixture in tests rather than allowing SQLite through product `AppSettings`.

- [ ] **Step 4: Run Postgres policy tests**

Run:

```bash
uv run pytest backend/tests/test_runtime_policy.py backend/tests/test_db_engine.py::test_product_settings_reject_sqlite_database_url -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ragstudio/config.py backend/tests/test_db_engine.py
git commit -m "feat: reject sqlite product runtime configuration"
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

## Task 11: Browser Smoke Test

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
  - Postgres-only storage: Tasks 1, 5, 8, 9, and 11.
  - Arabic normalization: Tasks 4-6.
  - Search quality gate for `وحنانا`: Tasks 7, 10, and 11.
  - UI/docs removal of fallback choices: Task 8.
- Marker scan:
  - No unresolved task markers or cross-task shorthand remain.
- Type consistency:
  - `ParserMode` is `Literal["mineru_strict"]`.
  - `StorageBackend` is `Literal["postgres_pgvector_neo4j"]`.
  - `normalize_arabic_text()`, `arabic_tokens()`, and `arabic_query_variants()` are used by chunk persistence and search scoring.
  - `MinerUExtractionValidator.validate()` returns `MinerUExtractionReport`.
  - `IndexQualityGate.validate_adapter_chunks()` returns a dict report or raises `IndexQualityGateError`.

