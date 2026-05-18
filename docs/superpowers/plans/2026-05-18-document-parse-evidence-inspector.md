# Document Parse Evidence Inspector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first document-parse Evidence Inspector slice: a backend evidence contract, a local API endpoint, sanitized proof export support, shared React inspector components, and a Local Studio route.

**Architecture:** Backend code derives a `DocumentParseEvidence` contract from persisted `Document`, `Job`, `Chunk`, and `GraphProjectionRecord` rows without re-parsing document text. Frontend code renders the contract through shared read-only components that work for local Studio and later public proof packets. Proof export redacts unsafe values and records redaction decisions explicitly.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async ORM, Pydantic, pytest; React, TypeScript, TanStack Query, Testing Library, Vitest, Tailwind CSS v4.

---

## Scope Check

This plan implements the document-parse evidence object only. It does not build query-run trace simulation, a new public `ragstudio-site` app, or a replacement for the Graph/Comparison pages. Public proof viewer work is represented by reusable read-only components and proof-packet export artifacts; mounting those components in a future separate public site remains a follow-up once `ragstudio-site` exists.

## File Structure

- `backend/src/ragstudio/schemas/document_parse_evidence.py`
  - New Pydantic response contract used by the API and exporter.
- `backend/src/ragstudio/services/document_parse_evidence_service.py`
  - New service that assembles evidence from existing persisted rows and sanitizes previews.
- `backend/src/ragstudio/services/document_parse_evidence_exporter.py`
  - New exporter/redactor for static proof-packet JSON.
- `backend/src/ragstudio/api/routes/documents.py`
  - Adds `GET /api/documents/{document_id}/parse-evidence`.
- `backend/tests/test_document_parse_evidence.py`
  - Backend service, route, and export tests.
- `frontend/src/features/document-evidence/types.ts`
  - Frontend contract mirroring the backend response without relying on generated OpenAPI output.
- `frontend/src/features/document-evidence/evidence-inspector.tsx`
  - Shared read-only inspector with local/public mode flags.
- `frontend/src/features/document-evidence/document-evidence-page.tsx`
  - Local Studio page that fetches the evidence contract and renders the inspector.
- `frontend/tests/document-evidence-inspector.test.tsx`
  - Component tests for rail selection, missing evidence, diff labels, redaction, and read-only mode.
- `frontend/tests/document-evidence-page.test.tsx`
  - Local page fetch/error/render tests.
- `frontend/src/api/client.ts`
  - Adds `documentParseEvidence(documentId)`.
- `frontend/src/App.tsx`
  - Adds `/document-evidence`.
- `frontend/src/lib/routes.ts`
  - Adds navigation entry.
- `docs/superpowers/specs/2026-05-18-document-parse-evidence-inspector-design.md`
  - Source design; do not modify unless implementation discovers a real design contradiction.

---

### Task 1: Backend Evidence Contract And Local Endpoint

**Files:**
- Create: `backend/src/ragstudio/schemas/document_parse_evidence.py`
- Create: `backend/src/ragstudio/services/document_parse_evidence_service.py`
- Modify: `backend/src/ragstudio/api/routes/documents.py`
- Create: `backend/tests/test_document_parse_evidence.py`

- [ ] **Step 1: Write failing backend tests**

Create `backend/tests/test_document_parse_evidence.py` with these tests:

```python
from __future__ import annotations

from pathlib import Path

import pytest
from ragstudio.db.models import Chunk, Document, GraphProjectionRecord, Job
from ragstudio.schemas.common import StageStatus
from ragstudio.services.document_parse_evidence_service import DocumentParseEvidenceService
from sqlalchemy import select


@pytest.mark.asyncio
async def test_parse_evidence_groups_page_stitch_decision(session, tmp_path: Path):
    artifact = tmp_path / "source.pdf"
    artifact.write_bytes(b"%PDF synthetic")
    document = Document(
        id="doc-stitch",
        filename="synthetic.pdf",
        content_type="application/pdf",
        sha256="sha-stitch",
        artifact_path=str(artifact),
        status=StageStatus.SUCCEEDED.value,
    )
    chunk = Chunk(
        id="chunk-stitch",
        document_id="doc-stitch",
        text="This paragraph starts on page one and\n\ncontinues on page two before ending.",
        source_location={
            "page_start": 1,
            "page_end": 2,
            "artifact": "source_content_list.json",
        },
        metadata_json={
            "parser_metadata": {
                "content_list_ref": "source_content_list.json",
                "split_strategy": "metadata_profile",
            },
            "split": {
                "source_blocks": [
                    {"block_id": "block-1", "page": 1, "block_index": 0, "text": "This paragraph starts on page one and"},
                    {"block_id": "block-2", "page": 2, "block_index": 1, "text": "continues on page two before ending."},
                ]
            },
        },
        extraction_quality={"quality_status": "passed"},
        content_type="text/markdown",
    )
    session.add_all([document, chunk])
    await session.commit()

    evidence = await DocumentParseEvidenceService(session).get_document_evidence("doc-stitch")

    assert evidence.document.id == "doc-stitch"
    assert evidence.document.filename == "synthetic.pdf"
    assert evidence.normalization_decisions[0].decision_type == "page_stitch"
    assert evidence.normalization_decisions[0].input_block_ids == ["block-1", "block-2"]
    assert evidence.normalization_decisions[0].output_chunk_ids == ["chunk-stitch"]
    assert evidence.chunks[0].page_start == 1
    assert evidence.chunks[0].page_end == 2
    assert evidence.proof.redaction_summary == []


@pytest.mark.asyncio
async def test_parse_evidence_groups_modal_and_warning_decisions(session, tmp_path: Path):
    artifact = tmp_path / "source.pdf"
    artifact.write_bytes(b"%PDF synthetic")
    document = Document(
        id="doc-modal",
        filename="modal.pdf",
        content_type="application/pdf",
        sha256="sha-modal",
        artifact_path=str(artifact),
        status=StageStatus.SUCCEEDED.value,
    )
    chunk = Chunk(
        id="chunk-table",
        document_id="doc-modal",
        text="Table: Scores\n\n| Name | Score |\n| --- | --- |\n| A | 9 |",
        source_location={"page": 3, "artifact": "source_content_list.json", "block_index": 4},
        metadata_json={
            "modal_router_processed": True,
            "modality": "table",
            "structured_data": {"rows": [["Name", "Score"], ["A", "9"]]},
            "parser_metadata": {"content_list_ref": "source_content_list.json"},
        },
        extraction_quality={
            "quality_status": "warning",
            "parser_warnings": [
                {"code": "table_recovered", "message": "Table extracted from MinerU content list.", "page": 3}
            ],
        },
        content_type="application/json",
    )
    session.add_all([document, chunk])
    await session.commit()

    evidence = await DocumentParseEvidenceService(session).get_document_evidence("doc-modal")

    assert [decision.decision_type for decision in evidence.normalization_decisions] == [
        "modal_route",
        "quality_warning",
    ]
    assert evidence.parser_blocks[0].modality == "table"
    assert evidence.warnings[0].code == "table_recovered"
    assert evidence.warnings[0].affected_chunk_ids == ["chunk-table"]


@pytest.mark.asyncio
async def test_parse_evidence_redacts_unsafe_artifact_values(session, tmp_path: Path):
    artifact = tmp_path / "private" / "secret.pdf"
    artifact.parent.mkdir()
    artifact.write_bytes(b"%PDF synthetic")
    document = Document(
        id="doc-redact",
        filename="secret.pdf",
        content_type="application/pdf",
        sha256="sha-redact",
        artifact_path=str(artifact),
        status=StageStatus.SUCCEEDED.value,
    )
    chunk = Chunk(
        id="chunk-redact",
        document_id="doc-redact",
        text="Private host reference should be redacted from metadata.",
        source_location={"artifact": str(artifact), "url": "http://10.0.0.5/private"},
        metadata_json={"provider_url": "http://internal.local/v1", "api_key": "sk-secret"},
        extraction_quality={},
    )
    session.add_all([document, chunk])
    await session.commit()

    evidence = await DocumentParseEvidenceService(session).get_document_evidence("doc-redact")
    serialized = evidence.model_dump_json()

    assert str(tmp_path) not in serialized
    assert "10.0.0.5" not in serialized
    assert "internal.local" not in serialized
    assert "sk-secret" not in serialized
    assert evidence.proof.redaction_summary


@pytest.mark.asyncio
async def test_parse_evidence_route_returns_404_for_missing_document(client):
    response = await client.get("/api/documents/missing-doc/parse-evidence")

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"


@pytest.mark.asyncio
async def test_parse_evidence_route_returns_contract(client, tmp_path: Path):
    app = client._transport.app
    artifact = tmp_path / "route.pdf"
    artifact.write_bytes(b"%PDF synthetic")
    async with app.state.session_factory() as session:
        session.add(
            Document(
                id="doc-route",
                filename="route.pdf",
                content_type="application/pdf",
                sha256="sha-route",
                artifact_path=str(artifact),
                status=StageStatus.SUCCEEDED.value,
            )
        )
        session.add(
            Chunk(
                id="chunk-route",
                document_id="doc-route",
                text="Route chunk",
                source_location={"page": 1},
                metadata_json={},
                extraction_quality={},
            )
        )
        await session.commit()

    response = await client.get("/api/documents/doc-route/parse-evidence")

    assert response.status_code == 200
    body = response.json()
    assert body["document"]["id"] == "doc-route"
    assert body["chunks"][0]["id"] == "chunk-route"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -m pytest backend/tests/test_document_parse_evidence.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `ragstudio.services.document_parse_evidence_service`.

- [ ] **Step 3: Add Pydantic evidence schemas**

Create `backend/src/ragstudio/schemas/document_parse_evidence.py`:

```python
from __future__ import annotations

from typing import Any, Literal

from ragstudio.schemas.common import StudioModel


class DocumentEvidenceSummary(StudioModel):
    id: str
    filename: str
    content_type: str
    status: str
    page_count: int | None = None
    parser_mode: str | None = None


class SourceArtifactEvidence(StudioModel):
    id: str
    kind: str
    path: str | None = None
    checksum: str | None = None
    preview_available: bool = False
    preview_capped: bool = False
    hidden_count: int = 0


class ParserBlockEvidence(StudioModel):
    id: str
    page: int | None = None
    block_index: int | None = None
    block_type: str
    text_preview: str
    bbox: list[float] | None = None
    modality: str | None = None
    warning_ids: list[str] = []


class NormalizationDecisionEvidence(StudioModel):
    id: str
    decision_type: Literal[
        "page_stitch",
        "modal_route",
        "quality_gate",
        "quality_warning",
        "chunk_materialization",
        "unresolved",
    ]
    title: str
    summary: str
    input_block_ids: list[str] = []
    output_chunk_ids: list[str] = []
    warning_ids: list[str] = []
    status: str = "recorded"


class ChunkEvidence(StudioModel):
    id: str
    text_preview: str
    page_start: int | None = None
    page_end: int | None = None
    source_location: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    modality: str | None = None
    quality_status: str | None = None
    warning_ids: list[str] = []


class WarningEvidence(StudioModel):
    id: str
    code: str
    message: str
    severity: str = "warning"
    page: int | None = None
    block_id: str | None = None
    decision_id: str | None = None
    affected_chunk_ids: list[str] = []


class ProofEvidence(StudioModel):
    source_commit: str | None = None
    proof_packet_id: str | None = None
    mode: Literal["local", "static-fixture", "export"] = "local"
    replay_command: str | None = None
    limitations: list[str] = []
    redaction_summary: list[str] = []


class DocumentParseEvidence(StudioModel):
    document: DocumentEvidenceSummary
    source_artifacts: list[SourceArtifactEvidence] = []
    parser_blocks: list[ParserBlockEvidence] = []
    normalization_decisions: list[NormalizationDecisionEvidence] = []
    chunks: list[ChunkEvidence] = []
    warnings: list[WarningEvidence] = []
    proof: ProofEvidence
    missing_sections: list[str] = []
```

- [ ] **Step 4: Implement evidence assembly service**

Create `backend/src/ragstudio/services/document_parse_evidence_service.py`:

```python
from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Any

from ragstudio.db.models import Chunk, Document, GraphProjectionRecord, Job
from ragstudio.schemas.document_parse_evidence import (
    ChunkEvidence,
    DocumentEvidenceSummary,
    DocumentParseEvidence,
    NormalizationDecisionEvidence,
    ParserBlockEvidence,
    ProofEvidence,
    SourceArtifactEvidence,
    WarningEvidence,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

TEXT_PREVIEW_LIMIT = 600
SECRET_KEY_PATTERN = re.compile(r"(api[_-]?key|token|secret|password|authorization)", re.I)
PRIVATE_HOST_PATTERN = re.compile(
    r"(localhost|127\.0\.0\.1|0\.0\.0\.0|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+|internal\.local)",
    re.I,
)


class DocumentParseEvidenceNotFoundError(Exception):
    pass


class DocumentParseEvidenceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.redactions: set[str] = set()

    async def get_document_evidence(self, document_id: str) -> DocumentParseEvidence:
        document = await self.session.get(Document, document_id)
        if document is None:
            raise DocumentParseEvidenceNotFoundError(document_id)

        chunks = list(
            (
                await self.session.execute(
                    select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.created_at, Chunk.id)
                )
            )
            .scalars()
            .all()
        )
        jobs = list(
            (
                await self.session.execute(
                    select(Job).where(Job.target_id == document_id).order_by(Job.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        graph_records = list(
            (
                await self.session.execute(
                    select(GraphProjectionRecord)
                    .where(GraphProjectionRecord.document_id == document_id)
                    .order_by(GraphProjectionRecord.created_at.desc())
                )
            )
            .scalars()
            .all()
        )

        parser_mode = self._parser_mode(jobs, chunks)
        warnings = self._warnings(chunks)
        parser_blocks = self._parser_blocks(chunks, warnings)
        decisions = self._decisions(chunks, parser_blocks, warnings, graph_records)
        source_artifacts = self._source_artifacts(document, chunks)
        chunk_evidence = self._chunk_evidence(chunks, warnings)
        missing_sections = self._missing_sections(chunks, parser_blocks, decisions)

        return DocumentParseEvidence(
            document=DocumentEvidenceSummary(
                id=document.id,
                filename=self._safe_text(document.filename),
                content_type=document.content_type,
                status=document.status,
                page_count=self._page_count(chunk_evidence),
                parser_mode=parser_mode,
            ),
            source_artifacts=source_artifacts,
            parser_blocks=parser_blocks,
            normalization_decisions=decisions,
            chunks=chunk_evidence,
            warnings=warnings,
            proof=ProofEvidence(
                mode="local",
                redaction_summary=sorted(self.redactions),
                limitations=[] if chunks else ["No chunks have been materialized for this document."],
            ),
            missing_sections=missing_sections,
        )

    def _parser_mode(self, jobs: list[Job], chunks: list[Chunk]) -> str | None:
        for job in jobs:
            parser_mode = job.job_options.get("parser_mode")
            if isinstance(parser_mode, str):
                return parser_mode
        for chunk in chunks:
            parser_metadata = self._dict(chunk.metadata_json.get("parser_metadata"))
            parser_mode = parser_metadata.get("parser_mode")
            if isinstance(parser_mode, str):
                return parser_mode
        return None

    def _source_artifacts(self, document: Document, chunks: list[Chunk]) -> list[SourceArtifactEvidence]:
        artifacts: dict[str, SourceArtifactEvidence] = {}
        document_artifact = self._safe_artifact_path(document.artifact_path)
        artifacts["document"] = SourceArtifactEvidence(
            id="document",
            kind="upload",
            path=document_artifact,
            checksum=document.sha256,
            preview_available=False,
        )
        for chunk in chunks:
            source_location = self._safe_mapping(chunk.source_location)
            artifact = source_location.get("artifact")
            if isinstance(artifact, str) and artifact:
                artifact_id = f"artifact-{len(artifacts)}"
                artifacts.setdefault(
                    artifact,
                    SourceArtifactEvidence(
                        id=artifact_id,
                        kind="parser",
                        path=self._safe_artifact_path(artifact),
                        preview_available=True,
                        preview_capped=len(chunk.text) > TEXT_PREVIEW_LIMIT,
                        hidden_count=max(0, len(chunk.text) - TEXT_PREVIEW_LIMIT),
                    ),
                )
        return list(artifacts.values())

    def _parser_blocks(
        self,
        chunks: list[Chunk],
        warnings: list[WarningEvidence],
    ) -> list[ParserBlockEvidence]:
        warning_by_chunk = self._warning_ids_by_chunk(warnings)
        blocks: list[ParserBlockEvidence] = []
        seen: set[str] = set()
        for chunk in chunks:
            source_blocks = self._dict(chunk.metadata_json.get("split")).get("source_blocks")
            if isinstance(source_blocks, list):
                for fallback_index, item in enumerate(source_blocks):
                    if not isinstance(item, dict):
                        continue
                    block_id = str(item.get("block_id") or f"{chunk.id}-block-{fallback_index}")
                    if block_id in seen:
                        continue
                    seen.add(block_id)
                    blocks.append(
                        ParserBlockEvidence(
                            id=block_id,
                            page=self._int_or_none(item.get("page")),
                            block_index=self._int_or_none(item.get("block_index")),
                            block_type=str(item.get("block_type") or "text"),
                            text_preview=self._preview(str(item.get("text") or "")),
                            bbox=self._bbox(item.get("bbox")),
                            modality=self._safe_optional_text(item.get("modality")),
                            warning_ids=warning_by_chunk.get(chunk.id, []),
                        )
                    )
                continue
            block_id = f"{chunk.id}-source"
            blocks.append(
                ParserBlockEvidence(
                    id=block_id,
                    page=self._page_start(chunk.source_location),
                    block_index=self._int_or_none(chunk.source_location.get("block_index")),
                    block_type=str(chunk.metadata_json.get("modality") or "text"),
                    text_preview=self._preview(chunk.text),
                    modality=self._safe_optional_text(chunk.metadata_json.get("modality")),
                    warning_ids=warning_by_chunk.get(chunk.id, []),
                )
            )
        return blocks

    def _warnings(self, chunks: list[Chunk]) -> list[WarningEvidence]:
        warnings: list[WarningEvidence] = []
        for chunk in chunks:
            parser_warnings = chunk.extraction_quality.get("parser_warnings")
            if not isinstance(parser_warnings, list):
                continue
            for index, warning in enumerate(parser_warnings):
                warning_dict = warning if isinstance(warning, dict) else {"message": str(warning)}
                warning_id = f"{chunk.id}-warning-{index}"
                warnings.append(
                    WarningEvidence(
                        id=warning_id,
                        code=str(warning_dict.get("code") or "parser_warning"),
                        message=self._safe_text(str(warning_dict.get("message") or "Parser warning recorded.")),
                        severity=str(warning_dict.get("severity") or "warning"),
                        page=self._int_or_none(warning_dict.get("page")) or self._page_start(chunk.source_location),
                        affected_chunk_ids=[chunk.id],
                    )
                )
        return warnings

    def _decisions(
        self,
        chunks: list[Chunk],
        parser_blocks: list[ParserBlockEvidence],
        warnings: list[WarningEvidence],
        graph_records: list[GraphProjectionRecord],
    ) -> list[NormalizationDecisionEvidence]:
        decisions: list[NormalizationDecisionEvidence] = []
        blocks_by_chunk = self._block_ids_by_chunk(chunks, parser_blocks)
        warning_ids_by_chunk = self._warning_ids_by_chunk(warnings)
        for chunk in chunks:
            page_start = self._page_start(chunk.source_location)
            page_end = self._page_end(chunk.source_location)
            if page_start is not None and page_end is not None and page_end > page_start:
                decisions.append(
                    NormalizationDecisionEvidence(
                        id=f"{chunk.id}-page-stitch",
                        decision_type="page_stitch",
                        title=f"Page {page_start} -> {page_end} stitch",
                        summary="Ragstudio kept a semantic unit together across physical page boundaries.",
                        input_block_ids=blocks_by_chunk.get(chunk.id, []),
                        output_chunk_ids=[chunk.id],
                        warning_ids=warning_ids_by_chunk.get(chunk.id, []),
                    )
                )
            if chunk.metadata_json.get("modal_router_processed") is True:
                modality = str(chunk.metadata_json.get("modality") or "modal")
                decisions.append(
                    NormalizationDecisionEvidence(
                        id=f"{chunk.id}-modal-route",
                        decision_type="modal_route",
                        title=f"{modality.title()} extraction",
                        summary=f"Ragstudio routed this {modality} block through modal extraction before chunking.",
                        input_block_ids=blocks_by_chunk.get(chunk.id, []),
                        output_chunk_ids=[chunk.id],
                        warning_ids=warning_ids_by_chunk.get(chunk.id, []),
                    )
                )
            quality_status = chunk.extraction_quality.get("quality_status")
            if isinstance(quality_status, str) and quality_status not in {"passed", "ok"}:
                decisions.append(
                    NormalizationDecisionEvidence(
                        id=f"{chunk.id}-quality-gate",
                        decision_type="quality_gate",
                        title=f"Quality gate: {quality_status}",
                        summary="Chunk quality metadata marked this materialized chunk for review.",
                        input_block_ids=blocks_by_chunk.get(chunk.id, []),
                        output_chunk_ids=[chunk.id],
                        warning_ids=warning_ids_by_chunk.get(chunk.id, []),
                        status=quality_status,
                    )
                )
            if warning_ids_by_chunk.get(chunk.id):
                decisions.append(
                    NormalizationDecisionEvidence(
                        id=f"{chunk.id}-quality-warning",
                        decision_type="quality_warning",
                        title="Parser warning",
                        summary="Parser or normalization warnings are attached to this chunk.",
                        input_block_ids=blocks_by_chunk.get(chunk.id, []),
                        output_chunk_ids=[chunk.id],
                        warning_ids=warning_ids_by_chunk.get(chunk.id, []),
                        status="warning",
                    )
                )
        if not decisions and chunks:
            decisions.append(
                NormalizationDecisionEvidence(
                    id="chunk-materialization",
                    decision_type="chunk_materialization",
                    title="Chunk materialization",
                    summary="Document chunks were materialized without recorded parser warnings or special normalization decisions.",
                    input_block_ids=[block.id for block in parser_blocks],
                    output_chunk_ids=[chunk.id for chunk in chunks],
                )
            )
        if graph_records:
            failed = [record for record in graph_records if record.status == "failed"]
            if failed:
                decisions.append(
                    NormalizationDecisionEvidence(
                        id="graph-projection-warning",
                        decision_type="quality_warning",
                        title="Graph projection warning",
                        summary=self._safe_text(failed[0].error or "Graph projection failed."),
                        status="warning",
                    )
                )
        return decisions

    def _chunk_evidence(self, chunks: list[Chunk], warnings: list[WarningEvidence]) -> list[ChunkEvidence]:
        warning_by_chunk = self._warning_ids_by_chunk(warnings)
        return [
            ChunkEvidence(
                id=chunk.id,
                text_preview=self._preview(chunk.text),
                page_start=self._page_start(chunk.source_location),
                page_end=self._page_end(chunk.source_location),
                source_location=self._safe_mapping(chunk.source_location),
                metadata=self._safe_mapping(chunk.metadata_json),
                modality=self._safe_optional_text(chunk.metadata_json.get("modality")),
                quality_status=self._safe_optional_text(chunk.extraction_quality.get("quality_status")),
                warning_ids=warning_by_chunk.get(chunk.id, []),
            )
            for chunk in chunks
        ]

    def _missing_sections(
        self,
        chunks: list[Chunk],
        parser_blocks: list[ParserBlockEvidence],
        decisions: list[NormalizationDecisionEvidence],
    ) -> list[str]:
        missing: list[str] = []
        if not chunks:
            missing.append("chunks")
        if not parser_blocks:
            missing.append("parserBlocks")
        if not decisions:
            missing.append("normalizationDecisions")
        return missing

    def _block_ids_by_chunk(
        self,
        chunks: list[Chunk],
        parser_blocks: list[ParserBlockEvidence],
    ) -> dict[str, list[str]]:
        by_chunk: dict[str, list[str]] = {}
        block_ids = [block.id for block in parser_blocks]
        for chunk in chunks:
            explicit = self._dict(chunk.metadata_json.get("split")).get("source_blocks")
            if isinstance(explicit, list):
                by_chunk[chunk.id] = [
                    str(item.get("block_id") or f"{chunk.id}-block-{index}")
                    for index, item in enumerate(explicit)
                    if isinstance(item, dict)
                ]
            else:
                by_chunk[chunk.id] = [block_id for block_id in block_ids if block_id.startswith(chunk.id)]
        return by_chunk

    def _warning_ids_by_chunk(self, warnings: list[WarningEvidence]) -> dict[str, list[str]]:
        by_chunk: dict[str, list[str]] = {}
        for warning in warnings:
            for chunk_id in warning.affected_chunk_ids:
                by_chunk.setdefault(chunk_id, []).append(warning.id)
        return by_chunk

    def _page_count(self, chunks: list[ChunkEvidence]) -> int | None:
        pages = [page for chunk in chunks for page in [chunk.page_start, chunk.page_end] if page is not None]
        return max(pages) if pages else None

    def _preview(self, value: str) -> str:
        safe = self._safe_text(value)
        return safe if len(safe) <= TEXT_PREVIEW_LIMIT else f"{safe[:TEXT_PREVIEW_LIMIT].rstrip()}..."

    def _safe_mapping(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        safe: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if SECRET_KEY_PATTERN.search(key_text):
                safe[key_text] = "[redacted]"
                self.redactions.add(f"Redacted secret-like field `{key_text}`.")
                continue
            safe[key_text] = self._safe_value(item, key_text)
        return safe

    def _safe_value(self, value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return self._safe_mapping(value)
        if isinstance(value, list):
            return [self._safe_value(item, key) for item in value[:50]]
        if isinstance(value, str):
            if SECRET_KEY_PATTERN.search(key):
                self.redactions.add(f"Redacted secret-like field `{key}`.")
                return "[redacted]"
            return self._safe_text(value)
        return value

    def _safe_text(self, value: str) -> str:
        text = value
        if self._looks_like_absolute_path(text):
            self.redactions.add("Redacted local absolute path.")
            return Path(text).name or "[redacted-path]"
        if PRIVATE_HOST_PATTERN.search(text):
            self.redactions.add("Redacted private host or endpoint.")
            return PRIVATE_HOST_PATTERN.sub("[redacted-host]", text)
        if text.startswith("sk-") or text.startswith("Bearer "):
            self.redactions.add("Redacted secret-shaped value.")
            return "[redacted-secret]"
        return text

    def _safe_optional_text(self, value: Any) -> str | None:
        return self._safe_text(value) if isinstance(value, str) else None

    def _safe_artifact_path(self, value: str | None) -> str | None:
        if not value:
            return None
        safe = self._safe_text(value)
        return safe.replace("\\", "/")

    def _looks_like_absolute_path(self, value: str) -> bool:
        return bool(re.match(r"^[A-Za-z]:[\\/]", value)) or value.startswith("/")

    def _page_start(self, source_location: dict[str, Any]) -> int | None:
        return self._int_or_none(source_location.get("page_start")) or self._int_or_none(
            source_location.get("page")
        )

    def _page_end(self, source_location: dict[str, Any]) -> int | None:
        return self._int_or_none(source_location.get("page_end")) or self._page_start(source_location)

    def _int_or_none(self, value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def _dict(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _bbox(self, value: Any) -> list[float] | None:
        if not isinstance(value, list) or len(value) != 4:
            return None
        output: list[float] = []
        for item in value:
            if not isinstance(item, int | float):
                return None
            output.append(float(item))
        return output
```

- [ ] **Step 5: Add route**

In `backend/src/ragstudio/api/routes/documents.py`, add imports:

```python
from ragstudio.schemas.document_parse_evidence import DocumentParseEvidence
from ragstudio.services.document_parse_evidence_service import (
    DocumentParseEvidenceNotFoundError,
    DocumentParseEvidenceService,
)
```

Add this route before `delete_document`:

```python
@router.get("/{document_id}/parse-evidence", response_model=DocumentParseEvidence)
async def get_document_parse_evidence(
    document_id: str,
    session: AsyncSession = Depends(get_session),
) -> DocumentParseEvidence:
    try:
        return await DocumentParseEvidenceService(session).get_document_evidence(document_id)
    except DocumentParseEvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
```

- [ ] **Step 6: Run focused backend tests**

Run:

```powershell
python -m pytest backend/tests/test_document_parse_evidence.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```powershell
git add backend/src/ragstudio/schemas/document_parse_evidence.py backend/src/ragstudio/services/document_parse_evidence_service.py backend/src/ragstudio/api/routes/documents.py backend/tests/test_document_parse_evidence.py
git commit -m "feat: expose document parse evidence contract"
```

---

### Task 2: Proof Export And Redaction Validation

**Files:**
- Create: `backend/src/ragstudio/services/document_parse_evidence_exporter.py`
- Modify: `backend/tests/test_document_parse_evidence.py`
- Modify: `docs/benchmarks/ragstudio-oss-proof-v1/manifest.json`

- [ ] **Step 1: Add failing exporter tests**

Append to `backend/tests/test_document_parse_evidence.py`:

```python
from ragstudio.schemas.document_parse_evidence import (
    ChunkEvidence,
    DocumentEvidenceSummary,
    DocumentParseEvidence,
    NormalizationDecisionEvidence,
    ProofEvidence,
)
from ragstudio.services.document_parse_evidence_exporter import (
    DocumentParseEvidenceExporter,
    UnsafeProofExportError,
)


def test_document_parse_evidence_exporter_writes_static_artifact(tmp_path: Path):
    evidence = DocumentParseEvidence(
        document=DocumentEvidenceSummary(
            id="doc-public",
            filename="synthetic.pdf",
            content_type="application/pdf",
            status="succeeded",
            page_count=2,
            parser_mode="mineru_strict",
        ),
        normalization_decisions=[
            NormalizationDecisionEvidence(
                id="decision-1",
                decision_type="page_stitch",
                title="Page 1 -> 2 stitch",
                summary="Semantic unit crossed a physical page boundary.",
                output_chunk_ids=["chunk-1"],
            )
        ],
        chunks=[ChunkEvidence(id="chunk-1", text_preview="safe preview", page_start=1, page_end=2)],
        proof=ProofEvidence(mode="local", redaction_summary=[]),
    )

    output = DocumentParseEvidenceExporter().export(
        evidence,
        packet_dir=tmp_path,
        proof_packet_id="ragstudio-oss-proof-v1",
        source_commit="abc1234",
    )

    assert output.relative_path == "artifacts/document-parse-evidence.export.json"
    exported = (tmp_path / output.relative_path).read_text(encoding="utf-8")
    assert '"mode":"export"' in exported
    assert '"proof_packet_id":"ragstudio-oss-proof-v1"' in exported
    assert '"source_commit":"abc1234"' in exported


def test_document_parse_evidence_exporter_rejects_unsafe_values(tmp_path: Path):
    evidence = DocumentParseEvidence(
        document=DocumentEvidenceSummary(
            id="doc-private",
            filename="private.pdf",
            content_type="application/pdf",
            status="succeeded",
        ),
        chunks=[ChunkEvidence(id="chunk-1", text_preview="http://10.0.0.5/private")],
        proof=ProofEvidence(mode="local"),
    )

    with pytest.raises(UnsafeProofExportError, match="private host"):
        DocumentParseEvidenceExporter().export(
            evidence,
            packet_dir=tmp_path,
            proof_packet_id="packet",
            source_commit="abc1234",
        )
```

- [ ] **Step 2: Run exporter tests to verify failure**

Run:

```powershell
python -m pytest backend/tests/test_document_parse_evidence.py::test_document_parse_evidence_exporter_writes_static_artifact backend/tests/test_document_parse_evidence.py::test_document_parse_evidence_exporter_rejects_unsafe_values -q
```

Expected: FAIL with `ModuleNotFoundError` for `document_parse_evidence_exporter`.

- [ ] **Step 3: Implement exporter**

Create `backend/src/ragstudio/services/document_parse_evidence_exporter.py`:

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ragstudio.schemas.document_parse_evidence import DocumentParseEvidence

EXPORT_RELATIVE_PATH = "artifacts/document-parse-evidence.export.json"
UNSAFE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[A-Za-z]:[\\/][^\"\\s]+"), "local absolute path"),
    (re.compile(r"/Users/|/home/|/tmp/"), "local absolute path"),
    (re.compile(r"(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|internal\.local)", re.I), "private host"),
    (re.compile(r"(api[_-]?key|token|secret|password|authorization)\"\\s*:", re.I), "secret-like key"),
    (re.compile(r"sk-[A-Za-z0-9_-]{8,}"), "secret-shaped value"),
)


class UnsafeProofExportError(ValueError):
    pass


@dataclass(frozen=True)
class DocumentParseEvidenceExportResult:
    relative_path: str
    bytes_written: int


class DocumentParseEvidenceExporter:
    def export(
        self,
        evidence: DocumentParseEvidence,
        *,
        packet_dir: Path,
        proof_packet_id: str,
        source_commit: str,
    ) -> DocumentParseEvidenceExportResult:
        export_evidence = evidence.model_copy(deep=True)
        export_evidence.proof.mode = "export"
        export_evidence.proof.proof_packet_id = proof_packet_id
        export_evidence.proof.source_commit = source_commit
        if not export_evidence.proof.replay_command:
            export_evidence.proof.replay_command = "./scripts/proof.sh --fixtures static-fixtures"

        payload = export_evidence.model_dump(mode="json")
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self._validate_safe(text)

        output_path = packet_dir / EXPORT_RELATIVE_PATH
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
        return DocumentParseEvidenceExportResult(
            relative_path=EXPORT_RELATIVE_PATH,
            bytes_written=len(text.encode("utf-8")),
        )

    def _validate_safe(self, text: str) -> None:
        for pattern, label in UNSAFE_PATTERNS:
            if pattern.search(text):
                raise UnsafeProofExportError(f"Proof export contains unsafe {label}.")
```

- [ ] **Step 4: Register export artifact in proof manifest**

Update `docs/benchmarks/ragstudio-oss-proof-v1/manifest.json` by adding this artifact entry to the existing artifact list:

```json
{
  "path": "artifacts/document-parse-evidence.export.json",
  "kind": "document_parse_evidence",
  "description": "Sanitized document parse evidence contract for the public proof viewer."
}
```

If the manifest uses a different shape, preserve its existing structure and add the new artifact with equivalent fields.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
python -m pytest backend/tests/test_document_parse_evidence.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```powershell
git add backend/src/ragstudio/services/document_parse_evidence_exporter.py backend/tests/test_document_parse_evidence.py docs/benchmarks/ragstudio-oss-proof-v1/manifest.json
git commit -m "feat: export sanitized document parse evidence"
```

---

### Task 3: Shared React Evidence Inspector

**Files:**
- Create: `frontend/src/features/document-evidence/types.ts`
- Create: `frontend/src/features/document-evidence/evidence-inspector.tsx`
- Create: `frontend/tests/document-evidence-inspector.test.tsx`

- [ ] **Step 1: Add failing component tests**

Create `frontend/tests/document-evidence-inspector.test.tsx`:

```tsx
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EvidenceInspector } from "../src/features/document-evidence/evidence-inspector";
import type { DocumentParseEvidence } from "../src/features/document-evidence/types";

const evidence: DocumentParseEvidence = {
  document: {
    id: "doc-1",
    filename: "synthetic.pdf",
    content_type: "application/pdf",
    status: "succeeded",
    page_count: 2,
    parser_mode: "mineru_strict",
  },
  source_artifacts: [
    {
      id: "artifact-1",
      kind: "parser",
      path: "artifacts/source_content_list.json",
      preview_available: true,
      preview_capped: true,
      hidden_count: 42,
    },
  ],
  parser_blocks: [
    {
      id: "block-1",
      page: 1,
      block_index: 0,
      block_type: "text",
      text_preview: "This paragraph starts on page one and",
      warning_ids: [],
    },
    {
      id: "block-2",
      page: 2,
      block_index: 1,
      block_type: "text",
      text_preview: "continues on page two before ending.",
      warning_ids: ["warning-1"],
    },
  ],
  normalization_decisions: [
    {
      id: "decision-1",
      decision_type: "page_stitch",
      title: "Page 1 -> 2 stitch",
      summary: "Ragstudio kept a semantic unit together across physical page boundaries.",
      input_block_ids: ["block-1", "block-2"],
      output_chunk_ids: ["chunk-1"],
      warning_ids: ["warning-1"],
      status: "recorded",
    },
  ],
  chunks: [
    {
      id: "chunk-1",
      text_preview: "This paragraph starts on page one and\n\ncontinues on page two before ending.",
      page_start: 1,
      page_end: 2,
      source_location: { page_start: 1, page_end: 2 },
      metadata: {},
      quality_status: "warning",
      warning_ids: ["warning-1"],
    },
  ],
  warnings: [
    {
      id: "warning-1",
      code: "missing_required_script",
      message: "Expected script was not detected on page 2.",
      severity: "warning",
      page: 2,
      affected_chunk_ids: ["chunk-1"],
    },
  ],
  proof: {
    mode: "export",
    source_commit: "abc1234",
    proof_packet_id: "ragstudio-oss-proof-v1",
    replay_command: "./scripts/proof.sh --fixtures static-fixtures",
    limitations: ["Synthetic fixture only."],
    redaction_summary: ["Redacted local absolute path."],
  },
  missing_sections: [],
};

describe("EvidenceInspector", () => {
  it("renders selected decision source blocks, chunk output, proof metadata, and diff labels", () => {
    render(<EvidenceInspector evidence={evidence} mode="public" />);

    expect(screen.getByRole("heading", { name: "Document parse evidence" })).toBeVisible();
    expect(screen.getByRole("button", { name: /Page 1 -> 2 stitch/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(screen.getByText("Source blocks")).toBeVisible();
    expect(screen.getByText("This paragraph starts on page one and")).toBeVisible();
    expect(screen.getByText("continues on page two before ending.")).toBeVisible();
    expect(screen.getByText("Chunk output")).toBeVisible();
    expect(screen.getByText("Added")).toBeVisible();
    expect(screen.getByText("Unchanged")).toBeVisible();
    expect(screen.getByText("Proof metadata")).toBeVisible();
    expect(screen.getByText("abc1234")).toBeVisible();
    expect(screen.getByText("Redacted local absolute path.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Reindex document" })).not.toBeInTheDocument();
  });

  it("supports rail selection", () => {
    const withSecondDecision = {
      ...evidence,
      normalization_decisions: [
        ...evidence.normalization_decisions,
        {
          id: "decision-2",
          decision_type: "quality_warning" as const,
          title: "Parser warning",
          summary: "Parser warning attached to chunk.",
          input_block_ids: ["block-2"],
          output_chunk_ids: ["chunk-1"],
          warning_ids: ["warning-1"],
          status: "warning",
        },
      ],
    };

    render(<EvidenceInspector evidence={withSecondDecision} mode="local" onReindex={() => undefined} />);

    fireEvent.click(screen.getByRole("button", { name: /Parser warning/ }));
    expect(screen.getByRole("button", { name: /Parser warning/ })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: "Reindex document" })).toBeVisible();
  });

  it("shows missing evidence sections explicitly", () => {
    render(<EvidenceInspector evidence={{ ...evidence, parser_blocks: [], missing_sections: ["parserBlocks"] }} />);

    expect(screen.getByText("Evidence unavailable")).toBeVisible();
    expect(screen.getByText("parserBlocks")).toBeVisible();
  });

  it("keeps artifact previews bounded", () => {
    render(<EvidenceInspector evidence={evidence} mode="public" />);

    const metadata = screen.getByRole("region", { name: "Proof metadata" });
    expect(within(metadata).getByText("42 hidden characters")).toBeVisible();
  });
});
```

- [ ] **Step 2: Run component tests to verify failure**

Run:

```powershell
cd frontend
npm test -- document-evidence-inspector.test.tsx
```

Expected: FAIL because `document-evidence/evidence-inspector` does not exist.

- [ ] **Step 3: Add frontend contract types**

Create `frontend/src/features/document-evidence/types.ts`:

```ts
export type EvidenceMode = "local" | "public";

export interface DocumentEvidenceSummary {
  id: string;
  filename: string;
  content_type: string;
  status: string;
  page_count?: number | null;
  parser_mode?: string | null;
}

export interface SourceArtifactEvidence {
  id: string;
  kind: string;
  path?: string | null;
  checksum?: string | null;
  preview_available: boolean;
  preview_capped: boolean;
  hidden_count: number;
}

export interface ParserBlockEvidence {
  id: string;
  page?: number | null;
  block_index?: number | null;
  block_type: string;
  text_preview: string;
  bbox?: number[] | null;
  modality?: string | null;
  warning_ids: string[];
}

export type NormalizationDecisionType =
  | "page_stitch"
  | "modal_route"
  | "quality_gate"
  | "quality_warning"
  | "chunk_materialization"
  | "unresolved";

export interface NormalizationDecisionEvidence {
  id: string;
  decision_type: NormalizationDecisionType;
  title: string;
  summary: string;
  input_block_ids: string[];
  output_chunk_ids: string[];
  warning_ids: string[];
  status: string;
}

export interface ChunkEvidence {
  id: string;
  text_preview: string;
  page_start?: number | null;
  page_end?: number | null;
  source_location: Record<string, unknown>;
  metadata: Record<string, unknown>;
  modality?: string | null;
  quality_status?: string | null;
  warning_ids: string[];
}

export interface WarningEvidence {
  id: string;
  code: string;
  message: string;
  severity: string;
  page?: number | null;
  block_id?: string | null;
  decision_id?: string | null;
  affected_chunk_ids: string[];
}

export interface ProofEvidence {
  source_commit?: string | null;
  proof_packet_id?: string | null;
  mode: "local" | "static-fixture" | "export";
  replay_command?: string | null;
  limitations: string[];
  redaction_summary: string[];
}

export interface DocumentParseEvidence {
  document: DocumentEvidenceSummary;
  source_artifacts: SourceArtifactEvidence[];
  parser_blocks: ParserBlockEvidence[];
  normalization_decisions: NormalizationDecisionEvidence[];
  chunks: ChunkEvidence[];
  warnings: WarningEvidence[];
  proof: ProofEvidence;
  missing_sections: string[];
}
```

- [ ] **Step 4: Implement shared inspector**

Create `frontend/src/features/document-evidence/evidence-inspector.tsx`:

```tsx
import { AlertCircle, Box, FileCode2, GitCommit, RotateCcw, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";

import { EmptyState } from "../../components/empty-state";
import { Button } from "../../components/ui/button";
import { cn, titleCase } from "../../lib/utils";
import type {
  ChunkEvidence,
  DocumentParseEvidence,
  EvidenceMode,
  NormalizationDecisionEvidence,
  ParserBlockEvidence,
  WarningEvidence,
} from "./types";

export function EvidenceInspector({
  evidence,
  mode = "local",
  onReindex,
}: {
  evidence: DocumentParseEvidence;
  mode?: EvidenceMode;
  onReindex?: () => void;
}) {
  const decisions = evidence.normalization_decisions;
  const [selectedDecisionId, setSelectedDecisionId] = useState(decisions[0]?.id ?? "");
  const selectedDecision = decisions.find((decision) => decision.id === selectedDecisionId) ?? decisions[0] ?? null;
  const selectedBlocks = useMemo(
    () => evidence.parser_blocks.filter((block) => selectedDecision?.input_block_ids.includes(block.id)),
    [evidence.parser_blocks, selectedDecision],
  );
  const selectedChunks = useMemo(
    () => evidence.chunks.filter((chunk) => selectedDecision?.output_chunk_ids.includes(chunk.id)),
    [evidence.chunks, selectedDecision],
  );
  const selectedWarnings = useMemo(
    () => evidence.warnings.filter((warning) => selectedDecision?.warning_ids.includes(warning.id)),
    [evidence.warnings, selectedDecision],
  );

  return (
    <div className="mx-auto grid max-w-7xl gap-4 xl:grid-cols-[280px_minmax(0,1fr)_300px]">
      <section className="xl:col-span-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-[var(--rs-accent)]">Document parse evidence</p>
            <h2 className="mt-1 truncate text-2xl font-semibold text-[var(--rs-ink)]">
              {evidence.document.filename}
            </h2>
            <p className="mt-1 text-sm text-[var(--rs-muted)]">
              {evidence.document.content_type} · {evidence.document.parser_mode ?? "Parser mode not recorded"}
            </p>
          </div>
          {mode === "local" && onReindex ? (
            <Button type="button" variant="secondary" onClick={onReindex}>
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
              Reindex document
            </Button>
          ) : null}
        </div>
        {evidence.missing_sections.length ? (
          <div className="mt-4 rounded-md border border-[var(--rs-warning)] bg-[var(--rs-warning-soft)] p-3 text-sm text-[var(--rs-warning)]">
            <p className="font-semibold">Evidence unavailable</p>
            <p className="mt-1">{evidence.missing_sections.join(", ")}</p>
          </div>
        ) : null}
      </section>

      <EvidenceRail
        decisions={decisions}
        selectedDecisionId={selectedDecision?.id ?? ""}
        onSelect={setSelectedDecisionId}
      />

      <main className="min-w-0 space-y-4">
        {selectedDecision ? (
          <>
            <DecisionSummary decision={selectedDecision} warnings={selectedWarnings} />
            <EvidencePanel title="Source blocks">
              {selectedBlocks.length ? (
                <div className="grid gap-2">
                  {selectedBlocks.map((block) => (
                    <BlockCard key={block.id} block={block} />
                  ))}
                </div>
              ) : (
                <MissingText>Source blocks not recorded for this decision.</MissingText>
              )}
            </EvidencePanel>
            <EvidencePanel title="Normalized unit">
              <DiffPanel blocks={selectedBlocks} chunks={selectedChunks} />
            </EvidencePanel>
            <EvidencePanel title="Chunk output">
              {selectedChunks.length ? (
                <div className="grid gap-2">
                  {selectedChunks.map((chunk) => (
                    <ChunkCard key={chunk.id} chunk={chunk} />
                  ))}
                </div>
              ) : (
                <MissingText>Chunk output not recorded for this decision.</MissingText>
              )}
            </EvidencePanel>
          </>
        ) : (
          <EmptyState icon={AlertCircle} title="Evidence unavailable" description="No decisions were recorded." />
        )}
      </main>

      <ProofMetadataPanel evidence={evidence} />
    </div>
  );
}

function EvidenceRail({
  decisions,
  selectedDecisionId,
  onSelect,
}: {
  decisions: NormalizationDecisionEvidence[];
  selectedDecisionId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <aside className="rounded-md border border-[var(--rs-line)] bg-[var(--rs-paper)] p-3" aria-label="Evidence decisions">
      <div className="mb-3 flex items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-[var(--rs-accent)]" aria-hidden="true" />
        <h3 className="text-sm font-semibold text-[var(--rs-ink)]">Decisions</h3>
      </div>
      <div className="grid gap-2">
        {decisions.map((decision) => (
          <button
            key={decision.id}
            type="button"
            aria-current={decision.id === selectedDecisionId ? "true" : undefined}
            onClick={() => onSelect(decision.id)}
            className={cn(
              "min-h-11 rounded-md border px-3 py-2 text-left text-sm transition-colors",
              decision.id === selectedDecisionId
                ? "border-[var(--rs-accent)] bg-[var(--rs-accent-soft)] text-[var(--rs-accent-deep)]"
                : "border-[var(--rs-line)] bg-[var(--rs-paper)] text-[var(--rs-text)] hover:bg-[var(--rs-field)]",
            )}
          >
            <span className="block font-semibold">{decision.title}</span>
            <span className="block text-xs opacity-80">{titleCase(decision.decision_type.replaceAll("_", " "))}</span>
          </button>
        ))}
      </div>
    </aside>
  );
}

function DecisionSummary({
  decision,
  warnings,
}: {
  decision: NormalizationDecisionEvidence;
  warnings: WarningEvidence[];
}) {
  return (
    <section className="rounded-md border border-[var(--rs-line)] bg-[var(--rs-paper)] p-4">
      <p className="text-xs font-semibold uppercase text-[var(--rs-muted)]">{decision.status}</p>
      <h3 className="mt-1 text-lg font-semibold text-[var(--rs-ink)]">{decision.title}</h3>
      <p className="mt-2 text-sm leading-6 text-[var(--rs-text)]">{decision.summary}</p>
      {warnings.length ? (
        <div className="mt-3 grid gap-2">
          {warnings.map((warning) => (
            <p key={warning.id} className="rounded-md bg-[var(--rs-warning-soft)] px-3 py-2 text-sm text-[var(--rs-warning)]">
              {warning.code}: {warning.message}
            </p>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function EvidencePanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-md border border-[var(--rs-line)] bg-[var(--rs-paper)] p-4" aria-label={title}>
      <h3 className="text-sm font-semibold text-[var(--rs-ink)]">{title}</h3>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function BlockCard({ block }: { block: ParserBlockEvidence }) {
  return (
    <article className="rounded-md border border-[var(--rs-line)] bg-[var(--rs-field)] p-3">
      <p className="text-xs font-semibold text-[var(--rs-muted)]">
        {block.block_type} · page {block.page ?? "?"} · block {block.block_index ?? "?"}
      </p>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-[var(--rs-text)]">{block.text_preview}</p>
    </article>
  );
}

function DiffPanel({ blocks, chunks }: { blocks: ParserBlockEvidence[]; chunks: ChunkEvidence[] }) {
  return (
    <div className="grid gap-2">
      {blocks.map((block) => (
        <DiffRow key={block.id} label="Unchanged" text={block.text_preview} />
      ))}
      {chunks.map((chunk) => (
        <DiffRow key={chunk.id} label="Added" text={chunk.text_preview} />
      ))}
      {!blocks.length && !chunks.length ? <MissingText>No diffable evidence recorded.</MissingText> : null}
    </div>
  );
}

function DiffRow({ label, text }: { label: "Added" | "Unchanged" | "Removed" | "Blocked"; text: string }) {
  return (
    <div className="grid gap-2 rounded-md border border-[var(--rs-line)] bg-[var(--rs-field)] p-3 sm:grid-cols-[110px_minmax(0,1fr)]">
      <span className="text-xs font-semibold uppercase text-[var(--rs-accent)]">{label}</span>
      <span className="whitespace-pre-wrap break-words text-sm leading-6 text-[var(--rs-text)]">{text}</span>
    </div>
  );
}

function ChunkCard({ chunk }: { chunk: ChunkEvidence }) {
  return (
    <article className="rounded-md border border-[var(--rs-line)] bg-[var(--rs-field)] p-3">
      <div className="flex flex-wrap gap-2 text-xs font-semibold text-[var(--rs-muted)]">
        <span>{chunk.id}</span>
        <span>page {chunk.page_start ?? "?"}{chunk.page_end && chunk.page_end !== chunk.page_start ? ` -> ${chunk.page_end}` : ""}</span>
        <span>{chunk.quality_status ?? "quality not recorded"}</span>
      </div>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-[var(--rs-text)]">{chunk.text_preview}</p>
    </article>
  );
}

function ProofMetadataPanel({ evidence }: { evidence: DocumentParseEvidence }) {
  return (
    <aside className="space-y-3 rounded-md border border-[var(--rs-line)] bg-[var(--rs-paper)] p-4" aria-label="Proof metadata">
      <div className="flex items-center gap-2">
        <GitCommit className="h-4 w-4 text-[var(--rs-accent)]" aria-hidden="true" />
        <h3 className="text-sm font-semibold text-[var(--rs-ink)]">Proof metadata</h3>
      </div>
      <MetadataItem label="Commit" value={evidence.proof.source_commit ?? "Not recorded"} mono />
      <MetadataItem label="Packet" value={evidence.proof.proof_packet_id ?? "Local evidence"} mono />
      <MetadataItem label="Replay" value={evidence.proof.replay_command ?? "Replay command not recorded"} mono />
      <div>
        <p className="text-xs font-semibold uppercase text-[var(--rs-muted)]">Artifacts</p>
        <div className="mt-2 grid gap-2">
          {evidence.source_artifacts.map((artifact) => (
            <div key={artifact.id} className="rounded-md bg-[var(--rs-field)] p-2 text-xs text-[var(--rs-text)]">
              <FileCode2 className="mr-1 inline h-3 w-3" aria-hidden="true" />
              {artifact.path ?? artifact.id}
              {artifact.preview_capped ? <span className="mt-1 block text-[var(--rs-warning)]">{artifact.hidden_count} hidden characters</span> : null}
            </div>
          ))}
        </div>
      </div>
      <ListSection title="Limitations" items={evidence.proof.limitations} icon={<Box className="h-4 w-4" aria-hidden="true" />} />
      <ListSection title="Redactions" items={evidence.proof.redaction_summary} icon={<ShieldCheck className="h-4 w-4" aria-hidden="true" />} />
    </aside>
  );
}

function MetadataItem({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-md bg-[var(--rs-field)] p-2">
      <p className="text-xs font-semibold uppercase text-[var(--rs-muted)]">{label}</p>
      <p className={cn("mt-1 break-words text-sm text-[var(--rs-text)]", mono && "font-mono text-xs")}>{value}</p>
    </div>
  );
}

function ListSection({ title, items, icon }: { title: string; items: string[]; icon: React.ReactNode }) {
  return (
    <div>
      <p className="flex items-center gap-1 text-xs font-semibold uppercase text-[var(--rs-muted)]">
        {icon}
        {title}
      </p>
      {items.length ? (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-[var(--rs-text)]">
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <MissingText>None recorded.</MissingText>
      )}
    </div>
  );
}

function MissingText({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-[var(--rs-muted)]">{children}</p>;
}
```

- [ ] **Step 5: Run component tests**

Run:

```powershell
cd frontend
npm test -- document-evidence-inspector.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```powershell
git add frontend/src/features/document-evidence/types.ts frontend/src/features/document-evidence/evidence-inspector.tsx frontend/tests/document-evidence-inspector.test.tsx
git commit -m "feat: add document evidence inspector component"
```

---

### Task 4: Local Studio Evidence Page And Navigation

**Files:**
- Create: `frontend/src/features/document-evidence/document-evidence-page.tsx`
- Create: `frontend/tests/document-evidence-page.test.tsx`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/lib/routes.ts`

- [ ] **Step 1: Add failing page tests**

Create `frontend/tests/document-evidence-page.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DocumentEvidencePage } from "../src/features/document-evidence/document-evidence-page";

const evidence = {
  document: {
    id: "doc-1",
    filename: "synthetic.pdf",
    content_type: "application/pdf",
    status: "succeeded",
    parser_mode: "mineru_strict",
  },
  source_artifacts: [],
  parser_blocks: [],
  normalization_decisions: [
    {
      id: "decision-1",
      decision_type: "chunk_materialization",
      title: "Chunk materialization",
      summary: "Chunks were materialized.",
      input_block_ids: [],
      output_chunk_ids: ["chunk-1"],
      warning_ids: [],
      status: "recorded",
    },
  ],
  chunks: [{ id: "chunk-1", text_preview: "Chunk text", source_location: {}, metadata: {}, warning_ids: [] }],
  warnings: [],
  proof: { mode: "local", limitations: [], redaction_summary: [] },
  missing_sections: [],
};

function renderPage(path = "/document-evidence?documentId=doc-1") {
  window.history.pushState(null, "", path);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DocumentEvidencePage />
    </QueryClientProvider>,
  );
}

describe("DocumentEvidencePage", () => {
  it("asks for a document id when missing", () => {
    renderPage("/document-evidence");

    expect(screen.getByText("Select a document")).toBeVisible();
  });

  it("loads and renders document parse evidence", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(evidence), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    renderPage();

    expect(await screen.findByText("synthetic.pdf")).toBeVisible();
    expect(screen.getByText("Chunk materialization")).toBeVisible();
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/documents/doc-1/parse-evidence", expect.any(Object));
  });

  it("shows API errors", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Document not found" }), {
        status: 404,
        headers: { "content-type": "application/json" },
      }),
    );

    renderPage();

    await waitFor(() => expect(screen.getByText("Document not found")).toBeVisible());
  });
});
```

- [ ] **Step 2: Run page tests to verify failure**

Run:

```powershell
cd frontend
npm test -- document-evidence-page.test.tsx
```

Expected: FAIL because `document-evidence-page` does not exist.

- [ ] **Step 3: Add API client method**

In `frontend/src/api/client.ts`, import the local type:

```ts
import type { DocumentParseEvidence } from "../features/document-evidence/types";
```

Add this method inside `apiClient` after `documents`:

```ts
  documentParseEvidence: (documentId: string) =>
    request<DocumentParseEvidence>(`/api/documents/${encodeURIComponent(documentId)}/parse-evidence`),
```

- [ ] **Step 4: Implement page**

Create `frontend/src/features/document-evidence/document-evidence-page.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, Loader2, Search } from "lucide-react";
import { useMemo } from "react";

import { apiClient } from "../../api/client";
import { EmptyState } from "../../components/empty-state";
import { Button } from "../../components/ui/button";
import { EvidenceInspector } from "./evidence-inspector";

export function DocumentEvidencePage() {
  const documentId = useMemo(() => new URLSearchParams(window.location.search).get("documentId") ?? "", []);
  const evidenceQuery = useQuery({
    queryKey: ["document-parse-evidence", documentId],
    queryFn: () => apiClient.documentParseEvidence(documentId),
    enabled: Boolean(documentId),
  });

  if (!documentId) {
    return (
      <EmptyState
        icon={Search}
        title="Select a document"
        description="Open document parse evidence from a document row or add ?documentId=... to the URL."
      />
    );
  }

  if (evidenceQuery.isLoading) {
    return <EmptyState icon={Loader2} title="Loading evidence" description="Fetching document parse evidence." />;
  }

  if (evidenceQuery.isError) {
    return (
      <EmptyState
        icon={AlertCircle}
        title="Evidence unavailable"
        description={evidenceQuery.error.message}
        action={
          <Button type="button" variant="secondary" onClick={() => void evidenceQuery.refetch()}>
            Retry
          </Button>
        }
      />
    );
  }

  if (!evidenceQuery.data) {
    return <EmptyState icon={AlertCircle} title="Evidence unavailable" description="No evidence returned." />;
  }

  return <EvidenceInspector evidence={evidenceQuery.data} mode="local" />;
}
```

- [ ] **Step 5: Add route and navigation**

In `frontend/src/App.tsx`, add import:

```ts
import { DocumentEvidencePage } from "./features/document-evidence/document-evidence-page";
```

Add title:

```ts
  "/document-evidence": "Parse Evidence",
```

Add switch case before `/documents` or after it:

```tsx
      case "/document-evidence":
        return <DocumentEvidencePage />;
```

In `frontend/src/lib/routes.ts`, add `ShieldCheck` to the lucide import and add a route near Documents:

```ts
  { href: "/document-evidence", label: "Evidence", icon: ShieldCheck, enabled: true },
```

- [ ] **Step 6: Run page tests**

Run:

```powershell
cd frontend
npm test -- document-evidence-page.test.tsx document-evidence-inspector.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```powershell
git add frontend/src/features/document-evidence/document-evidence-page.tsx frontend/tests/document-evidence-page.test.tsx frontend/src/api/client.ts frontend/src/App.tsx frontend/src/lib/routes.ts
git commit -m "feat: mount document evidence in studio"
```

---

### Task 5: Verification, Lint, And Plan Closeout

**Files:**
- Modify: `docs/superpowers/plans/2026-05-18-document-parse-evidence-inspector.md`

- [ ] **Step 1: Run backend focused verification**

Run:

```powershell
python -m pytest backend/tests/test_document_parse_evidence.py -q
python -m ruff check backend/src/ragstudio/schemas/document_parse_evidence.py backend/src/ragstudio/services/document_parse_evidence_service.py backend/src/ragstudio/services/document_parse_evidence_exporter.py backend/src/ragstudio/api/routes/documents.py backend/tests/test_document_parse_evidence.py
```

Expected: PASS.

- [ ] **Step 2: Run frontend focused verification**

Run:

```powershell
cd frontend
npm test -- document-evidence-inspector.test.tsx document-evidence-page.test.tsx
npm run lint
npm run build
```

Expected: PASS.

- [ ] **Step 3: Search for unsafe public proof values in exported fixture**

If `docs/benchmarks/ragstudio-oss-proof-v1/artifacts/document-parse-evidence.export.json` exists, run:

```powershell
Select-String -Path 'docs\benchmarks\ragstudio-oss-proof-v1\artifacts\document-parse-evidence.export.json' -Pattern 'C:\\|E:\\|/Users/|/home/|localhost|127\.0\.0\.1|10\.|192\.168|internal\.local|api_key|token|secret|password|sk-' -CaseSensitive:$false
```

Expected: no matches.

- [ ] **Step 4: Mark plan checkboxes complete**

Update this plan file so completed steps are marked with `[x]`. Do not mark a step complete unless its command passed or its expected failure occurred during TDD.

- [ ] **Step 5: Commit plan**

Run:

```powershell
git add docs/superpowers/plans/2026-05-18-document-parse-evidence-inspector.md
git commit -m "docs: plan document parse evidence inspector"
```

---

## Self-Review

**Spec coverage:** This plan covers the shared `DocumentParseEvidence` contract, local API endpoint, public proof export/redaction, read-only shared inspector, Local Studio mounting, explicit missing evidence states, accessibility labels, and focused backend/frontend/proof-packet tests. It intentionally defers query-run trace simulation and a standalone public site mount because the spec scoped them as later work or host-specific future wiring.

**Completeness scan:** The plan contains concrete files, test code, implementation code, commands, and expected outcomes. It does not use open-ended implementation markers.

**Type consistency:** Backend schema fields use snake_case and the frontend local contract mirrors those response keys directly. `documentParseEvidence()` returns the frontend `DocumentParseEvidence` type. The inspector consumes `normalization_decisions`, `parser_blocks`, `chunks`, `warnings`, `source_artifacts`, and `proof` exactly as defined.
