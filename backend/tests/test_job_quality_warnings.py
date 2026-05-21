import pytest
from ragstudio.db.models import Chunk, Document, IndexRecord, Job
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.job_quality_warning_service import JobQualityWarningService
from sqlalchemy import select


@pytest.mark.asyncio
async def test_job_quality_warnings_exposes_persisted_parser_warning_details(client):
    app = client._transport.app
    parser_warnings = [
        {
            "code": "disallowed_block_type_quarantined",
            "message": "Quarantined text-bearing block because the profile disallows it.",
            "block_type": "heading",
            "page": 3,
        }
    ]
    second_warning = {
        "code": "reference_unit_missing_expected_script",
        "message": "Expected Arabic text in reference unit.",
        "block_type": "paragraph",
        "page": 4,
    }

    async with app.state.session_factory() as session:
        document = Document(
            id="doc-quality-warnings",
            filename="quality.pdf",
            content_type="application/pdf",
            sha256="quality-warning-sha",
            artifact_path=str(app.state.settings.data_dir / "quality.pdf"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        session.add(
            Job(
                id="job-quality-warnings",
                type="index_document",
                target_id=document.id,
                status=StageStatus.SUCCEEDED.value,
                progress=100,
                logs=[
                    "Parser quality warnings: disallowed_block_type_quarantined=1, "
                    "reference_unit_missing_expected_script=1"
                ],
                result={
                    "parser_quality": {
                        "warning_counts": {
                            "disallowed_block_type_quarantined": 1,
                            "reference_unit_missing_expected_script": 1,
                        },
                        "affected_chunks": 2,
                    },
                    "index_quality_report": {
                        "quality_report_version": 1,
                        "status": "passed_with_warnings",
                        "summary": {
                            "reference_unit_count": 1,
                            "reference_units_missing_expected_script": 1,
                        },
                    },
                    "warnings": [
                        "Parser quality warnings: disallowed_block_type_quarantined=1, "
                        "reference_unit_missing_expected_script=1"
                    ],
                },
            )
        )
        session.add_all(
            [
                Chunk(
                    id="chunk-warning-a",
                    document_id=document.id,
                    text="Damaged heading text",
                    source_location={"page": 3, "artifact": "content_list.json"},
                    extraction_quality={"parser_warnings": parser_warnings},
                    metadata_json={
                        "parser_metadata": {
                            "artifact_ref": "content_list.json",
                            "chunk_index": 12,
                            "content_list_ref": "content_list.json",
                        },
                        "reference_metadata": {"references": ["19:13"]},
                        "extraction_quality": {"parser_warnings": parser_warnings},
                    },
                ),
                Chunk(
                    id="chunk-warning-b",
                    document_id=document.id,
                    text="Book 1, Hadith 2 English translation only.",
                    source_location={"page": 4},
                    extraction_quality={"parser_warnings": [second_warning]},
                    metadata_json={
                        "parser_metadata": {"artifact_ref": "content_list.json", "chunk_index": 13},
                        "reference_metadata": {"references": ["Book 1, Hadith 2"]},
                        "extraction_quality": {"parser_warnings": [second_warning]},
                    },
                ),
            ]
        )
        await session.commit()

    response = await client.get("/api/jobs/job-quality-warnings/quality-warnings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == "job-quality-warnings"
    assert payload["document_id"] == "doc-quality-warnings"
    assert payload["total"] == 2
    assert payload["affected_chunks"] == 2
    assert payload["warning_counts"] == {
        "disallowed_block_type_quarantined": 1,
        "reference_unit_missing_expected_script": 1,
    }
    assert payload["index_quality_report"]["status"] == "passed_with_warnings"
    assert payload["job_warnings"] == [
        "Parser quality warnings: disallowed_block_type_quarantined=1, "
        "reference_unit_missing_expected_script=1"
    ]
    first_item = payload["items"][0]
    assert first_item["chunk_id"] == "chunk-warning-a"
    assert first_item["chunk_preview"] == "Damaged heading text"
    assert first_item["source_location"] == {"page": 3, "artifact": "content_list.json"}
    assert first_item["parser_metadata"]["chunk_index"] == 12
    assert first_item["reference_metadata"] == {"references": ["19:13"]}
    assert first_item["code"] == "disallowed_block_type_quarantined"
    assert (
        first_item["message"]
        == "Quarantined text-bearing block because the profile disallows it."
    )
    assert first_item["block_type"] == "heading"
    assert first_item["page"] == 3
    assert first_item["warning"] == parser_warnings[0]


@pytest.mark.asyncio
async def test_job_quality_warnings_keeps_suppressed_recovery_visible_but_uncounted(client):
    app = client._transport.app
    accepted_recovery = {
        "code": "recovered_text_from_misclassified_block",
        "message": "Used parser-provided recovered text.",
        "block_type": "equation",
        "severity": "info",
        "quality_gate_action": "accepted_recovery",
        "suppressed_from_counts": True,
    }

    async with app.state.session_factory() as session:
        document = Document(
            id="doc-quality-info",
            filename="quality-info.pdf",
            content_type="application/pdf",
            sha256="quality-info-sha",
            artifact_path=str(app.state.settings.data_dir / "quality-info.pdf"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        session.add(
            Job(
                id="job-quality-info",
                type="index_document",
                target_id=document.id,
                status=StageStatus.SUCCEEDED.value,
                progress=100,
                logs=[],
                result={
                    "parser_quality": {
                        "warning_counts": {},
                        "affected_chunks": 0,
                    },
                },
            )
        )
        session.add(
            Chunk(
                id="chunk-quality-info",
                document_id=document.id,
                text="Verse 18:30 Tafseer commentary.",
                source_location={"page": 809},
                extraction_quality={"parser_warnings": [accepted_recovery]},
                metadata_json={
                    "parser_metadata": {"artifact_ref": "content_list.json"},
                    "extraction_quality": {"parser_warnings": [accepted_recovery]},
                },
            )
        )
        await session.commit()

    response = await client.get("/api/jobs/job-quality-info/quality-warnings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["warning_counts"] == {}
    assert payload["affected_chunks"] == 0
    assert payload["total"] == 1
    assert payload["items"][0]["warning"]["quality_gate_action"] == "accepted_recovery"


@pytest.mark.asyncio
async def test_job_quality_warnings_dedupes_reference_less_missing_script_warning(client):
    app = client._transport.app
    parser_warnings = [
        {
            "code": "reference_unit_missing_expected_script",
            "message": "Expected Arabic text in reference-bearing chunk.",
            "expected_script": "arabic",
        },
        {
            "code": "reference_unit_missing_expected_script",
            "message": "Expected Arabic text in reference unit.",
            "expected_script": "arabic",
            "reference": "12:108",
        },
    ]

    async with app.state.session_factory() as session:
        document = Document(
            id="doc-quality-dedupe",
            filename="quality-dedupe.pdf",
            content_type="application/pdf",
            sha256="quality-dedupe-sha",
            artifact_path=str(app.state.settings.data_dir / "quality-dedupe.pdf"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        session.add(
            Job(
                id="job-quality-dedupe",
                type="index_document",
                target_id=document.id,
                status=StageStatus.SUCCEEDED.value,
                progress=100,
                logs=[],
                result={
                    "document_id": document.id,
                    "parser_quality": {
                        "warning_counts": {
                            "reference_unit_missing_expected_script": 1,
                        },
                        "affected_chunks": 1,
                    },
                    "index_quality_report": {
                        "summary": {
                            "reference_units_missing_expected_script": 1,
                        },
                    },
                },
            )
        )
        session.add(
            Chunk(
                id="chunk-quality-dedupe",
                document_id=document.id,
                text="[12:108] English-only verse text.",
                source_location={"page": 123},
                extraction_quality={"parser_warnings": parser_warnings},
                metadata_json={
                    "reference_metadata": {"references": ["12:108"]},
                    "extraction_quality": {"parser_warnings": parser_warnings},
                },
            )
        )
        await session.commit()

    response = await client.get("/api/jobs/job-quality-dedupe/quality-warnings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["warning_counts"] == {"reference_unit_missing_expected_script": 1}
    assert payload["affected_chunks"] == 1
    assert payload["total"] == 1
    assert payload["items"][0]["warning"]["reference"] == "12:108"


@pytest.mark.asyncio
async def test_job_quality_warnings_keeps_info_severity_visible_but_uncounted(client):
    app = client._transport.app
    audit_warning = {
        "code": "optional_script_observed",
        "message": "Optional Arabic script was observed for audit only.",
        "severity": "info",
        "quality_gate_action": "audit",
    }

    async with app.state.session_factory() as session:
        document = Document(
            id="doc-quality-audit-info",
            filename="quality-audit-info.pdf",
            content_type="application/pdf",
            sha256="quality-audit-info-sha",
            artifact_path=str(app.state.settings.data_dir / "quality-audit-info.pdf"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        session.add(
            Job(
                id="job-quality-audit-info",
                type="index_document",
                target_id=document.id,
                status=StageStatus.SUCCEEDED.value,
                progress=100,
                logs=[],
                result={},
            )
        )
        session.add(
            Chunk(
                id="chunk-quality-audit-info",
                document_id=document.id,
                text="Audit-only optional script evidence.",
                source_location={"page": 12},
                extraction_quality={"parser_warnings": [audit_warning]},
                metadata_json={"extraction_quality": {"parser_warnings": [audit_warning]}},
            )
        )
        await session.commit()

    response = await client.get("/api/jobs/job-quality-audit-info/quality-warnings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["warning_counts"] == {}
    assert payload["affected_chunks"] == 0
    assert payload["total"] == 1
    assert payload["items"][0]["code"] == "optional_script_observed"


@pytest.mark.asyncio
async def test_fix_job_quality_warnings_does_not_sum_warning_counts_as_affected_chunks(
    client,
    monkeypatch,
):
    app = client._transport.app
    parser_warnings = [
        {
            "code": "reference_unit_missing_expected_script",
            "message": "Expected Arabic text in reference unit.",
        },
        {
            "code": "reference_unit_unresolved",
            "message": "Could not tie this chunk to one reference.",
        },
    ]

    async def fake_ai_repair_suggestion(
        self,
        repair_plan,
        *,
        options,
        settings,
    ):
        return {"status": "skipped", "reason": "test"}

    monkeypatch.setattr(
        JobQualityWarningService,
        "_ai_repair_suggestion",
        fake_ai_repair_suggestion,
    )

    async with app.state.session_factory() as session:
        document = Document(
            id="doc-quality-warning-overlap",
            filename="quality-overlap.pdf",
            content_type="application/pdf",
            sha256="quality-warning-overlap-sha",
            artifact_path=str(app.state.settings.data_dir / "quality-overlap.pdf"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        session.add(
            Job(
                id="job-quality-warning-overlap",
                type="index_document",
                target_id=document.id,
                status=StageStatus.SUCCEEDED.value,
                progress=100,
                logs=[],
                result={
                    "document_id": document.id,
                    "index_options": {"parser_mode": "mineru_strict", "domain_metadata": {}},
                },
                job_options={"parser_mode": "mineru_strict", "domain_metadata": {}},
            )
        )
        session.add(
            Chunk(
                id="chunk-warning-overlap",
                document_id=document.id,
                text="English-only reference continuation.",
                source_location={"page": 8},
                extraction_quality={"parser_warnings": parser_warnings},
                metadata_json={"extraction_quality": {"parser_warnings": parser_warnings}},
            )
        )
        await session.commit()

    response = await client.post(
        "/api/jobs/job-quality-warning-overlap/quality-warnings/fix"
    )

    assert response.status_code == 202
    repair_plan = response.json()["repair_plan"]
    assert repair_plan["warning_counts"] == {
        "reference_unit_missing_expected_script": 1,
        "reference_unit_unresolved": 1,
    }
    assert repair_plan["affected_chunks"] == 1


@pytest.mark.asyncio
async def test_job_quality_warnings_reads_index_report_from_existing_index_record(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        document = Document(
            id="doc-index-quality-report",
            filename="quality-report.pdf",
            content_type="application/pdf",
            sha256="quality-report-sha",
            artifact_path=str(app.state.settings.data_dir / "quality-report.pdf"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        session.add(
            Job(
                id="job-index-quality-report",
                type="index_document",
                target_id=document.id,
                status=StageStatus.SUCCEEDED.value,
                progress=100,
                logs=[],
                result={},
            )
        )
        session.add(
            IndexRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status=StageStatus.SUCCEEDED.value,
                index_shape={
                    "index_quality_report": {
                        "quality_report_version": 1,
                        "status": "passed_with_warnings",
                        "summary": {"reference_unit_unresolved_count": 2},
                    }
                },
                chunk_count=0,
            )
        )
        await session.commit()

    response = await client.get("/api/jobs/job-index-quality-report/quality-warnings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["index_quality_report"]["summary"] == {
        "reference_unit_unresolved_count": 2
    }
    assert payload["items"] == []


@pytest.mark.asyncio
async def test_job_quality_warnings_returns_404_for_unknown_job(client):
    response = await client.get("/api/jobs/missing-job/quality-warnings")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"


@pytest.mark.asyncio
async def test_fix_job_quality_warnings_queues_strict_reindex_from_stored_options(
    client,
    monkeypatch,
):
    app = client._transport.app
    parser_warnings = [
        {
            "code": "reference_unit_missing_expected_script",
            "message": "Expected Arabic text in reference unit.",
            "expected_script": "arabic",
            "block_type": "paragraph",
            "page": 4,
        },
        {
            "code": "reference_unit_unresolved",
            "message": "Could not tie this chunk to one reference.",
            "page": 4,
        },
        {
            "code": "disallowed_block_type_quarantined",
            "message": "Recovered text was emitted as a disallowed block type.",
            "block_type": "equation",
            "page": 4,
        },
    ]
    stored_options = {
        "parser_mode": "mineru_strict",
        "domain_metadata": {"domain": "quran_tafseer", "tags": ["arabic"]},
    }
    expected_options = IndexDocumentIn.model_validate(stored_options).model_dump(
        mode="json",
        exclude_none=True,
    )

    async def fake_ai_repair_suggestion(
        self,
        repair_plan,
        *,
        options,
        settings,
    ):
        return {
            "status": "succeeded",
            "model": "test-reasoning-model",
            "suggestion": {
                "summary": "Preserve parallel reference text and recover prose blocks.",
                "suggested_metadata_overrides": {},
                "risks": [],
                "reindex_expectations": {"warnings_should_drop": True},
            },
        }

    monkeypatch.setattr(
        JobQualityWarningService,
        "_ai_repair_suggestion",
        fake_ai_repair_suggestion,
    )

    async with app.state.session_factory() as session:
        document = Document(
            id="doc-quality-warning-fix",
            filename="quality-fix.pdf",
            content_type="application/pdf",
            sha256="quality-warning-fix-sha",
            artifact_path=str(app.state.settings.data_dir / "quality-fix.pdf"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        session.add(
            Job(
                id="job-quality-warning-fix",
                type="index_document",
                target_id=document.id,
                status=StageStatus.SUCCEEDED.value,
                progress=100,
                logs=["Parser quality warnings: reference_unit_missing_expected_script=1"],
                result={
                    "document_id": document.id,
                    "index_options": stored_options,
                    "parser_quality": {
                        "warning_counts": {
                            "disallowed_block_type_quarantined": 1,
                            "reference_unit_missing_expected_script": 1,
                            "reference_unit_unresolved": 1,
                        },
                        "affected_chunks": 1,
                    },
                    "index_quality_report": {
                        "summary": {
                            "materialization_blocked_reference_count": 1,
                            "reference_unit_unresolved_count": 1,
                            "reference_units_missing_expected_script": 1,
                        },
                        "references": [
                            {
                                "action": "block_reference_materialization",
                                "status": "missing_expected_script",
                                "reference": "Book 1, Hadith 2",
                                "missing_scripts": ["arabic"],
                                "quality_flags": ["missing_expected_script:arabic"],
                                "source_location": {"page_start": 4},
                                "materialization": {
                                    "action": "block_reference_materialization"
                                },
                            }
                        ],
                    },
                },
                job_options=stored_options,
            )
        )
        session.add(
            Chunk(
                id="chunk-warning-fix",
                document_id=document.id,
                text="Book 1, Hadith 2 English translation only.",
                source_location={"page": 4},
                extraction_quality={"parser_warnings": parser_warnings},
                metadata_json={
                    "parser_metadata": {
                        "backend": "mineru",
                        "parser_mode": "mineru_strict",
                    },
                    "domain_metadata": {
                        "domain": "quran_tafseer",
                        "tags": ["arabic"],
                    },
                    "reference_metadata": {"references": ["Book 1, Hadith 2"]},
                    "extraction_quality": {"parser_warnings": parser_warnings},
                },
            )
        )
        await session.commit()

    response = await client.post("/api/jobs/job-quality-warning-fix/quality-warnings/fix")

    assert response.status_code == 202
    payload = response.json()
    assert payload["source_job_id"] == "job-quality-warning-fix"
    assert payload["document_id"] == "doc-quality-warning-fix"
    assert payload["queued_job_status"] == StageStatus.READY.value
    assert payload["index_options"]["parser_mode"] == expected_options["parser_mode"]
    repair_plan = payload["repair_plan"]
    assert repair_plan["strategy"] == "metadata_aware_warning_repair"
    assert repair_plan["warning_counts"] == {
        "disallowed_block_type_quarantined": 1,
        "reference_materialization_blocked": 1,
        "reference_unit_missing_expected_script": 1,
        "reference_unit_unresolved": 1,
    }
    assert {step["code"] for step in repair_plan["steps"]} == {
        "disallowed_block_type_quarantined",
        "reference_materialization_blocked",
        "reference_unit_missing_expected_script",
        "reference_unit_unresolved",
    }
    assert repair_plan["sample_references"] == ["Book 1, Hadith 2"]
    assert repair_plan["sample_pages"] == [4]
    assert repair_plan["sample_chunk_previews"] == [
        "Book 1, Hadith 2 English translation only."
    ]
    assert repair_plan["ai_suggestion"]["status"] == "succeeded"
    assert repair_plan["ai_suggestion"]["model"] == "test-reasoning-model"
    repaired_custom_json = payload["index_options"]["domain_metadata"]["custom_json"]
    assert "repair_plan" not in repaired_custom_json
    assert repaired_custom_json["repair_plan_ref"]["summary"] == repair_plan["summary"]
    repair_metadata = repaired_custom_json["repair"]
    assert repair_metadata["reference_unit_missing_expected_script"] == {
        "action": "local_repair_then_targeted_vision_recovery",
        "local_repair_source": "same_chunk_provenance_blocks",
        "targeted_vision_recovery": True,
        "preserve_parallel_text": True,
        "expected_scripts": ["arabic"],
        "carry_reference_headers_into_body": True,
    }
    assert repaired_custom_json["reference_resolution"] == {
        "enabled": True,
        "build_canonical_units": True,
        "carry_forward_body_blocks": True,
        "header_only_policy": "provenance_only",
        "continuation_policy": "until_next_reference",
        "max_page_gap": 2,
        "require_single_reference_per_answerable_chunk": True,
        "carry_forward_previous_reference": True,
        "continuation_reference_carry_forward": True,
        "mark_title_front_matter_non_reference_chunks": True,
    }
    assert repaired_custom_json["chunking"]["merge_reference_header_with_body"] is True
    assert repaired_custom_json["chunking"]["preserve_parallel_text"] is True
    assert repaired_custom_json["provenance"] == {
        "preserve_original_blocks": True,
        "block_preview_chars": 160,
        "store_text_hash": True,
    }
    assert repaired_custom_json["reference_schema"] == {
        "type": "chapter_verse",
        "display": "{chapter}:{verse}",
        "canonical_ref_template": "{chapter}:{verse}",
        "fields": {
            "chapter": "surah_number",
            "verse": "ayah_number",
            "page": "page_number",
        },
    }
    assert repair_metadata["reference_unit_unresolved"][
        "carry_forward_previous_reference"
    ] is True
    assert (
        repair_metadata["reference_materialization_blocked"][
            "retry_after_reference_quality_repair"
        ]
        is True
    )
    assert (
        repair_metadata["disallowed_block_type_quarantined"]["action"]
        == "downgrade_layout_noise_or_recover_text_bearing_blocks"
    )
    assert (
        repair_metadata["disallowed_block_type_quarantined"][
            "downgrade_pure_layout_noise"
        ]
        is True
    )
    assert "metadata-aware repair plan" in payload["message"]

    async with app.state.session_factory() as session:
        queued = await session.get(Job, payload["queued_job_id"])
        document = await session.get(Document, "doc-quality-warning-fix")
        chunk = await session.get(Chunk, "chunk-warning-fix")

    assert queued is not None
    assert queued.type == "index_document"
    assert queued.target_id == "doc-quality-warning-fix"
    assert queued.status == StageStatus.READY.value
    assert queued.job_options == payload["index_options"]
    assert queued.result["index_options"] == payload["index_options"]
    queued_custom_json = queued.job_options["domain_metadata"]["custom_json"]
    assert "repair_plan" not in queued_custom_json
    assert queued_custom_json["repair_plan_ref"] == {
        "version": 1,
        "strategy": "metadata_aware_warning_repair",
        "source_job_id": "job-quality-warning-fix",
        "document_id": "doc-quality-warning-fix",
        "warning_counts": repair_plan["warning_counts"],
        "summary": repair_plan["summary"],
    }
    assert queued.result["repair_plan"]["summary"] == repair_plan["summary"]
    assert (
        queued.result["repair_plan"]["ai_suggestion"]["suggestion"]["summary"]
        == "Preserve parallel reference text and recover prose blocks."
    )
    assert document is not None
    assert document.status == StageStatus.RUNNING.value
    assert chunk is not None
    assert chunk.extraction_quality == {"parser_warnings": parser_warnings}


@pytest.mark.asyncio
async def test_fix_job_quality_warnings_rejects_incomplete_index_job(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        document = Document(
            id="doc-running-warning-fix",
            filename="running-warning-fix.pdf",
            content_type="application/pdf",
            sha256="running-warning-fix-sha",
            artifact_path=str(app.state.settings.data_dir / "running-warning-fix.pdf"),
            status=StageStatus.RUNNING.value,
        )
        session.add(document)
        session.add(
            Job(
                id="job-running-warning-fix",
                type="index_document",
                target_id=document.id,
                status=StageStatus.RUNNING.value,
                progress=50,
                logs=[],
                result={},
            )
        )
        await session.commit()

    response = await client.post("/api/jobs/job-running-warning-fix/quality-warnings/fix")

    assert response.status_code == 409
    assert "only be queued after the index job completes" in response.json()["detail"]
    async with app.state.session_factory() as session:
        jobs = (
            await session.execute(
                select(Job).where(
                    Job.type == "index_document",
                    Job.target_id == "doc-running-warning-fix",
                )
            )
        ).scalars().all()
    assert len(jobs) == 1


@pytest.mark.asyncio
async def test_fix_job_quality_warnings_rejects_existing_active_index_job(client):
    app = client._transport.app

    async with app.state.session_factory() as session:
        document = Document(
            id="doc-active-warning-fix",
            filename="active-warning-fix.pdf",
            content_type="application/pdf",
            sha256="active-warning-fix-sha",
            artifact_path=str(app.state.settings.data_dir / "active-warning-fix.pdf"),
            status=StageStatus.RUNNING.value,
        )
        session.add(document)
        session.add_all(
            [
                Job(
                    id="job-completed-warning-fix",
                    type="index_document",
                    target_id=document.id,
                    status=StageStatus.SUCCEEDED.value,
                    progress=100,
                    logs=[],
                    result={"document_id": document.id},
                    job_options={"parser_mode": "mineru_strict", "domain_metadata": {}},
                ),
                Job(
                    id="job-active-warning-fix",
                    type="index_document",
                    target_id=document.id,
                    status=StageStatus.READY.value,
                    progress=0,
                    logs=[],
                    result={},
                    job_options={"parser_mode": "mineru_strict", "domain_metadata": {}},
                ),
            ]
        )
        await session.commit()

    response = await client.post("/api/jobs/job-completed-warning-fix/quality-warnings/fix")

    assert response.status_code == 409
    assert "active indexing job" in response.json()["detail"]
