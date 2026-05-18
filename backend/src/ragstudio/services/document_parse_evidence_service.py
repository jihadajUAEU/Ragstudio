from __future__ import annotations

import re
from pathlib import Path, PurePath
from typing import Any
from urllib.parse import urlsplit

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
SECRET_KEY_PATTERN = re.compile(r"(api[_-]?key|token|secret|password|authorization)", re.IGNORECASE)
WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")
UNIX_ABSOLUTE_PATH_PATTERN = re.compile(r"^/([^/]+/)+[^/]+$")


class DocumentParseEvidenceNotFoundError(LookupError):
    pass


class DocumentParseEvidenceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._redactions: set[str] = set()

    async def get_document_evidence(self, document_id: str) -> DocumentParseEvidence:
        document = await self.session.get(Document, document_id)
        if document is None:
            raise DocumentParseEvidenceNotFoundError(document_id)

        chunks = list(
            (
                await self.session.execute(
                    select(Chunk)
                    .where(Chunk.document_id == document_id)
                    .order_by(Chunk.created_at.asc(), Chunk.id.asc())
                )
            )
            .scalars()
            .all()
        )
        jobs = list(
            (
                await self.session.execute(
                    select(Job)
                    .where(Job.target_id == document_id)
                    .order_by(Job.created_at.desc(), Job.id.desc())
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
                    .order_by(GraphProjectionRecord.created_at.desc(), GraphProjectionRecord.id.desc())
                )
            )
            .scalars()
            .all()
        )

        warnings = self._build_warnings(chunks)
        warning_ids_by_chunk = self._warning_ids_by_chunk(warnings)
        parser_blocks = self._build_parser_blocks(chunks, warning_ids_by_chunk)
        block_ids_by_chunk = self._block_ids_by_chunk(parser_blocks)
        decisions = self._build_decisions(chunks, graph_records, warning_ids_by_chunk, block_ids_by_chunk)
        warnings = self._attach_warning_decisions(warnings, decisions)
        chunk_evidence = self._build_chunks(chunks, warning_ids_by_chunk)
        source_artifacts = self._build_source_artifacts(document, chunks)
        limitations = self._proof_limitations(chunks, graph_records)
        missing_sections = self._missing_sections(chunks, parser_blocks, decisions)

        return DocumentParseEvidence(
            document=DocumentEvidenceSummary(
                id=document.id,
                filename=self._sanitize_string(document.filename, context="document.filename"),
                content_type=document.content_type,
                status=document.status,
                page_count=self._page_count(chunks),
                parser_mode=self._parser_mode(jobs, chunks),
            ),
            source_artifacts=source_artifacts,
            parser_blocks=parser_blocks,
            normalization_decisions=decisions,
            chunks=chunk_evidence,
            warnings=warnings,
            proof=ProofEvidence(
                mode="local",
                limitations=limitations,
                redaction_summary=sorted(self._redactions),
            ),
            missing_sections=missing_sections,
        )

    def _build_warnings(self, chunks: list[Chunk]) -> list[WarningEvidence]:
        warnings: list[WarningEvidence] = []
        for chunk in chunks:
            extraction_quality = self._chunk_extraction_quality(chunk)
            parser_warnings = extraction_quality.get("parser_warnings")
            if not isinstance(parser_warnings, list):
                continue
            for index, item in enumerate(parser_warnings):
                if not isinstance(item, dict):
                    continue
                code = self._coerce_string(item.get("code")) or "parser_warning"
                message = self._coerce_string(item.get("message")) or "Parser warning recorded."
                warnings.append(
                    WarningEvidence(
                        id=f"warning-{chunk.id}-{index}",
                        code=code,
                        message=self._sanitize_string(message, context=f"warning:{chunk.id}:{code}"),
                        severity=self._coerce_string(item.get("severity")) or "warning",
                        page=self._page_value(item.get("page")) or self._page_value(chunk.source_location.get("page")),
                        block_id=self._coerce_string(item.get("block_id")),
                        affected_chunk_ids=[chunk.id],
                    )
                )
        return warnings

    def _build_parser_blocks(
        self,
        chunks: list[Chunk],
        warning_ids_by_chunk: dict[str, list[str]],
    ) -> list[ParserBlockEvidence]:
        blocks: list[ParserBlockEvidence] = []
        seen_ids: set[str] = set()
        for chunk in chunks:
            source_blocks = self._dict_value(chunk.metadata_json.get("split")).get("source_blocks")
            chunk_warnings = warning_ids_by_chunk.get(chunk.id, [])
            if isinstance(source_blocks, list) and source_blocks:
                for fallback_index, item in enumerate(source_blocks):
                    if not isinstance(item, dict):
                        continue
                    block_id = self._coerce_string(item.get("block_id")) or f"{chunk.id}-block-{fallback_index}"
                    if block_id in seen_ids:
                        continue
                    seen_ids.add(block_id)
                    blocks.append(
                        ParserBlockEvidence(
                            id=block_id,
                            page=self._page_value(item.get("page")),
                            block_index=self._page_value(item.get("block_index")),
                            block_type=self._coerce_string(item.get("block_type"))
                            or self._coerce_string(item.get("type"))
                            or "text",
                            text_preview=self._preview(
                                self._coerce_string(item.get("text")) or chunk.text
                            ),
                            bbox=self._bbox_value(item.get("bbox")),
                            modality=self._chunk_modality(chunk),
                            warning_ids=list(chunk_warnings),
                        )
                    )
                continue

            fallback_id = f"{chunk.id}-block"
            if fallback_id in seen_ids:
                continue
            seen_ids.add(fallback_id)
            blocks.append(
                ParserBlockEvidence(
                    id=fallback_id,
                    page=self._page_value(
                        chunk.source_location.get("page")
                        if chunk.source_location.get("page") is not None
                        else chunk.source_location.get("page_start")
                    ),
                    block_index=self._page_value(chunk.source_location.get("block_index")),
                    block_type=self._chunk_modality(chunk) or "text",
                    text_preview=self._preview(chunk.text),
                    modality=self._chunk_modality(chunk),
                    warning_ids=list(chunk_warnings),
                )
            )
        return blocks

    def _build_decisions(
        self,
        chunks: list[Chunk],
        graph_records: list[GraphProjectionRecord],
        warning_ids_by_chunk: dict[str, list[str]],
        block_ids_by_chunk: dict[str, list[str]],
    ) -> list[NormalizationDecisionEvidence]:
        decisions: list[NormalizationDecisionEvidence] = []
        for chunk in chunks:
            input_block_ids = self._input_block_ids(chunk, block_ids_by_chunk)
            page_start, page_end = self._chunk_pages(chunk)
            if page_start is not None and page_end is not None and page_start != page_end:
                decisions.append(
                    NormalizationDecisionEvidence(
                        id=f"decision-page-stitch-{chunk.id}",
                        decision_type="page_stitch",
                        title="Page stitch",
                        summary=(
                            f"Chunk spans pages {page_start} to {page_end} after joining parser blocks "
                            "into one normalized unit."
                        ),
                        input_block_ids=input_block_ids,
                        output_chunk_ids=[chunk.id],
                    )
                )

            if self._chunk_modality(chunk) and self._is_modal_chunk(chunk):
                decisions.append(
                    NormalizationDecisionEvidence(
                        id=f"decision-modal-route-{chunk.id}",
                        decision_type="modal_route",
                        title="Modal route",
                        summary=(
                            f"Chunk was preserved as {self._chunk_modality(chunk)} content during parser "
                            "normalization."
                        ),
                        input_block_ids=input_block_ids,
                        output_chunk_ids=[chunk.id],
                    )
                )

            warning_ids = warning_ids_by_chunk.get(chunk.id, [])
            if warning_ids or self._quality_status(chunk) == "warning":
                decisions.append(
                    NormalizationDecisionEvidence(
                        id=f"decision-quality-warning-{chunk.id}",
                        decision_type="quality_warning",
                        title="Quality warning",
                        summary="Parser quality warnings were recorded for this normalized chunk.",
                        input_block_ids=input_block_ids,
                        output_chunk_ids=[chunk.id],
                        warning_ids=warning_ids,
                        status=self._quality_status(chunk) or "recorded",
                    )
                )

        latest_graph = graph_records[0] if graph_records else None
        if latest_graph is not None:
            decision_type = "chunk_materialization" if latest_graph.status == "succeeded" else "quality_gate"
            title = "Chunk materialization" if decision_type == "chunk_materialization" else "Quality gate"
            summary = (
                f"Latest graph projection status is {latest_graph.status} "
                f"with {latest_graph.node_count} nodes and {latest_graph.edge_count} edges."
            )
            decisions.append(
                NormalizationDecisionEvidence(
                    id=f"decision-graph-{latest_graph.id}",
                    decision_type=decision_type,
                    title=title,
                    summary=summary,
                    output_chunk_ids=[chunk.id for chunk in chunks],
                    status=latest_graph.status,
                )
            )

        return decisions

    def _attach_warning_decisions(
        self,
        warnings: list[WarningEvidence],
        decisions: list[NormalizationDecisionEvidence],
    ) -> list[WarningEvidence]:
        quality_decisions = {
            chunk_id: decision.id
            for decision in decisions
            if decision.decision_type == "quality_warning"
            for chunk_id in decision.output_chunk_ids
        }
        updated: list[WarningEvidence] = []
        for warning in warnings:
            decision_id = next(
                (quality_decisions.get(chunk_id) for chunk_id in warning.affected_chunk_ids if quality_decisions.get(chunk_id)),
                None,
            )
            updated.append(warning.model_copy(update={"decision_id": decision_id}))
        return updated

    def _build_chunks(
        self,
        chunks: list[Chunk],
        warning_ids_by_chunk: dict[str, list[str]],
    ) -> list[ChunkEvidence]:
        output: list[ChunkEvidence] = []
        for chunk in chunks:
            page_start, page_end = self._chunk_pages(chunk)
            output.append(
                ChunkEvidence(
                    id=chunk.id,
                    text_preview=self._preview(chunk.text),
                    page_start=page_start,
                    page_end=page_end,
                    source_location=self._sanitize_value(
                        self._dict_value(chunk.source_location),
                        context=f"chunk:{chunk.id}:source_location",
                    ),
                    metadata=self._sanitize_value(
                        self._dict_value(chunk.metadata_json),
                        context=f"chunk:{chunk.id}:metadata",
                    ),
                    modality=self._chunk_modality(chunk),
                    quality_status=self._quality_status(chunk),
                    warning_ids=list(warning_ids_by_chunk.get(chunk.id, [])),
                )
            )
        return output

    def _build_source_artifacts(
        self,
        document: Document,
        chunks: list[Chunk],
    ) -> list[SourceArtifactEvidence]:
        artifacts: dict[str, SourceArtifactEvidence] = {}
        document_path = self._sanitize_artifact_path(document.artifact_path, context="document.artifact_path")
        artifacts["document"] = SourceArtifactEvidence(
            id="document",
            kind="upload",
            path=document_path,
            checksum=document.sha256,
            preview_available=False,
        )
        for chunk in chunks:
            for raw_artifact in self._artifact_refs(chunk):
                safe_path = self._sanitize_artifact_path(raw_artifact, context=f"chunk:{chunk.id}:artifact")
                if safe_path in artifacts:
                    continue
                artifacts[safe_path] = SourceArtifactEvidence(
                    id=f"artifact-{len(artifacts)}",
                    kind="parser",
                    path=safe_path,
                    preview_available=True,
                    preview_capped=len(chunk.text) > TEXT_PREVIEW_LIMIT,
                    hidden_count=max(len(chunk.text) - TEXT_PREVIEW_LIMIT, 0),
                )
        return list(artifacts.values())

    def _proof_limitations(
        self,
        chunks: list[Chunk],
        graph_records: list[GraphProjectionRecord],
    ) -> list[str]:
        limitations: list[str] = []
        if not chunks:
            limitations.append("No chunks have been materialized for this document.")
        if not graph_records:
            limitations.append("No graph projection record is available for this document.")
        elif graph_records[0].status != "succeeded":
            limitations.append(
                f"Latest graph projection status is {graph_records[0].status}; graph-backed proof is incomplete."
            )
        return limitations

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
            missing.append("parser_blocks")
        if not decisions:
            missing.append("normalization_decisions")
        return missing

    def _parser_mode(self, jobs: list[Job], chunks: list[Chunk]) -> str | None:
        for job in jobs:
            parser_mode = self._coerce_string(self._dict_value(job.job_options).get("parser_mode"))
            if parser_mode:
                return parser_mode
        for chunk in chunks:
            parser_metadata = self._dict_value(chunk.metadata_json.get("parser_metadata"))
            parser_mode = self._coerce_string(parser_metadata.get("parser_mode"))
            if parser_mode:
                return parser_mode
            if parser_metadata.get("backend") == "mineru":
                return "mineru_strict"
        return None

    def _page_count(self, chunks: list[Chunk]) -> int | None:
        pages = [page for chunk in chunks for page in self._chunk_pages(chunk) if isinstance(page, int)]
        return max(pages) if pages else None

    def _chunk_pages(self, chunk: Chunk) -> tuple[int | None, int | None]:
        page_start = self._page_value(chunk.source_location.get("page_start"))
        page_end = self._page_value(chunk.source_location.get("page_end"))
        page = self._page_value(chunk.source_location.get("page"))
        if page_start is None and page is not None:
            page_start = page
        if page_end is None and page is not None:
            page_end = page
        return page_start, page_end

    def _chunk_modality(self, chunk: Chunk) -> str | None:
        return self._coerce_string(chunk.metadata_json.get("modality"))

    def _quality_status(self, chunk: Chunk) -> str | None:
        return self._coerce_string(self._chunk_extraction_quality(chunk).get("quality_status"))

    def _chunk_extraction_quality(self, chunk: Chunk) -> dict[str, Any]:
        if isinstance(chunk.extraction_quality, dict):
            return dict(chunk.extraction_quality)
        metadata_quality = self._dict_value(chunk.metadata_json.get("extraction_quality"))
        return metadata_quality

    def _artifact_refs(self, chunk: Chunk) -> list[str]:
        refs: list[str] = []
        artifact = self._coerce_string(chunk.source_location.get("artifact"))
        if artifact:
            refs.append(artifact)
        parser_metadata = self._dict_value(chunk.metadata_json.get("parser_metadata"))
        for key in ("content_list_ref", "artifact_ref"):
            value = self._coerce_string(parser_metadata.get(key))
            if value:
                refs.append(value)
        return refs

    def _warning_ids_by_chunk(self, warnings: list[WarningEvidence]) -> dict[str, list[str]]:
        output: dict[str, list[str]] = {}
        for warning in warnings:
            for chunk_id in warning.affected_chunk_ids:
                output.setdefault(chunk_id, []).append(warning.id)
        return output

    def _block_ids_by_chunk(self, blocks: list[ParserBlockEvidence]) -> dict[str, list[str]]:
        output: dict[str, list[str]] = {}
        for block in blocks:
            chunk_id = block.id.split("-block", 1)[0]
            output.setdefault(chunk_id, []).append(block.id)
        return output

    def _input_block_ids(
        self,
        chunk: Chunk,
        block_ids_by_chunk: dict[str, list[str]],
    ) -> list[str]:
        source_blocks = self._dict_value(chunk.metadata_json.get("split")).get("source_blocks")
        if isinstance(source_blocks, list):
            input_block_ids = [
                self._coerce_string(item.get("block_id"))
                for item in source_blocks
                if isinstance(item, dict)
            ]
            filtered = [item for item in input_block_ids if item is not None]
            if filtered:
                return filtered
        return list(block_ids_by_chunk.get(chunk.id, []))

    def _is_modal_chunk(self, chunk: Chunk) -> bool:
        if bool(chunk.metadata_json.get("modal_router_processed")):
            return True
        modality = self._chunk_modality(chunk)
        return modality is not None and modality != "text"

    def _sanitize_value(self, value: Any, *, context: str) -> Any:
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return value
        if isinstance(value, list):
            return [self._sanitize_value(item, context=context) for item in value]
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for key, nested in value.items():
                key_text = str(key)
                nested_context = f"{context}.{key_text}"
                if SECRET_KEY_PATTERN.search(key_text):
                    self._redactions.add(f"Redacted secret field at {nested_context}.")
                    sanitized[key_text] = "[redacted]"
                    continue
                sanitized[key_text] = self._sanitize_value(nested, context=nested_context)
            return sanitized
        if isinstance(value, Path):
            return self._sanitize_artifact_path(str(value), context=context)
        if isinstance(value, str):
            return self._sanitize_string(value, context=context)
        return self._sanitize_string(str(value), context=context)

    def _sanitize_string(self, value: str, *, context: str) -> str:
        if self._looks_like_secret(value):
            self._redactions.add(f"Redacted secret value at {context}.")
            return "[redacted]"
        if self._contains_private_host(value):
            self._redactions.add(f"Redacted private host at {context}.")
            return "[redacted]"
        if self._looks_like_absolute_path(value):
            basename = PurePath(value).name or "[redacted]"
            self._redactions.add(f"Redacted local path at {context}.")
            return basename
        return value

    def _sanitize_artifact_path(self, value: str, *, context: str) -> str:
        if self._looks_like_absolute_path(value):
            return PurePath(value).name or "[redacted]"
        sanitized = self._sanitize_string(value, context=context)
        if sanitized == "[redacted]":
            basename = PurePath(value).name
            return basename or sanitized
        return sanitized

    def _looks_like_secret(self, value: str) -> bool:
        lower = value.casefold()
        if lower.startswith("sk-"):
            return True
        if "bearer " in lower:
            return True
        return False

    def _contains_private_host(self, value: str) -> bool:
        candidate = value.strip()
        host = None
        if "://" in candidate:
            host = urlsplit(candidate).hostname
        elif re.fullmatch(r"(localhost|internal\.local)", candidate, flags=re.IGNORECASE):
            host = candidate
        elif re.fullmatch(r"\d+\.\d+\.\d+\.\d+", candidate):
            host = candidate
        if host is None:
            return False
        normalized = host.casefold()
        if normalized in {"localhost", "internal.local", "127.0.0.1", "0.0.0.0"}:
            return True
        octets = normalized.split(".")
        if len(octets) != 4 or not all(part.isdigit() for part in octets):
            return False
        first, second = int(octets[0]), int(octets[1])
        if first == 10:
            return True
        if first == 192 and second == 168:
            return True
        return first == 172 and 16 <= second <= 31

    def _looks_like_absolute_path(self, value: str) -> bool:
        return bool(WINDOWS_ABSOLUTE_PATH_PATTERN.match(value) or UNIX_ABSOLUTE_PATH_PATTERN.match(value))

    def _preview(self, text: str) -> str:
        safe_text = self._sanitize_string(text, context="text_preview")
        if len(safe_text) <= TEXT_PREVIEW_LIMIT:
            return safe_text
        hidden = len(safe_text) - TEXT_PREVIEW_LIMIT
        return f"{safe_text[:TEXT_PREVIEW_LIMIT]}...[{hidden} hidden chars]"

    def _dict_value(self, value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

    def _coerce_string(self, value: Any) -> str | None:
        return value if isinstance(value, str) and value else None

    def _page_value(self, value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        return None

    def _bbox_value(self, value: Any) -> list[float] | None:
        if not isinstance(value, list):
            return None
        bbox: list[float] = []
        for item in value:
            if isinstance(item, bool):
                return None
            if isinstance(item, (int, float)):
                bbox.append(float(item))
            else:
                return None
        return bbox
