import pytest
from ragstudio.db.models import Chunk, Document, GraphProjectionRecord, IndexRecord, Job
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.document_pipeline_timeline import (
    DocumentPipelineContractOut,
    DocumentPipelineEventOut,
    DocumentPipelineStageOut,
    DocumentPipelineTimelineOut,
    DocumentPipelineTotalsOut,
    DocumentPipelineWarningGroupOut,
)
from ragstudio.services.document_pipeline_timeline_service import (
    DocumentPipelineTimelineService,
    _stage_display_metadata,
)


def _stage(stage_id: str, label: str, state: str, detail: str):
    category, icon_hint, inspector_kind = _stage_display_metadata(stage_id)
    return type(
        "StageStub",
        (),
        {
            "id": stage_id,
            "label": label,
            "state": state,
            "detail": detail,
            "category": category,
            "icon_hint": icon_hint,
            "inspector_kind": inspector_kind,
        },
    )()


def test_pipeline_stage_contract_includes_display_metadata():
    stage = _stage(
        stage_id="contract",
        label="Contract",
        state="metadata_only",
        detail="Reference structure is metadata only and is not enforced.",
    )

    assert stage.category == "domain"
    assert stage.icon_hint == "contract"
    assert stage.inspector_kind == "contract"


def test_unknown_pipeline_stage_gets_neutral_display_metadata():
    stage = _stage(
        stage_id="model_compiler",
        label="Model compiler",
        state="complete",
        detail="Executed model-generated contract candidates.",
    )

    assert stage.category == "custom"
    assert stage.icon_hint == "stage"
    assert stage.inspector_kind == "generic"


def test_document_pipeline_timeline_contract_serializes_dynamic_stages():
    timeline = DocumentPipelineTimelineOut(
        document_id="doc-1",
        filename="quran_arabic_english.pdf",
        status=StageStatus.RUNNING,
        latest_job_id="job-1",
        contract_version=1,
        stages=[
            DocumentPipelineStageOut(
                id="custom_future_stage",
                label="Custom future stage",
                state="warning",
                detail="Future stage emitted by backend contract.",
                order=30,
                progress=58,
                is_current=True,
                event_count=1,
                warning_count=2,
                chunk_count=4500,
                source="structured_event",
                detail_payload={"custom": "value"},
            )
        ],
        events=[
            DocumentPipelineEventOut(
                sequence=1,
                stage_id="custom_future_stage",
                label="Custom future stage",
                detail="Future stage emitted by backend contract.",
                state="warning",
                progress=58,
                occurred_at="2026-05-24T17:20:00+00:00",
                source="structured_event",
                job_id="job-1",
                chunk_count=4500,
                warning="custom warning",
                detail_payload={"custom": "value"},
            )
        ],
        contract=DocumentPipelineContractOut(
            contract_status="metadata_only",
            verified=False,
            canonical_units=False,
            schema_type="chapter_verse",
            repair_status="unverified",
            validation_status="unverified",
            validation_matched_units=0,
            rejection_reasons=["named capture groups missing"],
        ),
        warning_groups=[
            DocumentPipelineWarningGroupOut(
                code="reference_unit_missing_expected_script",
                expected_script="arabic",
                count=912,
                message="Reference-bearing chunk is expected to contain Arabic script.",
                sample_chunk_ids=["chunk-1"],
            )
        ],
        totals=DocumentPipelineTotalsOut(
            jobs=1,
            chunks=4500,
            warnings=912,
            graph_nodes=0,
            graph_edges=0,
            index_records=0,
            graph_records=0,
        ),
        missing_sections=[],
    )

    payload = timeline.model_dump(mode="json")

    assert payload["stages"][0]["id"] == "custom_future_stage"
    assert payload["stages"][0]["state"] == "warning"
    assert payload["contract"]["contract_status"] == "metadata_only"
    assert payload["contract"]["verified"] is False
    assert payload["contract"]["canonical_units"] is False
    assert payload["contract"]["validation_matched_units"] == 0
    assert payload["warning_groups"][0]["code"] == "reference_unit_missing_expected_script"


@pytest.mark.asyncio
async def test_document_pipeline_timeline_service_builds_dynamic_stage_flow(client):
    document = Document(
        id="doc-timeline",
        filename="quran_arabic_english.pdf",
        content_type="application/pdf",
        sha256="sha-timeline",
        artifact_path="/data/uploads/quran_arabic_english.pdf",
        status=StageStatus.RUNNING.value,
        index_contract={
            "contract_status": "metadata_only",
            "domain_metadata": {
                "domain": "religious_text",
                "document_type": "quran_translation",
                "language": "mixed",
                "metadata_sources": ["ai_vision"],
                "custom_json": {
                    "reference_schema": {
                        "type": "chapter_verse",
                        "identity_fields": ["chapter", "verse"],
                        "canonical_ref_template": "{chapter}:{verse}",
                    },
                    "reference_contract_repair": {
                        "status": "unverified",
                        "rejections": [{"reason": "named capture groups missing"}],
                    },
                    "reference_contract_validation": {
                        "status": "unverified",
                        "matched_units": 0,
                        "candidates": [{"rejection_reason": "unsupported_regex"}],
                    },
                },
            },
            "reference_contract": {
                "verified": False,
                "canonical_units": False,
                "schema_type": "chapter_verse",
            },
        },
    )
    job = Job(
        id="job-timeline",
        type="index_document",
        target_id=document.id,
        status=StageStatus.RUNNING.value,
        progress=57,
        logs=["Persisting chunks: Persisted 4500 of 17699 canonical chunks."],
        result={
            "indexing_stage": {
                "stage": "custom_future_stage",
                "label": "Custom future stage",
                "detail": "Future stage emitted by backend contract.",
                "progress": 57,
                "chunk_count": 4500,
            },
            "indexing_stage_events": [
                {
                    "sequence": 1,
                    "stage": "mineru_validated",
                    "label": "MinerU validated",
                    "detail": "Validated 17699 chunks from MinerU.",
                    "progress": 45,
                    "occurred_at": "2026-05-24T17:16:33+00:00",
                    "chunk_count": 17699,
                },
                {
                    "sequence": 2,
                    "stage": "custom_future_stage",
                    "label": "Custom future stage",
                    "detail": "Future stage emitted by backend contract.",
                    "progress": 57,
                    "occurred_at": "2026-05-24T17:20:00+00:00",
                    "chunk_count": 4500,
                    "warning": "custom warning",
                },
            ],
        },
    )
    chunks = [
        Chunk(
            id="chunk-arabic",
            document_id=document.id,
            text="Verse 1:1",
            extraction_quality={
                "parser_warnings": [
                    {
                        "code": "reference_unit_missing_expected_script",
                        "expected_script": "arabic",
                        "message": "Missing Arabic script.",
                        "reference": "1:1",
                        "page": 2,
                    }
                ]
            },
        ),
        Chunk(
            id="chunk-latin",
            document_id=document.id,
            text="Verse 1:2",
            extraction_quality={
                "parser_warnings": [
                    {
                        "code": "reference_unit_missing_expected_script",
                        "expected_script": "latin",
                        "message": "Missing Latin script.",
                        "reference": "1:2",
                        "page": 2,
                    }
                ]
            },
        ),
        Chunk(
            id="chunk-equation",
            document_id=document.id,
            text="[Equation content]",
            extraction_quality={
                "parser_warnings": [
                    {
                        "code": "equation_missing_latex",
                        "message": "Equation chunk has no LaTeX content.",
                    }
                ]
            },
        ),
        Chunk(
            id="chunk-reference",
            document_id=document.id,
            text="Reference pending",
            extraction_quality={
                "parser_warnings": [
                    {
                        "code": "reference_unit_unresolved",
                        "message": "Reference unit could not be resolved.",
                    }
                ]
            },
        ),
    ]
    index_record = IndexRecord(
        id="index-record",
        document_id=document.id,
        runtime_profile_id="runtime",
        status=StageStatus.SUCCEEDED.value,
        chunk_count=4,
    )
    graph_record = GraphProjectionRecord(
        id="graph-record",
        document_id=document.id,
        runtime_profile_id="runtime",
        status=StageStatus.SUCCEEDED.value,
        node_count=3,
        edge_count=2,
    )
    async with client._transport.app.state.session_factory() as session:
        session.add_all([document, job, *chunks, index_record, graph_record])
        await session.commit()
        timeline = await DocumentPipelineTimelineService(session).get_timeline(document.id)

    stage_ids = [stage.id for stage in timeline.stages]
    assert "uploaded" in stage_ids
    assert "vision" in stage_ids
    assert "contract" in stage_ids
    assert "mineru_validated" in stage_ids
    contract_stage = next(stage for stage in timeline.stages if stage.id == "contract")
    assert contract_stage.category == "domain"
    assert contract_stage.icon_hint == "contract"
    assert contract_stage.inspector_kind == "contract"
    custom_stage = next(stage for stage in timeline.stages if stage.id == "custom_future_stage")
    assert custom_stage.category == "custom"
    assert custom_stage.icon_hint == "stage"
    assert custom_stage.inspector_kind == "generic"
    assert "custom_future_stage" in stage_ids
    assert "quality_gates" in stage_ids
    assert "materialization" in stage_ids
    assert timeline.contract.contract_status == "metadata_only"
    assert timeline.contract.verified is False
    assert timeline.contract.canonical_units is False
    assert timeline.contract.schema_type == "chapter_verse"
    assert timeline.contract.repair_status == "unverified"
    assert timeline.contract.validation_status == "unverified"
    assert timeline.contract.validation_matched_units == 0
    assert "named capture groups missing" in timeline.contract.rejection_reasons
    assert "unsupported_regex" in timeline.contract.rejection_reasons

    warning_counts = {
        (group.code, group.expected_script): group.count for group in timeline.warning_groups
    }
    assert warning_counts[("reference_unit_missing_expected_script", "arabic")] == 1
    assert warning_counts[("reference_unit_missing_expected_script", "latin")] == 1
    assert warning_counts[("equation_missing_latex", None)] == 1
    assert warning_counts[("reference_unit_unresolved", None)] == 1
    assert timeline.totals.chunks == 4
    assert timeline.totals.warnings == 4
    assert timeline.totals.graph_nodes == 3
    assert timeline.totals.graph_edges == 2


@pytest.mark.asyncio
async def test_document_pipeline_timeline_route_returns_timeline(client):
    document = Document(
        id="doc-route-timeline",
        filename="policy.pdf",
        content_type="application/pdf",
        sha256="sha-route-timeline",
        artifact_path="/data/uploads/policy.pdf",
        status=StageStatus.SUCCEEDED.value,
        index_contract={},
    )
    async with client._transport.app.state.session_factory() as session:
        session.add(document)
        await session.commit()

    response = await client.get(f"/api/documents/{document.id}/pipeline-timeline")

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == document.id
    assert body["filename"] == "policy.pdf"
    assert body["stages"][0]["id"] == "uploaded"


@pytest.mark.asyncio
async def test_document_pipeline_timeline_route_returns_404(client):
    response = await client.get("/api/documents/missing-doc/pipeline-timeline")

    assert response.status_code == 404
