from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from ragstudio.db.models import Chunk, Document, GraphProjectionRecord, IndexRecord, Job
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.document_pipeline_timeline import (
    DocumentPipelineContractOut,
    DocumentPipelineEventOut,
    DocumentPipelineStageOut,
    DocumentPipelineTimelineOut,
    DocumentPipelineTotalsOut,
    DocumentPipelineWarningGroupOut,
    PipelineEventSource,
    PipelineStageState,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class DocumentPipelineTimelineNotFoundError(Exception):
    """Raised when a document has no timeline source row."""


_BASE_STAGE_ORDER = {
    "uploaded": 10,
    "vision": 20,
    "vision_sampled": 22,
    "contract": 30,
    "contract_proposed": 32,
    "contract_executed": 34,
    "contract_verified": 36,
    "upload_contract_applied": 38,
    "canonical_units_enabled": 39,
    "queued": 40,
    "worker_claimed": 45,
    "mineru_parsing": 50,
    "mineru_validated": 60,
    "chunks_persisting": 70,
    "chunks_persisted": 80,
    "quality_gates": 90,
    "search_ready": 100,
    "runtime_enriching": 110,
    "graph_enriching": 120,
    "materialization": 130,
    "ready": 140,
    "ready_with_warnings": 140,
    "failed": 140,
    "proof_readiness": 150,
}

_STAGE_DISPLAY_METADATA: dict[str, tuple[str, str, str]] = {
    "uploaded": ("layout", "upload", "generic"),
    "vision": ("domain", "vision", "generic"),
    "vision_sampled": ("domain", "vision", "generic"),
    "contract": ("domain", "contract", "contract"),
    "contract_proposed": ("domain", "contract", "contract"),
    "contract_executed": ("domain", "contract", "contract"),
    "contract_verified": ("domain", "contract", "contract"),
    "upload_contract_applied": ("domain", "upload", "contract"),
    "canonical_units_enabled": ("context", "chunks", "contract"),
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


class DocumentPipelineTimelineService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_timeline(self, document_id: str) -> DocumentPipelineTimelineOut:
        document = await self._document(document_id)
        if document is None:
            raise DocumentPipelineTimelineNotFoundError(document_id)

        jobs = await self._jobs(document_id)
        chunks = await self._chunks(document_id)
        index_records = await self._index_records(document_id)
        graph_records = await self._graph_records(document_id)

        contract = _contract_summary(document.index_contract or {})
        latest_index_options = _latest_index_options(document, jobs)
        warning_groups = _warning_groups(chunks)
        events = _events(
            document,
            jobs,
            contract,
            warning_groups,
            index_records,
            graph_records,
            latest_index_options,
        )
        stages = _stages(
            events,
            jobs,
            contract,
            warning_groups,
            chunks,
            index_records,
            graph_records,
        )
        missing_sections = _missing_sections(jobs, chunks)

        latest_job = jobs[-1] if jobs else None
        return DocumentPipelineTimelineOut(
            document_id=document.id,
            filename=document.filename,
            status=StageStatus(document.status),
            latest_job_id=latest_job.id if latest_job else None,
            contract_version=1,
            stages=stages,
            events=events,
            contract=contract,
            warning_groups=warning_groups,
            totals=DocumentPipelineTotalsOut(
                jobs=len(jobs),
                chunks=len(chunks),
                warnings=sum(group.count for group in warning_groups),
                graph_nodes=sum(record.node_count for record in graph_records),
                graph_edges=sum(record.edge_count for record in graph_records),
                index_records=len(index_records),
                graph_records=len(graph_records),
            ),
            missing_sections=missing_sections,
        )

    async def _document(self, document_id: str) -> Document | None:
        result = await self._session.execute(select(Document).where(Document.id == document_id))
        return result.scalar_one_or_none()

    async def _jobs(self, document_id: str) -> list[Job]:
        result = await self._session.execute(
            select(Job)
            .where(Job.type == "index_document", Job.target_id == document_id)
            .order_by(Job.created_at, Job.id)
        )
        return list(result.scalars())

    async def _chunks(self, document_id: str) -> list[Chunk]:
        result = await self._session.execute(
            select(Chunk)
            .where(Chunk.document_id == document_id)
            .order_by(Chunk.created_at, Chunk.id)
        )
        return list(result.scalars())

    async def _index_records(self, document_id: str) -> list[IndexRecord]:
        result = await self._session.execute(
            select(IndexRecord)
            .where(IndexRecord.document_id == document_id)
            .order_by(IndexRecord.created_at, IndexRecord.id)
        )
        return list(result.scalars())

    async def _graph_records(self, document_id: str) -> list[GraphProjectionRecord]:
        result = await self._session.execute(
            select(GraphProjectionRecord)
            .where(GraphProjectionRecord.document_id == document_id)
            .order_by(GraphProjectionRecord.created_at, GraphProjectionRecord.id)
        )
        return list(result.scalars())


def _events(
    document: Document,
    jobs: list[Job],
    contract: DocumentPipelineContractOut,
    warning_groups: list[DocumentPipelineWarningGroupOut],
    index_records: list[IndexRecord],
    graph_records: list[GraphProjectionRecord],
    latest_index_options: dict[str, Any],
) -> list[DocumentPipelineEventOut]:
    events: list[DocumentPipelineEventOut] = []
    sequence = 1

    events.append(
        DocumentPipelineEventOut(
            sequence=sequence,
            stage_id="uploaded",
            label="Upload",
            detail=f"Stored source artifact for {document.filename}.",
            state="complete",
            progress=0,
            occurred_at=document.created_at.isoformat() if document.created_at else None,
            source="document",
            detail_payload={
                "artifact_path": document.artifact_path,
                "artifact_exists": _artifact_exists(document.artifact_path),
                "content_type": document.content_type,
            },
        )
    )
    sequence += 1

    index_contract = document.index_contract or {}
    domain_metadata = _domain_metadata(index_contract, latest_index_options)
    if domain_metadata:
        events.append(
            DocumentPipelineEventOut(
                sequence=sequence,
                stage_id="vision",
                label="Vision profile",
                detail=_vision_detail(domain_metadata),
                state="complete",
                progress=None,
                occurred_at=None,
                source="document",
                detail_payload=domain_metadata,
            )
        )
        sequence += 1

    if _has_contract_signal(contract):
        state: PipelineStageState = "complete" if contract.verified else "metadata_only"
        detail = (
            "Executable reference contract verified."
            if contract.verified
            else "Reference structure is metadata only and is not enforced."
        )
        events.append(
            DocumentPipelineEventOut(
                sequence=sequence,
                stage_id="contract",
                label="Contract",
                detail=detail,
                state=state,
                progress=None,
                occurred_at=None,
                source="contract",
                detail_payload=contract.model_dump(mode="json"),
            )
        )
        sequence += 1

    sequence = _append_contract_flow_events(
        events,
        sequence,
        index_contract,
        latest_index_options,
    )

    for job in jobs:
        structured_events = _structured_job_events(job)
        if structured_events:
            for raw_event in structured_events:
                events.append(_event_from_structured_job_event(sequence, job, raw_event))
                sequence += 1
        else:
            for log in job.logs or []:
                events.append(_event_from_log(sequence, job, log))
                sequence += 1

    if warning_groups:
        events.append(
            DocumentPipelineEventOut(
                sequence=sequence,
                stage_id="quality_gates",
                label="Quality gates",
                detail=f"Grouped {sum(group.count for group in warning_groups)} parser warnings.",
                state="warning",
                progress=None,
                occurred_at=None,
                source="warning",
                warning=f"{sum(group.count for group in warning_groups)} warnings",
            )
        )
        sequence += 1

    if index_records or graph_records:
        graph_nodes = sum(record.node_count for record in graph_records)
        graph_edges = sum(record.edge_count for record in graph_records)
        events.append(
            DocumentPipelineEventOut(
                sequence=sequence,
                stage_id="materialization",
                label="Materialization",
                detail=(
                    f"{len(index_records)} index records, {len(graph_records)} graph records, "
                    f"{graph_nodes} graph nodes, {graph_edges} graph edges."
                ),
                state="complete",
                progress=None,
                occurred_at=None,
                source="index_record",
                detail_payload={
                    "index_records": len(index_records),
                    "graph_records": len(graph_records),
                    "graph_nodes": graph_nodes,
                    "graph_edges": graph_edges,
                },
            )
        )

    return events


def _stages(
    events: list[DocumentPipelineEventOut],
    jobs: list[Job],
    contract: DocumentPipelineContractOut,
    warning_groups: list[DocumentPipelineWarningGroupOut],
    chunks: list[Chunk],
    index_records: list[IndexRecord],
    graph_records: list[GraphProjectionRecord],
) -> list[DocumentPipelineStageOut]:
    grouped: dict[str, list[DocumentPipelineEventOut]] = defaultdict(list)
    for event in events:
        grouped[event.stage_id].append(event)

    current_stage_id = _current_stage_id(jobs)
    stages: list[DocumentPipelineStageOut] = []
    for stage_id, stage_events in grouped.items():
        last = stage_events[-1]
        state = _stage_state(stage_id, stage_events, current_stage_id, contract)
        category, icon_hint, inspector_kind = _stage_display_metadata(stage_id)
        warning_count = _stage_warning_count(stage_id, warning_groups)
        detail_payload = dict(last.detail_payload)
        if stage_id == "contract":
            detail_payload = contract.model_dump(mode="json")
        elif stage_id == "quality_gates":
            detail_payload = {
                "warning_groups": [
                    group.model_dump(mode="json") for group in warning_groups
                ]
            }
        elif stage_id == "materialization":
            detail_payload.update(
                {
                    "index_records": len(index_records),
                    "graph_records": len(graph_records),
                    "graph_nodes": sum(record.node_count for record in graph_records),
                    "graph_edges": sum(record.edge_count for record in graph_records),
                }
            )

        stages.append(
            DocumentPipelineStageOut(
                id=stage_id,
                label=last.label,
                state=state,
                detail=last.detail,
                order=_stage_order(stage_id, last.sequence),
                category=category,
                icon_hint=icon_hint,
                inspector_kind=inspector_kind,
                progress=last.progress,
                is_current=stage_id == current_stage_id,
                event_count=len(stage_events),
                warning_count=warning_count,
                chunk_count=(
                    last.chunk_count
                    if last.chunk_count is not None
                    else len(chunks) or None
                ),
                source=last.source,
                started_at=stage_events[0].occurred_at,
                completed_at=None if stage_id == current_stage_id else last.occurred_at,
                detail_payload=detail_payload,
            )
        )
    return sorted(stages, key=lambda stage: (stage.order, stage.id))


def _latest_index_options(document: Document, jobs: list[Job]) -> dict[str, Any]:
    for job in reversed(jobs):
        for candidate in (job.job_options, _dict(job.result or {}, "index_options")):
            if isinstance(candidate, dict) and candidate:
                return dict(candidate)

    domain_metadata = _dict(document.index_contract or {}, "domain_metadata")
    if domain_metadata:
        payload: dict[str, Any] = {"domain_metadata": domain_metadata}
        analysis_binding = _dict(document.index_contract or {}, "analysis_binding")
        if analysis_binding:
            payload["analysis_binding"] = analysis_binding
        return payload
    return {}


def _domain_metadata(
    index_contract: dict[str, Any],
    latest_index_options: dict[str, Any],
) -> dict[str, Any]:
    return (
        _dict(latest_index_options, "domain_metadata")
        or _dict(index_contract, "domain_metadata")
    )


def _append_contract_flow_events(
    events: list[DocumentPipelineEventOut],
    sequence: int,
    index_contract: dict[str, Any],
    latest_index_options: dict[str, Any],
) -> int:
    domain_metadata = _domain_metadata(index_contract, latest_index_options)
    latest_custom_json = _dict(domain_metadata, "custom_json")
    reference_schema = _dict(latest_custom_json, "reference_schema")
    domain_structure = _dict(latest_custom_json, "domain_structure")
    execution = _dict(latest_custom_json, "reference_contract_execution")
    validation = _dict(latest_custom_json, "reference_contract_validation")
    reference_resolution = _dict(latest_custom_json, "reference_resolution")
    reference_contract = _dict(index_contract, "reference_contract")
    vision_analysis = _dict(index_contract, "vision_analysis")
    analysis_binding = _dict(latest_index_options, "analysis_binding")
    evidence_pages = _evidence_pages(
        latest_index_options,
        latest_custom_json,
        execution,
        validation,
        vision_analysis,
    )

    if evidence_pages or analysis_binding:
        sequence = _append_flow_event(
            events,
            sequence,
            stage_id="vision_sampled",
            label="Vision sampled pages",
            detail="Vision analysis sampled pages for upload contract evidence.",
            state="complete",
            source="document",
            detail_payload={
                "evidence_pages": evidence_pages,
                "analysis_binding": analysis_binding or None,
            },
        )

    if reference_schema or domain_structure:
        sequence = _append_flow_event(
            events,
            sequence,
            stage_id="contract_proposed",
            label="Contract proposed",
            detail="Reference contract structure was proposed from document metadata.",
            state="complete",
            source="contract",
            detail_payload={
                "reference_schema": reference_schema,
                "domain_structure": domain_structure,
                "identity_fields": _reference_schema_fields(reference_schema),
            },
        )

    if execution:
        execution_state = _contract_status_state(execution)
        sequence = _append_flow_event(
            events,
            sequence,
            stage_id="contract_executed",
            label="Contract executed",
            detail=(
                "Contract execution verified sampled reference units."
                if execution_state == "complete"
                else "Contract execution is metadata-only and did not verify canonical units."
            ),
            state=execution_state,
            source="contract",
            detail_payload=execution,
        )

    if validation:
        validation_state = _contract_status_state(validation)
        sequence = _append_flow_event(
            events,
            sequence,
            stage_id="contract_verified",
            label="Contract verified",
            detail=(
                "Contract validation verified the selected reference strategy."
                if validation_state == "complete"
                else "Contract validation is metadata-only and not upload-enforced."
            ),
            state=validation_state,
            source="contract",
            detail_payload=validation,
        )

    if latest_custom_json and (analysis_binding or execution or validation):
        sequence = _append_flow_event(
            events,
            sequence,
            stage_id="upload_contract_applied",
            label="Upload contract applied",
            detail="Upload metadata package was applied to indexing options.",
            state="complete",
            source="contract",
            detail_payload={
                "custom_json": latest_custom_json,
                "analysis_binding": analysis_binding or None,
            },
        )

    canonical_units = (
        reference_contract.get("verified") is True
        and reference_contract.get("canonical_units") is True
    )
    if canonical_units or reference_contract or reference_resolution:
        sequence = _append_flow_event(
            events,
            sequence,
            stage_id="canonical_units_enabled",
            label="Canonical units enabled",
            detail=(
                "Verified contract enables canonical reference units."
                if canonical_units
                else "Canonical reference units are unavailable without a verified contract."
            ),
            state="complete" if canonical_units else "metadata_only",
            source="contract",
            detail_payload={
                "reference_contract": reference_contract,
                "reference_resolution": reference_resolution,
            },
        )

    return sequence


def _append_flow_event(
    events: list[DocumentPipelineEventOut],
    sequence: int,
    *,
    stage_id: str,
    label: str,
    detail: str,
    state: PipelineStageState,
    source: PipelineEventSource,
    detail_payload: dict[str, Any],
) -> int:
    events.append(
        DocumentPipelineEventOut(
            sequence=sequence,
            stage_id=stage_id,
            label=label,
            detail=detail,
            state=state,
            progress=None,
            occurred_at=None,
            source=source,
            detail_payload=detail_payload,
        )
    )
    return sequence + 1


def _evidence_pages(
    latest_index_options: dict[str, Any],
    latest_custom_json: dict[str, Any],
    execution: dict[str, Any],
    validation: dict[str, Any],
    vision_analysis: dict[str, Any],
) -> list[Any]:
    custom_vision_analysis = _dict(latest_custom_json, "vision_analysis")
    for value in (
        latest_index_options.get("evidence_pages"),
        latest_custom_json.get("evidence_pages"),
        custom_vision_analysis.get("sample_pages"),
        execution.get("matched_pages"),
        validation.get("matched_pages"),
        vision_analysis.get("sample_pages"),
    ):
        pages = _list_value(value)
        if pages:
            return pages
    return []


def _contract_status_state(payload: dict[str, Any]) -> PipelineStageState:
    if _normalized_status(payload.get("status")) == "verified":
        return "complete"
    return "metadata_only"


def _reference_schema_fields(reference_schema: dict[str, Any]) -> list[str]:
    for key in ("identity_fields", "required_fields", "fields"):
        values = reference_schema.get(key)
        if isinstance(values, list):
            return [item.strip() for item in values if isinstance(item, str) and item.strip()]
        if isinstance(values, dict):
            return [item.strip() for item in values if isinstance(item, str) and item.strip()]
    return []


def _contract_summary(index_contract: dict[str, Any]) -> DocumentPipelineContractOut:
    reference_contract = _dict(index_contract, "reference_contract")
    domain_metadata = _dict(index_contract, "domain_metadata")
    custom_json = _dict(domain_metadata, "custom_json")
    repair = _dict(custom_json, "reference_contract_repair")
    validation = _dict(custom_json, "reference_contract_validation")
    reference_schema = _dict(custom_json, "reference_schema")
    rejection_reasons = _rejection_reasons(repair, validation)

    return DocumentPipelineContractOut(
        contract_status=_str_or_none(index_contract.get("contract_status")),
        verified=_bool_or_none(reference_contract.get("verified")),
        canonical_units=_bool_or_none(reference_contract.get("canonical_units")),
        schema_type=_first_string(
            reference_contract.get("schema_type"),
            reference_schema.get("type"),
        ),
        repair_status=_str_or_none(repair.get("status")),
        validation_status=_str_or_none(validation.get("status")),
        validation_matched_units=_int_or_none(validation.get("matched_units")),
        selected_strategy=_first_string(
            validation.get("selected_strategy"),
            reference_contract.get("strategy"),
        ),
        rejection_reasons=rejection_reasons,
        detail_payload={
            "contract_status": index_contract.get("contract_status"),
            "reference_contract": reference_contract,
            "reference_schema": reference_schema,
        },
    )


def _warning_groups(chunks: list[Chunk]) -> list[DocumentPipelineWarningGroupOut]:
    grouped: dict[tuple[str, str | None], dict[str, Any]] = {}
    for chunk in chunks:
        warnings = chunk.extraction_quality.get("parser_warnings")
        if not isinstance(warnings, list):
            continue
        for warning in warnings:
            if not isinstance(warning, dict):
                continue
            if warning.get("suppressed_from_counts") is True:
                continue
            code = _str_or_none(warning.get("code")) or "unknown_warning"
            expected_script = _str_or_none(warning.get("expected_script"))
            key = (code, expected_script)
            entry = grouped.setdefault(
                key,
                {
                    "count": 0,
                    "message": _str_or_none(warning.get("message")),
                    "sample_chunk_ids": [],
                    "sample_references": [],
                    "sample_pages": [],
                },
            )
            entry["count"] += 1
            _append_sample(entry["sample_chunk_ids"], chunk.id)
            _append_sample(entry["sample_references"], _str_or_none(warning.get("reference")))
            page = warning.get("page")
            if isinstance(page, int | str):
                _append_sample(entry["sample_pages"], page)

    return [
        DocumentPipelineWarningGroupOut(
            code=code,
            expected_script=expected_script,
            count=entry["count"],
            message=entry["message"],
            sample_chunk_ids=entry["sample_chunk_ids"],
            sample_references=entry["sample_references"],
            sample_pages=entry["sample_pages"],
        )
        for (code, expected_script), entry in sorted(grouped.items())
    ]


def _structured_job_events(job: Job) -> list[dict[str, Any]]:
    result = job.result or {}
    raw_events = result.get("indexing_stage_events")
    if not isinstance(raw_events, list):
        return []
    return [event for event in raw_events if isinstance(event, dict)]


def _event_from_structured_job_event(
    sequence: int,
    job: Job,
    raw_event: dict[str, Any],
) -> DocumentPipelineEventOut:
    stage_id = _str_or_none(raw_event.get("stage")) or "unknown_stage"
    label = _str_or_none(raw_event.get("label")) or _label_from_id(stage_id)
    warning = _str_or_none(raw_event.get("warning"))
    return DocumentPipelineEventOut(
        sequence=sequence,
        stage_id=stage_id,
        label=label,
        detail=_str_or_none(raw_event.get("detail")) or label,
        state=_event_state(job, raw_event, warning),
        progress=_int_or_none(raw_event.get("progress")),
        occurred_at=_str_or_none(raw_event.get("occurred_at")),
        source="structured_event",
        job_id=job.id,
        chunk_count=_int_or_none(raw_event.get("chunk_count")),
        warning=warning,
        detail_payload=dict(raw_event),
    )


def _event_from_log(sequence: int, job: Job, log: str) -> DocumentPipelineEventOut:
    label, _, detail = log.partition(":")
    return DocumentPipelineEventOut(
        sequence=sequence,
        stage_id=_stage_id_from_label(label),
        label=label.strip() or "Job log",
        detail=detail.strip() or log,
        state="running" if job.status == StageStatus.RUNNING.value else "complete",
        progress=job.progress,
        occurred_at=job.updated_at.isoformat() if job.updated_at else None,
        source="inferred_log",
        job_id=job.id,
    )


def _event_state(
    job: Job,
    raw_event: dict[str, Any],
    warning: str | None,
) -> PipelineStageState:
    if job.status == StageStatus.FAILED.value:
        return "failed"
    current_stage = _dict(job.result or {}, "indexing_stage")
    if (
        job.status == StageStatus.RUNNING.value
        and raw_event.get("stage") == current_stage.get("stage")
    ):
        return "running"
    if warning:
        return "warning"
    return "complete"


def _current_stage_id(jobs: list[Job]) -> str | None:
    if not jobs:
        return None
    latest = jobs[-1]
    if latest.status != StageStatus.RUNNING.value:
        return None
    stage = _dict(latest.result or {}, "indexing_stage")
    return _str_or_none(stage.get("stage"))


def _stage_state(
    stage_id: str,
    events: list[DocumentPipelineEventOut],
    current_stage_id: str | None,
    contract: DocumentPipelineContractOut,
) -> PipelineStageState:
    if stage_id == current_stage_id:
        return "running"
    if stage_id == "contract" and contract.verified is False:
        return "metadata_only"
    if any(event.state in {"failed", "blocked"} for event in events):
        return "failed"
    if any(event.state == "warning" or event.warning for event in events):
        return "warning"
    return events[-1].state if events else "pending"


def _stage_warning_count(
    stage_id: str,
    warning_groups: list[DocumentPipelineWarningGroupOut],
) -> int:
    if stage_id != "quality_gates":
        return 0
    return sum(group.count for group in warning_groups)


def _stage_order(stage_id: str, sequence: int) -> int:
    return _BASE_STAGE_ORDER.get(stage_id, 1000 + sequence)


def _stage_display_metadata(stage_id: str) -> tuple[str, str, str]:
    return _STAGE_DISPLAY_METADATA.get(stage_id, ("custom", "stage", "generic"))


def _missing_sections(jobs: list[Job], chunks: list[Chunk]) -> list[str]:
    missing = []
    if not jobs:
        missing.append("jobs")
    if not chunks:
        missing.append("chunks")
    return missing


def _vision_detail(domain_metadata: dict[str, Any]) -> str:
    domain = _str_or_none(domain_metadata.get("domain"))
    document_type = _str_or_none(domain_metadata.get("document_type"))
    language = _str_or_none(domain_metadata.get("language"))
    parts = [part for part in [domain, document_type, language] if part]
    return " - ".join(parts) or "Metadata recorded."


def _has_contract_signal(contract: DocumentPipelineContractOut) -> bool:
    return any(
        value is not None
        for value in [
            contract.contract_status,
            contract.verified,
            contract.canonical_units,
            contract.schema_type,
            contract.repair_status,
            contract.validation_status,
        ]
    )


def _rejection_reasons(
    repair: dict[str, Any],
    validation: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    for rejection in repair.get("rejections") or []:
        if isinstance(rejection, dict):
            _append_sample(reasons, _str_or_none(rejection.get("reason")), limit=20)
    for candidate in validation.get("candidates") or []:
        if isinstance(candidate, dict):
            _append_sample(reasons, _str_or_none(candidate.get("rejection_reason")), limit=20)
    return reasons


def _artifact_exists(artifact_path: str) -> bool:
    try:
        return Path(artifact_path).is_file()
    except (OSError, ValueError):
        return False


def _stage_id_from_label(label: str) -> str:
    normalized = label.strip().lower().replace(" ", "_").replace("-", "_")
    return normalized or "job_log"


def _label_from_id(stage_id: str) -> str:
    return stage_id.replace("_", " ").title()


def _dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _list_value(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _normalized_status(value: Any) -> str | None:
    return value.strip().casefold() if isinstance(value, str) and value.strip() else None


def _first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _append_sample(items: list[Any], value: Any, *, limit: int = 5) -> None:
    if value is None or value in items or len(items) >= limit:
        return
    items.append(value)
