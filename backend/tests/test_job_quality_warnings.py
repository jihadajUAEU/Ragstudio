import pytest
from ragstudio.db.models import Chunk, Document, IndexRecord, Job
from ragstudio.schemas.common import StageStatus


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
