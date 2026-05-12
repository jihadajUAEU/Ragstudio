from __future__ import annotations

import re
from typing import Any

from ragstudio.db.models import Chunk, IndexRecord, Job
from ragstudio.schemas.jobs import JobQualityWarningsOut, ParserQualityWarningOut
from ragstudio.services.domain_metadata_quality_gate import DomainMetadataQualityGate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class JobQualityWarningService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def details(
        self,
        job_id: str,
        *,
        offset: int = 0,
        limit: int = 5000,
    ) -> JobQualityWarningsOut | None:
        job = await self.session.get(Job, job_id)
        if job is None:
            return None

        result = job.result if isinstance(job.result, dict) else {}
        document_id = self._document_id(job, result)
        chunks = await self._chunks(document_id) if document_id else []
        all_items = [
            item
            for chunk in chunks
            for item in self._warning_items_for_chunk(chunk)
        ]

        parser_quality = self._dict_value(result.get("parser_quality"))
        if not parser_quality and chunks:
            parser_quality = DomainMetadataQualityGate().parser_quality_summary(chunks)

        raw_index_quality_report = result.get("index_quality_report")
        index_quality_report = (
            self._compact_index_quality_report(raw_index_quality_report)
            if isinstance(raw_index_quality_report, dict)
            else None
        )
        if index_quality_report is None and document_id:
            index_quality_report = await self._index_quality_report(document_id, chunks)

        warning_counts = self._warning_counts(all_items)
        if not warning_counts:
            warning_counts = self._parser_quality_counts(parser_quality)

        affected_chunks = self._affected_chunks(parser_quality, all_items)
        total = len(all_items)
        start = max(offset, 0)
        end = start + max(limit, 0)
        page_items = all_items[start:end]

        return JobQualityWarningsOut(
            job_id=job.id,
            document_id=document_id,
            parser_quality=parser_quality,
            index_quality_report=index_quality_report,
            job_warnings=self._job_warnings(result),
            warning_counts=warning_counts,
            affected_chunks=affected_chunks,
            total=total,
            offset=start,
            limit=limit,
            truncated=end < total,
            items=page_items,
        )

    async def _chunks(self, document_id: str) -> list[Chunk]:
        result = await self.session.execute(
            select(Chunk)
            .where(Chunk.document_id == document_id)
            .order_by(Chunk.created_at.asc(), Chunk.id.asc())
        )
        return list(result.scalars().all())

    async def _index_quality_report(
        self,
        document_id: str,
        chunks: list[Chunk],
    ) -> dict[str, Any] | None:
        record = await self.session.scalar(
            select(IndexRecord)
            .where(IndexRecord.document_id == document_id)
            .order_by(IndexRecord.created_at.desc(), IndexRecord.id.desc())
            .limit(1)
        )
        index_shape = record.index_shape if record is not None else None
        if isinstance(index_shape, dict):
            report = index_shape.get("index_quality_report")
            if isinstance(report, dict):
                return self._compact_index_quality_report(report)
        if chunks:
            return self._compact_index_quality_report(
                DomainMetadataQualityGate().index_quality_report_from_chunks(
                    chunks,
                    document_id=document_id,
                )
            )
        return None

    def _warning_items_for_chunk(self, chunk: Chunk) -> list[ParserQualityWarningOut]:
        metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
        extraction_quality = (
            chunk.extraction_quality
            if isinstance(chunk.extraction_quality, dict)
            else metadata.get("extraction_quality")
        )
        if not isinstance(extraction_quality, dict):
            return []
        parser_warnings = extraction_quality.get("parser_warnings")
        if not isinstance(parser_warnings, list):
            return []

        source_location = chunk.source_location if isinstance(chunk.source_location, dict) else {}
        parser_metadata = metadata.get("parser_metadata")
        reference_metadata = metadata.get("reference_metadata")
        return [
            ParserQualityWarningOut(
                chunk_id=chunk.id,
                chunk_preview=self._preview(chunk.text),
                source_location=dict(source_location),
                parser_metadata=self._parser_metadata_summary(parser_metadata),
                reference_metadata=dict(reference_metadata)
                if isinstance(reference_metadata, dict)
                else None,
                code=self._string_value(warning.get("code")),
                message=self._string_value(warning.get("message")),
                block_type=self._string_value(warning.get("block_type")),
                page=self._page_value(
                    warning.get("page")
                    if warning.get("page") is not None
                    else source_location.get("page")
                ),
                warning=dict(warning),
            )
            for warning in parser_warnings
            if isinstance(warning, dict)
        ]

    def _document_id(self, job: Job, result: dict[str, Any]) -> str | None:
        if isinstance(job.target_id, str) and job.target_id:
            return job.target_id
        document_id = result.get("document_id")
        return document_id if isinstance(document_id, str) and document_id else None

    def _job_warnings(self, result: dict[str, Any]) -> list[str]:
        warnings = result.get("warnings")
        if not isinstance(warnings, list):
            return []
        return [warning for warning in warnings if isinstance(warning, str)]

    def _parser_quality_counts(self, parser_quality: dict[str, Any]) -> dict[str, int]:
        warning_counts = parser_quality.get("warning_counts")
        if not isinstance(warning_counts, dict):
            return {}
        return {
            code: count
            for code, count in warning_counts.items()
            if isinstance(code, str) and isinstance(count, int)
        }

    def _warning_counts(
        self,
        items: list[ParserQualityWarningOut],
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            if item.code:
                counts[item.code] = counts.get(item.code, 0) + 1
        return dict(sorted(counts.items()))

    def _affected_chunks(
        self,
        parser_quality: dict[str, Any],
        items: list[ParserQualityWarningOut],
    ) -> int:
        affected = parser_quality.get("affected_chunks")
        if isinstance(affected, int):
            return affected
        return len({item.chunk_id for item in items})

    def _dict_value(self, value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

    def _compact_index_quality_report(self, report: dict[str, Any]) -> dict[str, Any]:
        compact = {
            key: report[key]
            for key in (
                "quality_report_version",
                "status",
                "domain_profile",
                "document_id",
                "runtime_profile_id",
                "summary",
            )
            if key in report
        }
        references = report.get("references")
        if isinstance(references, list):
            warning_references = [
                reference
                for reference in references
                if isinstance(reference, dict) and self._is_warning_reference(reference)
            ]
            compact["warning_reference_count"] = len(warning_references)
            compact["warning_references"] = warning_references[:200]
            compact["warning_references_truncated"] = len(warning_references) > 200
        unresolved = report.get("unresolved")
        if isinstance(unresolved, list):
            compact["unresolved_count"] = len(unresolved)
            compact["unresolved"] = unresolved[:200]
            compact["unresolved_truncated"] = len(unresolved) > 200
        return compact

    def _is_warning_reference(self, reference: dict[str, Any]) -> bool:
        status = reference.get("status")
        if isinstance(status, str) and status not in {"passed", "quality_unknown"}:
            return True
        action = reference.get("action")
        if isinstance(action, str) and action.startswith("block_"):
            return True
        for key in ("quality_flags", "missing_scripts", "parser_warning_codes"):
            value = reference.get(key)
            if isinstance(value, list) and value:
                return True
        return False

    def _string_value(self, value: Any) -> str | None:
        return value if isinstance(value, str) and value else None

    def _page_value(self, value: Any) -> int | str | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _parser_metadata_summary(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        allowed_keys = {
            "artifact_ref",
            "backend",
            "chunk_index",
            "content_list_ref",
            "document_id",
            "parse_method",
            "parser",
            "parser_mode",
            "split_index",
            "split_profile",
            "split_strategy",
        }
        return {key: value[key] for key in sorted(allowed_keys) if key in value}

    def _preview(self, text: str) -> str:
        compact = re.sub(r"\s+", " ", text).strip()
        if len(compact) <= 220:
            return compact
        return f"{compact[:217]}..."
