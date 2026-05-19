from __future__ import annotations

import os
import re
from ipaddress import ip_address
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

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
MAX_EVIDENCE_CHUNKS = 200
SECRET_KEY_PATTERN = re.compile(r"(api[_-]?key|token|secret|password|authorization)", re.IGNORECASE)
OPENAI_KEY_VALUE_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]+")
BEARER_VALUE_PATTERN = re.compile(r"bearer\s+[A-Za-z0-9._=-]{12,}", re.IGNORECASE)
URL_PATTERN = re.compile(r"https?://(?:\[[^\]\s]+\]|[^\s\"'\]]+)(?::\d+)?[^\s\"']*", re.IGNORECASE)
WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(r"[A-Za-z]:[\\/][^\s\"']+")
UNIX_ABSOLUTE_PATH_PATTERN = re.compile(r"(?<![:\w])/(?:[^\s\"'\\]+(?:/[^\s\"'\\]+)*)")
UNC_PATH_PATTERN = re.compile(r"\\\\[^\s\\/:*?\"<>|]+\\[^\s\"']+")


class DocumentParseEvidenceNotFoundError(LookupError):
    pass


class DocumentParseEvidenceService:
    def __init__(self, session: AsyncSession, *, source_commit: str | None = None) -> None:
        self.session = session
        self._redactions: set[str] = set()
        self._source_commit = self._normalized_source_commit(source_commit)

    async def get_document_evidence(self, document_id: str) -> DocumentParseEvidence:
        document = await self.session.get(Document, document_id)
        if document is None:
            raise DocumentParseEvidenceNotFoundError(document_id)

        all_chunks = list(
            (
                await self.session.execute(
                    select(Chunk)
                    .where(Chunk.document_id == document_id)
                    .order_by(Chunk.created_at.asc(), Chunk.id.asc())
                    .limit(MAX_EVIDENCE_CHUNKS + 1)
                )
            )
            .scalars()
            .all()
        )
        chunks = all_chunks[:MAX_EVIDENCE_CHUNKS]
        omitted_chunk_count = max(len(all_chunks) - MAX_EVIDENCE_CHUNKS, 0)
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
                    .order_by(
                        GraphProjectionRecord.created_at.desc(), GraphProjectionRecord.id.desc()
                    )
                )
            )
            .scalars()
            .all()
        )

        warnings = self._build_warnings(chunks)
        warning_ids_by_chunk = self._warning_ids_by_chunk(warnings)
        parser_blocks = self._build_parser_blocks(chunks)
        block_ids_by_chunk = self._parser_block_ids_by_chunk(chunks, parser_blocks)
        decisions = self._build_decisions(
            chunks, graph_records, warning_ids_by_chunk, block_ids_by_chunk
        )
        warnings = self._attach_warning_links(
            warnings, parser_blocks, block_ids_by_chunk, decisions
        )
        parser_blocks = self._attach_block_warning_ids(parser_blocks, warnings)
        chunk_evidence = self._build_chunks(chunks, warning_ids_by_chunk)
        source_artifacts = self._build_source_artifacts(document, chunks)
        limitations = self._proof_limitations(chunks, graph_records, omitted_chunk_count)
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
                source_commit=self._source_commit,
                proof_packet_id="local-document-parse-evidence",
                mode="local",
                replay_command="./scripts/proof.sh --fixtures static-fixtures",
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
                warning_payload = self._dict_value(item.get("warning"))
                quality_gate_action = self._coerce_string(
                    warning_payload.get("quality_gate_action") or item.get("quality_gate_action")
                )
                suppressed_from_counts = bool(
                    warning_payload.get("suppressed_from_counts")
                    or item.get("suppressed_from_counts")
                )
                block_type = self._coerce_string(
                    item.get("block_type") or warning_payload.get("block_type")
                )
                warnings.append(
                    WarningEvidence(
                        id=f"warning-{chunk.id}-{index}",
                        code=code,
                        message=self._sanitize_string(
                            message, context=f"warning:{chunk.id}:{code}"
                        ),
                        severity=self._coerce_string(item.get("severity")) or "warning",
                        page=self._page_value(item.get("page"))
                        or self._page_value(chunk.source_location.get("page")),
                        block_id=self._coerce_string(item.get("block_id")),
                        block_type=block_type,
                        quality_gate_action=quality_gate_action,
                        suppressed_from_counts=suppressed_from_counts,
                        affected_chunk_ids=[chunk.id],
                    )
                )
        return warnings

    def _build_parser_blocks(
        self,
        chunks: list[Chunk],
    ) -> list[ParserBlockEvidence]:
        blocks: list[ParserBlockEvidence] = []
        seen_ids: set[str] = set()
        for chunk in chunks:
            source_blocks = self._dict_value(chunk.metadata_json.get("split")).get("source_blocks")
            if isinstance(source_blocks, list) and source_blocks:
                for fallback_index, item in enumerate(source_blocks):
                    if not isinstance(item, dict):
                        continue
                    block_id = (
                        self._coerce_string(item.get("block_id"))
                        or f"{chunk.id}-block-{fallback_index}"
                    )
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
                            f"Chunk spans pages {page_start} to {page_end} after joining "
                            "parser blocks into one normalized unit."
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
                            f"Chunk was preserved as {self._chunk_modality(chunk)} content "
                            "during parser normalization."
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
            decision_type = (
                "chunk_materialization" if latest_graph.status == "succeeded" else "quality_gate"
            )
            title = (
                "Chunk materialization"
                if decision_type == "chunk_materialization"
                else "Quality gate"
            )
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

    def _attach_warning_links(
        self,
        warnings: list[WarningEvidence],
        parser_blocks: list[ParserBlockEvidence],
        block_ids_by_chunk: dict[str, list[str]],
        decisions: list[NormalizationDecisionEvidence],
    ) -> list[WarningEvidence]:
        block_by_id = {block.id: block for block in parser_blocks}
        quality_decisions = {
            chunk_id: decision.id
            for decision in decisions
            if decision.decision_type == "quality_warning"
            for chunk_id in decision.output_chunk_ids
        }
        updated: list[WarningEvidence] = []
        for warning in warnings:
            block_id = self._warning_block_id(warning, block_ids_by_chunk, block_by_id)
            decision_id = next(
                (
                    quality_decisions.get(chunk_id)
                    for chunk_id in warning.affected_chunk_ids
                    if quality_decisions.get(chunk_id)
                ),
                None,
            )
            updated.append(
                warning.model_copy(
                    update={
                        "block_id": block_id,
                        "decision_id": decision_id,
                    }
                )
            )
        return updated

    def _attach_block_warning_ids(
        self,
        parser_blocks: list[ParserBlockEvidence],
        warnings: list[WarningEvidence],
    ) -> list[ParserBlockEvidence]:
        warning_ids_by_block: dict[str, list[str]] = {}
        for warning in warnings:
            if warning.block_id:
                warning_ids_by_block.setdefault(warning.block_id, []).append(warning.id)
        return [
            block.model_copy(update={"warning_ids": list(warning_ids_by_block.get(block.id, []))})
            for block in parser_blocks
        ]

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
        document_path = self._sanitize_artifact_path(
            document.artifact_path, context="document.artifact_path"
        )
        artifacts["document"] = SourceArtifactEvidence(
            id="document",
            kind="upload",
            path=document_path,
            checksum=document.sha256,
            preview_available=False,
        )
        for chunk in chunks:
            for raw_artifact in self._artifact_refs(chunk):
                safe_path = self._sanitize_artifact_path(
                    raw_artifact, context=f"chunk:{chunk.id}:artifact"
                )
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
        omitted_chunk_count: int = 0,
    ) -> list[str]:
        limitations: list[str] = []
        if not chunks:
            limitations.append("No chunks have been materialized for this document.")
        if omitted_chunk_count:
            limitations.append(
                "Evidence preview is capped at "
                f"{MAX_EVIDENCE_CHUNKS} chunks; at least {omitted_chunk_count} "
                "additional chunks are omitted from this response."
            )
        if not graph_records:
            limitations.append("No graph projection record is available for this document.")
        elif graph_records[0].status != "succeeded":
            limitations.append(
                f"Latest graph projection status is {graph_records[0].status}; "
                "graph-backed proof is incomplete."
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
        pages: set[int] = set()
        for chunk in chunks:
            page_start, page_end = self._chunk_pages(chunk)
            if page_start is not None and page_end is not None and page_end >= page_start:
                pages.update(range(page_start, page_end + 1))
                continue
            if page_start is not None:
                pages.add(page_start)
            if page_end is not None:
                pages.add(page_end)
        return len(pages) if pages else None

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

    def _parser_block_ids_by_chunk(
        self,
        chunks: list[Chunk],
        parser_blocks: list[ParserBlockEvidence],
    ) -> dict[str, list[str]]:
        generated_block_ids_by_chunk = self._block_ids_by_chunk(parser_blocks)
        return {
            chunk.id: self._input_block_ids(chunk, generated_block_ids_by_chunk) for chunk in chunks
        }

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

    def _warning_block_id(
        self,
        warning: WarningEvidence,
        block_ids_by_chunk: dict[str, list[str]],
        block_by_id: dict[str, ParserBlockEvidence],
    ) -> str | None:
        if warning.block_id and warning.block_id in block_by_id:
            return warning.block_id

        chunk_block_ids = [
            block_id
            for chunk_id in warning.affected_chunk_ids
            for block_id in block_ids_by_chunk.get(chunk_id, [])
            if block_id in block_by_id
        ]
        if not chunk_block_ids:
            return warning.block_id
        if warning.page is not None:
            page_matches = [
                block_id
                for block_id in chunk_block_ids
                if block_by_id[block_id].page == warning.page
            ]
            if page_matches:
                return page_matches[0]
        if len(chunk_block_ids) == 1:
            return chunk_block_ids[0]
        return warning.block_id

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
        sanitized, protected_urls = self._protect_urls(value, context=context)
        sanitized = self._replace_pattern(
            sanitized,
            pattern=OPENAI_KEY_VALUE_PATTERN,
            context=context,
            redaction_kind="secret value",
            replacement_factory=lambda _match: "[redacted]",
        )
        sanitized = self._replace_pattern(
            sanitized,
            pattern=BEARER_VALUE_PATTERN,
            context=context,
            redaction_kind="secret value",
            replacement_factory=lambda _match: "[redacted]",
        )
        sanitized = self._replace_private_urls(sanitized, context=context)
        sanitized = self._replace_pattern(
            sanitized,
            pattern=UNC_PATH_PATTERN,
            context=context,
            redaction_kind="local path",
            replacement_factory=self._path_replacement,
        )
        sanitized = self._replace_pattern(
            sanitized,
            pattern=WINDOWS_ABSOLUTE_PATH_PATTERN,
            context=context,
            redaction_kind="local path",
            replacement_factory=self._path_replacement,
        )
        sanitized = self._replace_pattern(
            sanitized,
            pattern=UNIX_ABSOLUTE_PATH_PATTERN,
            context=context,
            redaction_kind="local path",
            replacement_factory=self._path_replacement,
        )
        for placeholder, safe_url in protected_urls.items():
            sanitized = sanitized.replace(placeholder, safe_url)
        return sanitized

    def _sanitize_artifact_path(self, value: str, *, context: str) -> str:
        if self._is_absolute_path(value):
            self._record_redaction("local path", context)
            return self._sanitize_artifact_basename(self._path_basename(value), context=context)
        sanitized = self._sanitize_string(value, context=context)
        if sanitized == "[redacted]":
            basename = self._path_basename(value)
            return self._sanitize_artifact_basename(basename, context=context)
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
        elif re.fullmatch(r"\[[0-9A-Fa-f:]+\]", candidate):
            host = candidate[1:-1]
        elif re.fullmatch(r"\d+\.\d+\.\d+\.\d+", candidate):
            host = candidate
        if host is None:
            return False
        normalized = host.casefold().strip("[]")
        if normalized in {"localhost", "internal.local", "127.0.0.1", "0.0.0.0", "::1"}:
            return True
        try:
            parsed = ip_address(normalized)
        except ValueError:
            return False
        return parsed.is_loopback or parsed.is_private or parsed.is_link_local

    def _is_absolute_path(self, value: str) -> bool:
        return (
            value.startswith("/")
            or value.startswith("\\\\")
            or bool(re.fullmatch(r"[A-Za-z]:[\\/].*", value))
        )

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

    def _replace_private_urls(self, value: str, *, context: str) -> str:
        def _replace(match: re.Match[str]) -> str:
            candidate = match.group(0)
            if self._contains_private_host(candidate):
                self._record_redaction("private host", context)
                return "[redacted]"
            return candidate

        return URL_PATTERN.sub(_replace, value)

    def _protect_urls(self, value: str, *, context: str) -> tuple[str, dict[str, str]]:
        protected_urls: dict[str, str] = {}
        parts: list[str] = []
        last_index = 0
        for index, match in enumerate(URL_PATTERN.finditer(value)):
            parts.append(value[last_index : match.start()])
            candidate = match.group(0)
            if self._contains_private_host(candidate):
                self._record_redaction("private host", context)
                parts.append("[redacted]")
            else:
                placeholder = f"__RAGSTUDIO_SAFE_URL_{index}__"
                protected_urls[placeholder] = self._sanitize_public_url(candidate, context=context)
                parts.append(placeholder)
            last_index = match.end()
        parts.append(value[last_index:])
        return "".join(parts), protected_urls

    def _sanitize_public_url(self, value: str, *, context: str) -> str:
        split = urlsplit(value)
        netloc = split.netloc
        if split.username is not None or split.password is not None:
            self._record_redaction("secret value", f"{context}.userinfo")
            hostname = split.hostname or ""
            if ":" in hostname and not hostname.startswith("["):
                hostname = f"[{hostname}]"
            port_value = self._safe_port(split)
            port = f":{port_value}" if port_value is not None else ""
            netloc = f"{hostname}{port}"
        elif self._has_malformed_port(split):
            netloc = self._sanitize_malformed_netloc(split, context=context)

        path = self._sanitize_public_url_path(split.path, context=context)

        sanitized_query: list[tuple[str, str]] = []
        for key, raw_value in parse_qsl(split.query, keep_blank_values=True):
            if SECRET_KEY_PATTERN.search(key) or self._looks_like_secret(raw_value):
                self._record_redaction("secret value", f"{context}.query.{key}")
                sanitized_query.append((key, "[redacted]"))
            else:
                sanitized_query.append((key, raw_value))

        fragment = split.fragment
        if fragment:
            fragment_pairs = parse_qsl(fragment, keep_blank_values=True)
            if fragment_pairs:
                sanitized_fragment_pairs: list[tuple[str, str]] = []
                for key, raw_value in fragment_pairs:
                    if SECRET_KEY_PATTERN.search(key) or self._looks_like_secret(raw_value):
                        self._record_redaction("secret value", f"{context}.fragment.{key}")
                        sanitized_fragment_pairs.append((key, "[redacted]"))
                    else:
                        sanitized_fragment_pairs.append((key, raw_value))
                fragment = urlencode(sanitized_fragment_pairs, doseq=True)
            elif self._looks_like_secret(fragment) or "bearer " in fragment.casefold():
                self._record_redaction("secret value", f"{context}.fragment")
                fragment = "[redacted]"

        query = urlencode(sanitized_query, doseq=True)
        return urlunsplit((split.scheme, netloc, path, query, fragment))

    def _replace_pattern(
        self,
        value: str,
        *,
        pattern: re.Pattern[str],
        context: str,
        redaction_kind: str,
        replacement_factory: Any,
    ) -> str:
        def _replace(match: re.Match[str]) -> str:
            self._record_redaction(redaction_kind, context)
            return replacement_factory(match)

        return pattern.sub(_replace, value)

    def _path_replacement(self, match: re.Match[str]) -> str:
        raw = match.group(0)
        basename = self._path_basename(raw)
        return basename or "[redacted]"

    def _path_basename(self, value: str) -> str:
        if value.startswith("\\\\") or re.fullmatch(r"[A-Za-z]:[\\/].*", value):
            return PureWindowsPath(value).name
        return PurePosixPath(value).name

    def _sanitize_artifact_basename(self, basename: str, *, context: str) -> str:
        if not basename:
            return "[redacted]"
        if self._looks_like_secret(basename):
            self._record_redaction("secret value", f"{context}.basename")
            return "[redacted]"
        sanitized = self._sanitize_string(basename, context=f"{context}.basename")
        return sanitized if sanitized != basename else basename

    def _sanitize_public_url_path(self, path: str, *, context: str) -> str:
        if not path:
            return path
        leading_slash = path.startswith("/")
        trailing_slash = path.endswith("/") and path != "/"
        segments = path.split("/")
        sanitized_segments: list[str] = []
        for index, segment in enumerate(segments):
            if segment == "":
                sanitized_segments.append("")
                continue
            decoded = unquote(segment)
            if self._looks_like_secret(decoded):
                self._record_redaction("secret value", f"{context}.path.{index}")
                sanitized_segments.append("[redacted-secret]")
            else:
                sanitized_segments.append(segment)
        sanitized_path = "/".join(sanitized_segments)
        if leading_slash and not sanitized_path.startswith("/"):
            sanitized_path = f"/{sanitized_path}"
        if trailing_slash and not sanitized_path.endswith("/"):
            sanitized_path = f"{sanitized_path}/"
        return sanitized_path

    def _safe_port(self, split_result: Any) -> int | None:
        try:
            return split_result.port
        except ValueError:
            return None

    def _has_malformed_port(self, split_result: Any) -> bool:
        try:
            _ = split_result.port
        except ValueError:
            return True
        return False

    def _sanitize_malformed_netloc(self, split_result: Any, *, context: str) -> str:
        self._record_redaction("malformed url", f"{context}.port")
        netloc = split_result.netloc
        if "@" in netloc:
            self._record_redaction("secret value", f"{context}.userinfo")
            netloc = netloc.rsplit("@", 1)[-1]
        if "/" in netloc:
            netloc = netloc.split("/", 1)[0]
        if netloc.count(":") > 1 and not netloc.startswith("["):
            return netloc
        if ":" in netloc:
            host_candidate, port_candidate = netloc.rsplit(":", 1)
            if host_candidate and not port_candidate.isdigit():
                return host_candidate
        return netloc or "[redacted-url]"

    def _record_redaction(self, redaction_kind: str, context: str) -> None:
        self._redactions.add(f"Redacted {redaction_kind} at {context}.")

    def _normalized_source_commit(self, source_commit: str | None) -> str | None:
        candidate = (
            source_commit if source_commit is not None else os.getenv("RAGSTUDIO_SOURCE_COMMIT")
        )
        if candidate is None:
            return None
        stripped = candidate.strip()
        return stripped or None
