from __future__ import annotations

from pathlib import Path

import pytest
from ragstudio.db.models import Chunk, Document
from ragstudio.schemas.common import StageStatus
from ragstudio.services.document_parse_evidence_service import DocumentParseEvidenceService


@pytest.mark.asyncio
async def test_parse_evidence_groups_page_stitch_decision(client, tmp_path: Path):
    artifact = tmp_path / "source.pdf"
    artifact.write_bytes(b"%PDF synthetic")
    async with client._transport.app.state.session_factory() as session:
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
                        {
                            "block_id": "block-1",
                            "page": 1,
                            "block_index": 0,
                            "text": "This paragraph starts on page one and",
                        },
                        {
                            "block_id": "block-2",
                            "page": 2,
                            "block_index": 1,
                            "text": "continues on page two before ending.",
                        },
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
async def test_parse_evidence_groups_modal_and_warning_decisions(client, tmp_path: Path):
    artifact = tmp_path / "source.pdf"
    artifact.write_bytes(b"%PDF synthetic")
    async with client._transport.app.state.session_factory() as session:
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
                    {
                        "code": "table_recovered",
                        "message": "Table extracted from MinerU content list.",
                        "page": 3,
                    }
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
async def test_parse_evidence_redacts_unsafe_artifact_values(client, tmp_path: Path):
    artifact = tmp_path / "private" / "secret.pdf"
    artifact.parent.mkdir()
    artifact.write_bytes(b"%PDF synthetic")
    async with client._transport.app.state.session_factory() as session:
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
