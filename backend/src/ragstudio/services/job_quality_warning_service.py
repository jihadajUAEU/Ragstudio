from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError
from ragstudio.config import AppSettings
from ragstudio.db.models import Chunk, IndexRecord, Job
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.jobs import (
    JobQualityWarningRepairOut,
    JobQualityWarningsOut,
    ParserQualityWarningOut,
)
from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn
from ragstudio.services.document_service import ActiveIndexJobError, DocumentService
from ragstudio.services.domain_metadata_quality_gate import DomainMetadataQualityGate
from ragstudio.services.runtime_profile_service import (
    RuntimeProfileNotConfiguredError,
    RuntimeProfileService,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class JobQualityWarningRepairDocumentNotFound(RuntimeError):
    pass


class JobQualityWarningRepairUnavailable(RuntimeError):
    pass


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

    async def queue_repair_job(
        self,
        job_id: str,
        *,
        data_dir: Path,
        settings: AppSettings | None = None,
    ) -> JobQualityWarningRepairOut | None:
        job = await self.session.get(Job, job_id)
        if job is None:
            return None
        if job.type != "index_document":
            raise JobQualityWarningRepairUnavailable(
                "Only completed index jobs can queue parser warning repair."
            )
        if job.status != StageStatus.SUCCEEDED.value:
            raise JobQualityWarningRepairUnavailable(
                "Parser warning repair can only be queued after the index job completes."
            )

        result = job.result if isinstance(job.result, dict) else {}
        document_id = self._document_id(job, result)
        if document_id is None:
            raise JobQualityWarningRepairUnavailable(
                "Parser warning repair requires an indexed document."
            )

        options = await self._stored_index_options(job, result, document_id)
        chunks = await self._chunks(document_id)
        warning_items = [
            item
            for chunk in chunks
            for item in self._warning_items_for_chunk(chunk)
        ]
        parser_quality = self._dict_value(result.get("parser_quality"))
        if not parser_quality and chunks:
            parser_quality = DomainMetadataQualityGate().parser_quality_summary(chunks)
        index_quality_report = self._repair_index_quality_report(result, document_id, chunks)
        if index_quality_report is None:
            index_quality_report = await self._index_quality_report(document_id, chunks)
        repair_plan = self._repair_plan(
            warning_items,
            parser_quality=parser_quality,
            index_quality_report=index_quality_report,
            options=options,
            source_job_id=job.id,
            document_id=document_id,
        )
        repair_plan["ai_suggestion"] = await self._ai_repair_suggestion(
            repair_plan,
            options=options,
            settings=settings,
        )
        options = self._options_with_repair_plan(options, repair_plan)
        document_service = DocumentService(self.session, data_dir, settings=settings)
        try:
            queued_job = await document_service.create_index_job(document_id, options)
        except ActiveIndexJobError as exc:
            raise JobQualityWarningRepairUnavailable(str(exc)) from exc
        if queued_job is None:
            raise JobQualityWarningRepairDocumentNotFound("Document not found")

        index_options = options.model_dump(mode="json", exclude_none=True)
        return JobQualityWarningRepairOut(
            source_job_id=job.id,
            document_id=document_id,
            queued_job_id=queued_job.id,
            queued_job_status=StageStatus(queued_job.status),
            index_options=index_options,
            repair_plan=repair_plan,
            message=(
                "Generated a metadata-aware repair plan and queued a strict reindex job. "
                "Existing warnings remain visible until the new job completes."
            ),
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

    async def _stored_index_options(
        self,
        job: Job,
        result: dict[str, Any],
        document_id: str,
    ) -> IndexDocumentIn:
        raw_options = self._dict_value(job.job_options)
        if not raw_options:
            raw_options = self._dict_value(result.get("index_options"))
        if raw_options:
            return self._validate_index_options(raw_options)

        inferred_options = await self._latest_index_options_from_chunk_metadata(document_id)
        if inferred_options is not None:
            return inferred_options
        return IndexDocumentIn()

    async def _latest_index_options_from_chunk_metadata(
        self,
        document_id: str,
    ) -> IndexDocumentIn | None:
        metadata = await self.session.scalar(
            select(Chunk.metadata_json)
            .where(Chunk.document_id == document_id)
            .order_by(Chunk.created_at.desc(), Chunk.id.desc())
            .limit(1)
        )
        if not isinstance(metadata, dict):
            return None

        parser_metadata = metadata.get("parser_metadata")
        parser_mode = self._parser_mode_from_metadata(parser_metadata)
        if parser_mode is None:
            return None

        domain_metadata = metadata.get("domain_metadata")
        try:
            metadata_model = (
                DomainMetadata.model_validate(domain_metadata)
                if isinstance(domain_metadata, dict)
                else DomainMetadata()
            )
        except ValidationError:
            metadata_model = DomainMetadata()
        return IndexDocumentIn(parser_mode=parser_mode, domain_metadata=metadata_model)

    def _parser_mode_from_metadata(self, value: Any) -> str | None:
        if not isinstance(value, dict):
            return None
        parser_mode = value.get("parser_mode")
        if parser_mode == "mineru_strict":
            return parser_mode
        backend = value.get("backend")
        if backend == "mineru":
            return "mineru_strict"
        return None

    def _validate_index_options(self, raw_options: dict[str, Any]) -> IndexDocumentIn:
        try:
            return IndexDocumentIn.model_validate(raw_options)
        except ValidationError as exc:
            raise JobQualityWarningRepairUnavailable(
                "Stored index options are invalid; cannot queue automatic parser warning repair."
            ) from exc

    def _repair_index_quality_report(
        self,
        result: dict[str, Any],
        document_id: str,
        chunks: list[Chunk],
    ) -> dict[str, Any] | None:
        raw_index_quality_report = result.get("index_quality_report")
        if isinstance(raw_index_quality_report, dict):
            return self._compact_index_quality_report(raw_index_quality_report)
        if chunks:
            return self._compact_index_quality_report(
                DomainMetadataQualityGate().index_quality_report_from_chunks(
                    chunks,
                    document_id=document_id,
                )
            )
        return None

    def _repair_plan(
        self,
        items: list[ParserQualityWarningOut],
        *,
        parser_quality: dict[str, Any],
        index_quality_report: dict[str, Any] | None,
        options: IndexDocumentIn,
        source_job_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        warning_counts = self._repair_warning_counts(items, parser_quality, index_quality_report)
        affected_chunks = self._affected_chunks(parser_quality, items)
        if affected_chunks == 0 and warning_counts:
            affected_chunks = sum(warning_counts.values())
        steps = [
            step
            for step in (
                self._missing_expected_script_step(
                    items,
                    warning_counts,
                    options.domain_metadata,
                ),
                self._blocked_reference_step(index_quality_report, warning_counts),
                self._unresolved_reference_step(items, warning_counts),
                self._quarantined_block_step(items, warning_counts),
            )
            if step is not None
        ]
        metadata_patch = self._repair_metadata_patch(steps)
        return {
            "version": 1,
            "strategy": "metadata_aware_warning_repair",
            "source_job_id": source_job_id,
            "document_id": document_id,
            "summary": self._repair_plan_summary(steps),
            "warning_counts": warning_counts,
            "affected_chunks": affected_chunks,
            "index_quality_summary": self._dict_value(
                index_quality_report.get("summary") if index_quality_report else None
            ),
            "sample_references": self._plan_sample_values(steps, "references"),
            "sample_pages": self._plan_sample_values(steps, "page"),
            "sample_chunk_previews": self._plan_sample_values(steps, "preview"),
            "metadata_patch": metadata_patch,
            "steps": steps,
        }

    def _repair_warning_counts(
        self,
        items: list[ParserQualityWarningOut],
        parser_quality: dict[str, Any],
        index_quality_report: dict[str, Any] | None,
    ) -> dict[str, int]:
        counts = self._warning_counts(items)
        for source_counts in (
            self._parser_quality_counts(parser_quality),
            self._index_quality_warning_counts(index_quality_report),
        ):
            for code, count in source_counts.items():
                if count > 0:
                    counts[code] = max(counts.get(code, 0), count)
        return dict(sorted(counts.items()))

    def _index_quality_warning_counts(
        self,
        index_quality_report: dict[str, Any] | None,
    ) -> dict[str, int]:
        if not isinstance(index_quality_report, dict):
            return {}
        summary = index_quality_report.get("summary")
        if not isinstance(summary, dict):
            return {}

        counts: dict[str, int] = {}
        missing_expected_script = summary.get("reference_units_missing_expected_script")
        if isinstance(missing_expected_script, int) and missing_expected_script > 0:
            counts["reference_unit_missing_expected_script"] = missing_expected_script

        unresolved = summary.get("reference_unit_unresolved_count")
        if isinstance(unresolved, int) and unresolved > 0:
            counts["reference_unit_unresolved"] = unresolved

        blocked = summary.get("materialization_blocked_reference_count")
        if isinstance(blocked, int) and blocked > 0:
            counts["reference_materialization_blocked"] = blocked
        return counts

    def _missing_expected_script_step(
        self,
        items: list[ParserQualityWarningOut],
        counts: dict[str, int],
        domain_metadata: DomainMetadata,
    ) -> dict[str, Any] | None:
        count = counts.get("reference_unit_missing_expected_script")
        if not count:
            return None
        matching = [
            item
            for item in items
            if item.code == "reference_unit_missing_expected_script"
        ]
        expected_scripts = {
            script
            for item in matching
            for script in [self._string_value(item.warning.get("expected_script"))]
            if script
        }
        expected_scripts.update(
            DomainMetadataQualityGate().profile_for(domain_metadata).expected_scripts
        )
        if not expected_scripts:
            expected_scripts.add("arabic")
        return {
            "code": "reference_unit_missing_expected_script",
            "count": count,
            "reason": (
                "Reference metadata says these units should include the expected script, "
                "but the persisted chunk text does not contain those letters."
            ),
            "action": "preserve_parallel_reference_units",
            "metadata_patch": {
                "repair": {
                    "reference_unit_missing_expected_script": {
                        "action": "preserve_parallel_reference_units",
                        "preserve_parallel_text": True,
                        "expected_scripts": sorted(expected_scripts),
                        "carry_reference_headers_into_body": True,
                    }
                },
                "chunking": {
                    "preserve_parallel_text": True,
                    "merge_reference_header_with_body": True,
                },
            },
            "expected_effect": (
                "Arabic/English pairs stay in one reference unit so exact Arabic search and "
                "graph materialization are not blocked only because the reference chunk was split."
            ),
            "samples": self._warning_samples(matching),
        }

    def _blocked_reference_step(
        self,
        index_quality_report: dict[str, Any] | None,
        counts: dict[str, int],
    ) -> dict[str, Any] | None:
        count = counts.get("reference_materialization_blocked")
        if not count:
            return None
        blocked_references = self._blocked_reference_samples(index_quality_report)
        missing_scripts = sorted(
            {
                script
                for reference in blocked_references
                for script in reference.get("missing_scripts", [])
                if isinstance(script, str) and script
            }
        )
        return {
            "code": "reference_materialization_blocked",
            "count": count,
            "reason": (
                "The index quality gate blocked some references from vector indexing and graph "
                "projection because the reference text did not satisfy the domain metadata "
                "contract."
            ),
            "action": "unblock_reference_materialization_after_metadata_repair",
            "metadata_patch": {
                "repair": {
                    "reference_materialization_blocked": {
                        "action": (
                            "unblock_reference_materialization_after_metadata_repair"
                        ),
                        "retry_after_reference_quality_repair": True,
                        "missing_scripts": missing_scripts,
                    }
                },
                "graph_materialization": {
                    "retry_blocked_references_after_quality_repair": True,
                },
            },
            "expected_effect": (
                "Once the missing script and reference-continuation fixes run, previously blocked "
                "references are allowed back into vector search and graph projection."
            ),
            "samples": blocked_references,
        }

    def _unresolved_reference_step(
        self,
        items: list[ParserQualityWarningOut],
        counts: dict[str, int],
    ) -> dict[str, Any] | None:
        count = counts.get("reference_unit_unresolved")
        if not count:
            return None
        matching = [item for item in items if item.code == "reference_unit_unresolved"]
        return {
            "code": "reference_unit_unresolved",
            "count": count,
            "reason": (
                "Some chunks are prose continuations, titles, or front matter that could not be "
                "attached to exactly one book/hadith reference."
            ),
            "action": "mark_non_reference_chunks_and_carry_forward_references",
            "metadata_patch": {
                "repair": {
                    "reference_unit_unresolved": {
                        "action": (
                            "mark_non_reference_chunks_and_carry_forward_references"
                        ),
                        "carry_forward_previous_reference": True,
                        "continuation_reference_carry_forward": True,
                        "mark_title_front_matter_non_reference_chunks": True,
                        "mark_non_reference_blocks": [
                            "title",
                            "front_matter",
                            "non_reference",
                        ],
                    }
                },
                "reference_resolution": {
                    "carry_forward_previous_reference": True,
                    "continuation_reference_carry_forward": True,
                    "mark_title_front_matter_non_reference_chunks": True,
                },
            },
            "expected_effect": (
                "Continuation chunks inherit the nearest valid reference, while true title/front "
                "matter chunks stop being counted as broken references."
            ),
            "samples": self._warning_samples(matching),
        }

    def _quarantined_block_step(
        self,
        items: list[ParserQualityWarningOut],
        counts: dict[str, int],
    ) -> dict[str, Any] | None:
        count = counts.get("disallowed_block_type_quarantined")
        if not count:
            return None
        matching = [item for item in items if item.code == "disallowed_block_type_quarantined"]
        block_types = sorted({item.block_type for item in matching if item.block_type})
        return {
            "code": "disallowed_block_type_quarantined",
            "count": count,
            "reason": (
                "MinerU emitted text-bearing blocks with types that the current content profile "
                "does not trust as prose."
            ),
            "action": "recover_text_bearing_blocks_as_prose",
            "metadata_patch": {
                "repair": {
                    "disallowed_block_type_quarantined": {
                        "action": "recover_text_bearing_blocks_as_prose",
                        "block_types": block_types,
                        "only_when_text_bearing": True,
                    }
                },
                "parser_normalization": {
                    "recover_text_bearing_blocks_as_prose": True,
                    "preserve_original_block_type": True,
                },
            },
            "expected_effect": (
                "Real Arabic/Hadith text misclassified as another block type can be indexed as "
                "prose, while non-text parser artifacts remain quarantined."
            ),
            "samples": self._warning_samples(matching),
        }

    def _repair_metadata_patch(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        patch: dict[str, Any] = {
            "repair": {
                "strategy": "metadata_aware_warning_repair",
                "applied_at": "reindex_time",
            }
        }
        for step in steps:
            step_patch = step.get("metadata_patch")
            if isinstance(step_patch, dict):
                patch = self._deep_merge(patch, step_patch)
        if any(
            step.get("code")
            in {
                "reference_unit_missing_expected_script",
                "reference_materialization_blocked",
                "reference_unit_unresolved",
            }
            for step in steps
        ):
            patch = self._deep_merge(patch, self._canonical_reference_metadata_patch())
        return patch

    def _canonical_reference_metadata_patch(self) -> dict[str, Any]:
        return {
            "chunking": {
                "preserve_parallel_text": True,
                "merge_reference_header_with_body": True,
            },
            "reference_resolution": {
                "enabled": True,
                "build_canonical_units": True,
                "carry_forward_body_blocks": True,
                "header_only_policy": "provenance_only",
                "continuation_policy": "until_next_reference",
                "max_page_gap": 2,
                "require_single_reference_per_answerable_chunk": True,
            },
            "provenance": {
                "preserve_original_blocks": True,
                "block_preview_chars": 160,
                "store_text_hash": True,
            },
        }

    def _repair_plan_summary(self, steps: list[dict[str, Any]]) -> str:
        if not steps:
            return (
                "No parser warning groups were found, so the repair reindex will only refresh "
                "the existing metadata contract."
            )
        actions = ", ".join(str(step["action"]) for step in steps if step.get("action"))
        return f"Apply metadata-aware fixes before reindex: {actions}."

    def _plan_sample_values(self, steps: list[dict[str, Any]], key: str) -> list[Any]:
        values: list[Any] = []
        for step in steps:
            samples = step.get("samples")
            if not isinstance(samples, list):
                continue
            for sample in samples:
                if not isinstance(sample, dict):
                    continue
                value = sample.get(key)
                if key == "references" and isinstance(value, list):
                    for reference in value:
                        self._append_unique_sample_value(values, reference)
                    continue
                self._append_unique_sample_value(values, value)
        return values

    def _append_unique_sample_value(self, values: list[Any], value: Any) -> None:
        if value is None or value in values or len(values) >= 5:
            return
        values.append(value)

    def _warning_samples(
        self,
        items: list[ParserQualityWarningOut],
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        samples: list[dict[str, Any]] = []
        for item in items[:limit]:
            samples.append(
                {
                    "chunk_id": item.chunk_id,
                    "page": self._sample_page(item),
                    "references": self._sample_references(item),
                    "preview": item.chunk_preview,
                    "parser": item.parser_metadata,
                    "warning": item.warning,
                }
            )
        return samples

    def _sample_page(self, item: ParserQualityWarningOut) -> int | str | None:
        if item.page is not None:
            return item.page
        for key in ("page", "page_start", "page_number"):
            page = self._page_value(item.source_location.get(key))
            if page is not None:
                return page
        return None

    def _sample_references(self, item: ParserQualityWarningOut) -> list[str]:
        references: list[str] = []
        warning_reference = item.warning.get("reference")
        if isinstance(warning_reference, str) and warning_reference.strip():
            references.append(warning_reference.strip())

        metadata = item.reference_metadata if isinstance(item.reference_metadata, dict) else {}
        for key in ("reference", "display_reference"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                references.append(value.strip())
        metadata_references = metadata.get("references")
        if isinstance(metadata_references, list):
            references.extend(
                value.strip()
                for value in metadata_references
                if isinstance(value, str) and value.strip()
            )

        for key in ("reference", "display_reference"):
            value = item.source_location.get(key)
            if isinstance(value, str) and value.strip():
                references.append(value.strip())
        return list(dict.fromkeys(references))

    def _blocked_reference_samples(
        self,
        index_quality_report: dict[str, Any] | None,
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if not isinstance(index_quality_report, dict):
            return []
        references = index_quality_report.get("warning_references")
        if not isinstance(references, list):
            return []

        samples: list[dict[str, Any]] = []
        for reference in references:
            if not isinstance(reference, dict):
                continue
            action = reference.get("action")
            materialization = self._dict_value(reference.get("materialization"))
            materialization_action = materialization.get("action")
            if (
                action != "block_reference_materialization"
                and materialization_action != "block_reference_materialization"
            ):
                continue
            source_location = self._dict_value(reference.get("source_location"))
            samples.append(
                {
                    "reference": self._string_value(reference.get("reference")),
                    "references": [
                        self._string_value(reference.get("reference"))
                    ]
                    if self._string_value(reference.get("reference"))
                    else [],
                    "page": self._page_value(
                        source_location.get("page_start")
                        if source_location.get("page_start") is not None
                        else source_location.get("page")
                    ),
                    "missing_scripts": [
                        script
                        for script in reference.get("missing_scripts", [])
                        if isinstance(script, str)
                    ]
                    if isinstance(reference.get("missing_scripts"), list)
                    else [],
                    "quality_flags": [
                        flag
                        for flag in reference.get("quality_flags", [])
                        if isinstance(flag, str)
                    ]
                    if isinstance(reference.get("quality_flags"), list)
                    else [],
                    "status": self._string_value(reference.get("status")),
                    "warning": {
                        "action": action,
                        "materialization_action": materialization_action,
                    },
                }
            )
            if len(samples) >= limit:
                break
        return samples

    def _options_with_repair_plan(
        self,
        options: IndexDocumentIn,
        repair_plan: dict[str, Any],
    ) -> IndexDocumentIn:
        payload = options.model_dump(mode="json", exclude_none=True)
        domain_metadata = self._dict_value(payload.get("domain_metadata"))
        custom_json = self._dict_value(domain_metadata.get("custom_json"))
        patch = self._dict_value(repair_plan.get("metadata_patch"))
        custom_json = self._deep_merge(custom_json, patch)
        custom_json = self._with_repair_reference_schema(domain_metadata, custom_json)
        custom_json["repair_plan"] = repair_plan
        domain_metadata["custom_json"] = custom_json
        payload["domain_metadata"] = domain_metadata
        return IndexDocumentIn.model_validate(payload)

    def _with_repair_reference_schema(
        self,
        domain_metadata: dict[str, Any],
        custom_json: dict[str, Any],
    ) -> dict[str, Any]:
        if isinstance(custom_json.get("reference_schema"), dict):
            return custom_json

        tokens = self._domain_metadata_tokens(domain_metadata)
        schema: dict[str, Any] | None = None
        if (
            "book_hadith" in tokens
            or "hadith" in tokens
            or any("hadith" in token and "book" in token for token in tokens)
        ):
            schema = {
                "type": "book_hadith",
                "display": "Book {book}, Hadith {hadith}",
                "canonical_ref_template": "book:{book}:hadith:{hadith}",
                "fields": {
                    "book": "book_number",
                    "hadith": "hadith_number",
                    "chapter": "chapter_title",
                },
            }
        elif (
            "surah_ayah" in tokens
            or "chapter_verse" in tokens
            or "quran" in tokens
            or any("quran" in token for token in tokens)
        ):
            schema = {
                "type": "chapter_verse",
                "display": "{chapter}:{verse}",
                "canonical_ref_template": "{chapter}:{verse}",
                "fields": {
                    "chapter": "surah_number",
                    "verse": "ayah_number",
                    "page": "page_number",
                },
            }
        if schema is None:
            return custom_json
        repaired = dict(custom_json)
        repaired["reference_schema"] = schema
        return repaired

    def _domain_metadata_tokens(self, domain_metadata: dict[str, Any]) -> set[str]:
        values: list[Any] = [
            domain_metadata.get("domain"),
            domain_metadata.get("document_type"),
            domain_metadata.get("citation_style"),
            domain_metadata.get("expected_structure"),
            domain_metadata.get("reference_pattern"),
            domain_metadata.get("script"),
            domain_metadata.get("content_role"),
        ]
        tags = domain_metadata.get("tags")
        if isinstance(tags, list):
            values.extend(tags)
        return {
            value.strip().casefold()
            for value in values
            if isinstance(value, str) and value.strip()
        }

    async def _ai_repair_suggestion(
        self,
        repair_plan: dict[str, Any],
        *,
        options: IndexDocumentIn,
        settings: AppSettings | None,
    ) -> dict[str, Any]:
        if settings is None:
            return {
                "status": "skipped",
                "reason": "App settings were not provided.",
            }

        try:
            profile = await RuntimeProfileService(
                self.session,
                settings,
            ).get_active_profile()
        except RuntimeProfileNotConfiguredError as exc:
            return {"status": "skipped", "reason": str(exc)}

        if not profile.llm_base_url or not profile.llm_model:
            return {
                "status": "skipped",
                "reason": "Active runtime profile has no LLM endpoint configured.",
            }

        headers = {"content-type": "application/json"}
        if profile.llm_api_key:
            headers["authorization"] = f"Bearer {profile.llm_api_key}"

        prompt = self._ai_repair_prompt(repair_plan, options)
        payload: dict[str, Any] = {
            "model": profile.llm_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You review RAG indexing warning repair plans. Return compact JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "max_tokens": 900,
            "response_format": {"type": "json_object"},
        }
        timeout = min(max((profile.llm_timeout_ms or 10_000) / 1000, 30), 90)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    self._chat_url(profile.llm_base_url),
                    headers=headers,
                    json=payload,
                )
                if self._is_response_format_rejection(response):
                    fallback_payload = dict(payload)
                    fallback_payload.pop("response_format", None)
                    response = await client.post(
                        self._chat_url(profile.llm_base_url),
                        headers=headers,
                        json=fallback_payload,
                    )
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
            return {
                "status": "failed",
                "model": profile.llm_model,
                "reason": str(exc),
            }

        content = self._llm_content(body)
        try:
            suggestion = self._json_from_text(content)
        except (json.JSONDecodeError, ValueError) as exc:
            return {
                "status": "failed",
                "model": profile.llm_model,
                "reason": f"Reasoning model returned invalid JSON: {exc}",
                "raw_text": content[:1000],
            }

        return {
            "status": "succeeded",
            "model": profile.llm_model,
            "runtime_profile_id": profile.id,
            "suggestion": suggestion,
            "usage": self._dict_value(body.get("usage")),
        }

    def _ai_repair_prompt(
        self,
        repair_plan: dict[str, Any],
        options: IndexDocumentIn,
    ) -> str:
        prompt_payload = {
            "index_options": self._compact_for_prompt(
                options.model_dump(mode="json", exclude_none=True)
            ),
            "repair_plan": self._compact_for_prompt(repair_plan),
        }
        return (
            "Review this metadata-aware RAG index warning repair plan before reindex. "
            "Use the warning counts, samples, index quality summary, and domain metadata. "
            "Do not invent unavailable source text. Return JSON only with these keys: "
            "summary, suggested_metadata_overrides, risks, reindex_expectations. "
            "If the deterministic plan is sufficient, say so and keep overrides small.\n\n"
            f"{json.dumps(prompt_payload, ensure_ascii=False, indent=2)}"
        )

    def _compact_for_prompt(self, value: Any, *, depth: int = 0) -> Any:
        if depth >= 5:
            return "[truncated]"
        if isinstance(value, dict):
            compact: dict[str, Any] = {}
            for index, (key, nested) in enumerate(value.items()):
                if index >= 24:
                    compact["__truncated__"] = True
                    break
                compact[str(key)] = self._compact_for_prompt(nested, depth=depth + 1)
            return compact
        if isinstance(value, list):
            return [self._compact_for_prompt(item, depth=depth + 1) for item in value[:12]]
        if isinstance(value, str):
            return value if len(value) <= 800 else f"{value[:800]}...[truncated]"
        return value

    def _chat_url(self, base_url: str) -> str:
        normalized = base_url.rstrip("/")
        if normalized.endswith("/chat/completions"):
            return normalized
        return f"{normalized}/chat/completions"

    def _is_response_format_rejection(self, response: httpx.Response) -> bool:
        if response.status_code not in {400, 422}:
            return False
        try:
            error_text = json.dumps(response.json())
        except (json.JSONDecodeError, TypeError, ValueError):
            error_text = response.text
        lower_error = error_text.lower()
        return "response_format" in lower_error or (
            "response format" in lower_error and "unsupported" in lower_error
        )

    def _llm_content(self, body: Any) -> str:
        if not isinstance(body, dict):
            return ""
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first = choices[0]
        if not isinstance(first, dict):
            return ""
        message = first.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
        text = first.get("text")
        return text if isinstance(text, str) else ""

    def _json_from_text(self, text: str) -> dict[str, Any]:
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
            stripped = re.sub(r"\s*```$", "", stripped)
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
            if not match:
                raise
            parsed = json.loads(match.group(0))
        if not isinstance(parsed, dict):
            raise ValueError("Expected a JSON object.")
        return parsed

    def _deep_merge(self, base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        for key, value in patch.items():
            existing = merged.get(key)
            if isinstance(existing, dict) and isinstance(value, dict):
                merged[key] = self._deep_merge(existing, value)
            else:
                merged[key] = value
        return merged

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
