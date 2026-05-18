from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from ragstudio.db.models import Chunk, Document
from ragstudio.schemas.document_parse_evidence import (
    ChunkEvidence,
    DocumentEvidenceSummary,
    DocumentParseEvidence,
    NormalizationDecisionEvidence,
    ProofEvidence,
)
from ragstudio.schemas.common import StageStatus
from ragstudio.services.document_parse_evidence_exporter import (
    DocumentParseEvidenceExporter,
    UnsafeProofExportError,
)
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

        evidence = await DocumentParseEvidenceService(
            session,
            source_commit="test-commit",
        ).get_document_evidence("doc-stitch")

    assert evidence.document.id == "doc-stitch"
    assert evidence.document.filename == "synthetic.pdf"
    assert evidence.normalization_decisions[0].decision_type == "page_stitch"
    assert evidence.normalization_decisions[0].input_block_ids == ["block-1", "block-2"]
    assert evidence.normalization_decisions[0].output_chunk_ids == ["chunk-stitch"]
    assert evidence.chunks[0].page_start == 1
    assert evidence.chunks[0].page_end == 2
    assert any("document.artifact_path" in entry for entry in evidence.proof.redaction_summary)
    assert evidence.proof.source_commit == "test-commit"
    assert evidence.proof.proof_packet_id == "local-document-parse-evidence"
    assert evidence.proof.replay_command == "./scripts/proof.sh --fixtures static-fixtures"


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

        evidence = await DocumentParseEvidenceService(
            session,
            source_commit="test-commit",
        ).get_document_evidence("doc-modal")

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

        evidence = await DocumentParseEvidenceService(
            session,
            source_commit="test-commit",
        ).get_document_evidence("doc-redact")

    serialized = evidence.model_dump_json()
    assert str(tmp_path) not in serialized
    assert "10.0.0.5" not in serialized
    assert "internal.local" not in serialized
    assert "sk-secret" not in serialized
    assert evidence.proof.redaction_summary
    assert any("document.artifact_path" in entry for entry in evidence.proof.redaction_summary)
    assert any("source_location.artifact" in entry for entry in evidence.proof.redaction_summary)


@pytest.mark.asyncio
async def test_parse_evidence_preserves_safe_public_urls(client, tmp_path: Path):
    artifact = tmp_path / "public-url.pdf"
    artifact.write_bytes(b"%PDF synthetic")
    async with client._transport.app.state.session_factory() as session:
        session.add(
            Document(
                id="doc-public-url",
                filename="public-url.pdf",
                content_type="application/pdf",
                sha256="sha-public-url",
                artifact_path=str(artifact),
                status=StageStatus.SUCCEEDED.value,
            )
        )
        session.add(
            Chunk(
                id="chunk-public-url",
                document_id="doc-public-url",
                text="Safe public URL https://example.com/v1 should survive redaction.",
                source_location={"page": 1, "url": "https://example.com/v1"},
                metadata_json={"public_url": "https://example.com/v1"},
                extraction_quality={},
            )
        )
        await session.commit()

        evidence = await DocumentParseEvidenceService(
            session,
            source_commit="test-commit",
        ).get_document_evidence("doc-public-url")

    serialized = evidence.model_dump_json()
    assert "https://example.com/v1" in serialized


@pytest.mark.asyncio
async def test_parse_evidence_redacts_secret_query_params_but_preserves_public_url_host_and_path(
    client,
    tmp_path: Path,
):
    artifact = tmp_path / "public-query.pdf"
    artifact.write_bytes(b"%PDF synthetic")
    public_url = "https://api.example.com/v1?api_key=plain-secret-123&ok=true"
    async with client._transport.app.state.session_factory() as session:
        session.add(
            Document(
                id="doc-public-query",
                filename="public-query.pdf",
                content_type="application/pdf",
                sha256="sha-public-query",
                artifact_path=str(artifact),
                status=StageStatus.SUCCEEDED.value,
            )
        )
        session.add(
            Chunk(
                id="chunk-public-query",
                document_id="doc-public-query",
                text=f"Safe public URL with secret query {public_url}",
                source_location={"page": 1, "url": public_url},
                metadata_json={"provider_url": public_url},
                extraction_quality={},
            )
        )
        await session.commit()

        evidence = await DocumentParseEvidenceService(
            session,
            source_commit="test-commit",
        ).get_document_evidence("doc-public-query")

    serialized = evidence.model_dump_json()
    assert "plain-secret-123" not in serialized
    assert "api_key=plain-secret-123" not in serialized
    assert "https://api.example.com/v1" in serialized
    assert "ok=true" in serialized
    assert any(".query.api_key" in entry for entry in evidence.proof.redaction_summary)


@pytest.mark.asyncio
async def test_parse_evidence_redacts_public_url_userinfo_but_preserves_public_host_and_path(
    client,
    tmp_path: Path,
):
    artifact = tmp_path / "userinfo-url.pdf"
    artifact.write_bytes(b"%PDF synthetic")
    userinfo_secret_url = "https://user:sk-secret@example.com/v1?ok=true"
    userinfo_password_url = "https://user:password@example.com/v1"
    async with client._transport.app.state.session_factory() as session:
        session.add(
            Document(
                id="doc-userinfo-url",
                filename="userinfo-url.pdf",
                content_type="application/pdf",
                sha256="sha-userinfo-url",
                artifact_path=str(artifact),
                status=StageStatus.SUCCEEDED.value,
            )
        )
        session.add(
            Chunk(
                id="chunk-userinfo-url",
                document_id="doc-userinfo-url",
                text="Public URLs with userinfo should be sanitized.",
                source_location={"page": 1, "url": userinfo_secret_url},
                metadata_json={"provider_url": userinfo_password_url},
                extraction_quality={},
            )
        )
        await session.commit()

        evidence = await DocumentParseEvidenceService(
            session,
            source_commit="test-commit",
        ).get_document_evidence("doc-userinfo-url")

    serialized = evidence.model_dump_json()
    assert "sk-secret" not in serialized
    assert "password@example.com" not in serialized
    assert "user:" not in serialized
    assert "https://example.com/v1" in serialized
    assert any(".userinfo" in entry for entry in evidence.proof.redaction_summary)


@pytest.mark.asyncio
async def test_parse_evidence_redacts_secret_public_url_path_segments(client, tmp_path: Path):
    artifact = tmp_path / "public-path-secret.pdf"
    artifact.write_bytes(b"%PDF synthetic")
    public_url = "https://example.com/sk-secret/path"
    async with client._transport.app.state.session_factory() as session:
        session.add(
            Document(
                id="doc-public-path-secret",
                filename="public-path-secret.pdf",
                content_type="application/pdf",
                sha256="sha-public-path-secret",
                artifact_path=str(artifact),
                status=StageStatus.SUCCEEDED.value,
            )
        )
        session.add(
            Chunk(
                id="chunk-public-path-secret",
                document_id="doc-public-path-secret",
                text=f"Public URL with secret path segment {public_url}",
                source_location={"page": 1, "url": public_url},
                metadata_json={"public_url": public_url},
                extraction_quality={},
            )
        )
        await session.commit()

        evidence = await DocumentParseEvidenceService(
            session,
            source_commit="test-commit",
        ).get_document_evidence("doc-public-path-secret")

    serialized = evidence.model_dump_json()
    assert "https://example.com/sk-secret/path" not in serialized
    assert "sk-secret" not in serialized
    assert "https://example.com/[redacted-secret]/path" in serialized
    assert any(".path." in entry for entry in evidence.proof.redaction_summary)


@pytest.mark.asyncio
async def test_parse_evidence_redacts_percent_encoded_secret_public_url_path_segments(
    client,
    tmp_path: Path,
):
    artifact = tmp_path / "public-path-encoded-secret.pdf"
    artifact.write_bytes(b"%PDF synthetic")
    public_url = "https://example.com/%73k-secret/path"
    metadata_url = "https://example.com/%73%6b-secret/path"
    async with client._transport.app.state.session_factory() as session:
        session.add(
            Document(
                id="doc-public-path-encoded-secret",
                filename="public-path-encoded-secret.pdf",
                content_type="application/pdf",
                sha256="sha-public-path-encoded-secret",
                artifact_path=str(artifact),
                status=StageStatus.SUCCEEDED.value,
            )
        )
        session.add(
            Chunk(
                id="chunk-public-path-encoded-secret",
                document_id="doc-public-path-encoded-secret",
                text=f"Encoded public URL path secret {public_url}",
                source_location={"page": 1, "url": public_url},
                metadata_json={"public_url": metadata_url},
                extraction_quality={},
            )
        )
        await session.commit()

        evidence = await DocumentParseEvidenceService(
            session,
            source_commit="test-commit",
        ).get_document_evidence("doc-public-path-encoded-secret")

    serialized = evidence.model_dump_json()
    assert "%73k-secret" not in serialized
    assert "%73%6b-secret" not in serialized
    assert "sk-secret" not in serialized
    assert "https://example.com/[redacted-secret]/path" in serialized
    assert any(".path." in entry for entry in evidence.proof.redaction_summary)


@pytest.mark.asyncio
async def test_parse_evidence_handles_malformed_public_url_ports_without_throwing(client, tmp_path: Path):
    artifact = tmp_path / "malformed-port.pdf"
    artifact.write_bytes(b"%PDF synthetic")
    malformed_url = "https://user:pw@example.com:bad/v1"
    async with client._transport.app.state.session_factory() as session:
        session.add(
            Document(
                id="doc-malformed-port",
                filename="malformed-port.pdf",
                content_type="application/pdf",
                sha256="sha-malformed-port",
                artifact_path=str(artifact),
                status=StageStatus.SUCCEEDED.value,
            )
        )
        session.add(
            Chunk(
                id="chunk-malformed-port",
                document_id="doc-malformed-port",
                text=f"Malformed public URL {malformed_url}",
                source_location={"page": 1, "url": malformed_url},
                metadata_json={"provider_url": malformed_url},
                extraction_quality={},
            )
        )
        await session.commit()

        evidence = await DocumentParseEvidenceService(
            session,
            source_commit="test-commit",
        ).get_document_evidence("doc-malformed-port")

    serialized = evidence.model_dump_json()
    assert "user:" not in serialized
    assert "pw@" not in serialized
    assert "example.com" in serialized
    assert "/v1" in serialized
    assert any(".port" in entry or ".userinfo" in entry for entry in evidence.proof.redaction_summary)


@pytest.mark.asyncio
async def test_parse_evidence_marks_missing_sections_for_document_without_chunks(client, tmp_path: Path):
    artifact = tmp_path / "empty.pdf"
    artifact.write_bytes(b"%PDF synthetic")
    async with client._transport.app.state.session_factory() as session:
        session.add(
            Document(
                id="doc-empty",
                filename="empty.pdf",
                content_type="application/pdf",
                sha256="sha-empty",
                artifact_path=str(artifact),
                status=StageStatus.READY.value,
            )
        )
        await session.commit()

        evidence = await DocumentParseEvidenceService(
            session,
            source_commit="test-commit",
        ).get_document_evidence("doc-empty")

    assert evidence.chunks == []
    assert evidence.parser_blocks == []
    assert evidence.normalization_decisions == []
    assert evidence.missing_sections == ["chunks", "parser_blocks", "normalization_decisions"]
    assert "No chunks have been materialized for this document." in evidence.proof.limitations


@pytest.mark.asyncio
async def test_parse_evidence_links_warning_to_block_and_decision_when_page_is_known(
    client,
    tmp_path: Path,
):
    artifact = tmp_path / "warning-link.pdf"
    artifact.write_bytes(b"%PDF synthetic")
    async with client._transport.app.state.session_factory() as session:
        document = Document(
            id="doc-warning-link",
            filename="warning-link.pdf",
            content_type="application/pdf",
            sha256="sha-warning-link",
            artifact_path=str(artifact),
            status=StageStatus.SUCCEEDED.value,
        )
        chunk = Chunk(
            id="chunk-warning-link",
            document_id="doc-warning-link",
            text="Heading\n\nBody block on page eight.",
            source_location={"page_start": 7, "page_end": 8, "artifact": "source_content_list.json"},
            metadata_json={
                "parser_metadata": {"content_list_ref": "source_content_list.json"},
                "split": {
                    "source_blocks": [
                        {
                            "block_id": "block-heading",
                            "page": 7,
                            "block_index": 0,
                            "block_type": "heading",
                            "text": "Heading",
                        },
                        {
                            "block_id": "block-body",
                            "page": 8,
                            "block_index": 1,
                            "block_type": "text",
                            "text": "Body block on page eight.",
                        },
                    ]
                },
            },
            extraction_quality={
                "quality_status": "warning",
                "parser_warnings": [
                    {
                        "code": "body_truncated",
                        "message": "Page body was truncated during parse recovery.",
                        "severity": "error",
                        "page": 8,
                    }
                ],
            },
        )
        session.add_all([document, chunk])
        await session.commit()

        evidence = await DocumentParseEvidenceService(
            session,
            source_commit="test-commit",
        ).get_document_evidence("doc-warning-link")

    warning = evidence.warnings[0]
    decision = next(
        item for item in evidence.normalization_decisions if item.decision_type == "quality_warning"
    )
    body_block = next(block for block in evidence.parser_blocks if block.id == "block-body")
    heading_block = next(block for block in evidence.parser_blocks if block.id == "block-heading")

    assert warning.severity == "error"
    assert warning.page == 8
    assert warning.block_id == "block-body"
    assert warning.decision_id == decision.id
    assert body_block.warning_ids == [warning.id]
    assert heading_block.warning_ids == []


@pytest.mark.asyncio
async def test_parse_evidence_counts_distinct_observed_pages_not_max_page_number(client, tmp_path: Path):
    artifact = tmp_path / "page-312.pdf"
    artifact.write_bytes(b"%PDF synthetic")
    async with client._transport.app.state.session_factory() as session:
        session.add(
            Document(
                id="doc-page-count",
                filename="page-312.pdf",
                content_type="application/pdf",
                sha256="sha-page-count",
                artifact_path=str(artifact),
                status=StageStatus.SUCCEEDED.value,
            )
        )
        session.add(
            Chunk(
                id="chunk-page-count",
                document_id="doc-page-count",
                text="Observed only one page.",
                source_location={"page": 312},
                metadata_json={},
                extraction_quality={},
            )
        )
        await session.commit()

        evidence = await DocumentParseEvidenceService(
            session,
            source_commit="test-commit",
        ).get_document_evidence("doc-page-count")

    assert evidence.document.page_count == 1


@pytest.mark.asyncio
async def test_parse_evidence_redacts_embedded_private_urls_ipv6_and_root_paths(client, tmp_path: Path):
    artifact = tmp_path / "network-private.pdf"
    artifact.write_bytes(b"%PDF synthetic")
    async with client._transport.app.state.session_factory() as session:
        session.add(
            Document(
                id="doc-network-private",
                filename="network-private.pdf",
                content_type="application/pdf",
                sha256="sha-network-private",
                artifact_path="/var/private/file.pdf",
                status=StageStatus.SUCCEEDED.value,
            )
        )
        session.add(
            Chunk(
                id="chunk-network-private",
                document_id="doc-network-private",
                text=(
                    "prefix http://10.0.0.5/private suffix and http://[::1]:8000/v1 and "
                    "http://[fd00::1]/v1 plus /secret and /var/private/file.pdf and "
                    "\\\\server\\share\\secret.pdf"
                ),
                source_location={
                    "page": 1,
                    "url_loopback_v6": "http://[::1]:8000/v1",
                    "url_private_v6": "http://[fd00::1]/v1",
                    "embedded_private_url": "prefix http://10.0.0.5/private suffix",
                    "root_path": "/secret",
                    "unix_path": "/var/private/file.pdf",
                    "unc_path": "\\\\server\\share\\secret.pdf",
                },
                metadata_json={
                    "provider_url": "prefix http://10.0.0.5/private suffix",
                    "cache_url": "http://[::1]:8000/v1",
                    "private_v6": "http://[fd00::1]/v1",
                    "root_path_hint": "/secret",
                    "export_path": "/var/private/file.pdf",
                    "network_share": "\\\\server\\share\\secret.pdf",
                },
                extraction_quality={},
            )
        )
        await session.commit()

        evidence = await DocumentParseEvidenceService(
            session,
            source_commit="test-commit",
        ).get_document_evidence("doc-network-private")

    serialized = evidence.model_dump_json()
    for unsafe in (
        "http://[::1]:8000/v1",
        "http://[fd00::1]/v1",
        "http://10.0.0.5/private",
        "/secret",
        "/var/private/file.pdf",
        "\\\\server\\share\\secret.pdf",
    ):
        assert unsafe not in serialized
    assert any("private host" in entry for entry in evidence.proof.redaction_summary)
    assert any("local path" in entry for entry in evidence.proof.redaction_summary)


@pytest.mark.asyncio
async def test_parse_evidence_redacts_secret_shaped_artifact_basenames(client):
    async with client._transport.app.state.session_factory() as session:
        session.add(
            Document(
                id="doc-secret-basename",
                filename="secret-basename.pdf",
                content_type="application/pdf",
                sha256="sha-secret-basename",
                artifact_path="/tmp/sk-secret.json",
                status=StageStatus.SUCCEEDED.value,
            )
        )
        session.add(
            Chunk(
                id="chunk-secret-basename",
                document_id="doc-secret-basename",
                text="Secret basename should not leak.",
                source_location={"page": 1},
                metadata_json={},
                extraction_quality={},
            )
        )
        await session.commit()

        evidence = await DocumentParseEvidenceService(
            session,
            source_commit="test-commit",
        ).get_document_evidence("doc-secret-basename")

    serialized = evidence.model_dump_json()
    assert "sk-secret.json" not in serialized
    assert any("document.artifact_path.basename" in entry for entry in evidence.proof.redaction_summary)


@pytest.mark.asyncio
async def test_parse_evidence_route_returns_404_for_missing_document(client):
    response = await client.get("/api/documents/missing-doc/parse-evidence")

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"


@pytest.mark.asyncio
async def test_parse_evidence_route_returns_contract(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    app = client._transport.app
    monkeypatch.setenv("RAGSTUDIO_SOURCE_COMMIT", "env-commit")
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
    assert body["proof"]["proof_packet_id"] == "local-document-parse-evidence"
    assert body["proof"]["source_commit"] == "env-commit"


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
    assert '"replay_command":"./scripts/proof.sh --fixtures static-fixtures"' in exported
    assert output.bytes_written == len(exported.encode("utf-8"))


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


@pytest.mark.parametrize(
    ("text_preview", "expected_message"),
    [
        ("ghp_abcdefghijklmnopqrstuvwxyz123456", "secret-shaped value"),
        ("Bearer abc.def.ghi", "secret-shaped value"),
        ("Authorization: Bearer secret", "secret-shaped value"),
        ("http://0.0.0.0:8000/private", "private host"),
    ],
)
def test_document_parse_evidence_exporter_rejects_additional_unsafe_values(
    tmp_path: Path,
    text_preview: str,
    expected_message: str,
):
    evidence = DocumentParseEvidence(
        document=DocumentEvidenceSummary(
            id="doc-unsafe",
            filename="unsafe.pdf",
            content_type="application/pdf",
            status="succeeded",
        ),
        chunks=[ChunkEvidence(id="chunk-unsafe", text_preview=text_preview)],
        proof=ProofEvidence(mode="local"),
    )

    with pytest.raises(UnsafeProofExportError, match=expected_message):
        DocumentParseEvidenceExporter().export(
            evidence,
            packet_dir=tmp_path,
            proof_packet_id="packet",
            source_commit="abc1234",
        )


def test_document_parse_evidence_manifest_registers_fixture_artifact():
    repo_root = Path(__file__).resolve().parents[2]
    manifest_path = repo_root / "docs/benchmarks/ragstudio-oss-proof-v1/manifest.json"
    artifact_relative_path = "artifacts/document-parse-evidence.export.json"
    artifact_path = manifest_path.parent / artifact_relative_path

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert artifact_relative_path in manifest["artifacts"]
    assert artifact_path.exists()

    artifact_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    hash_entry = manifest["artifact_hashes"][artifact_relative_path]
    assert hash_entry["algorithm"] == "sha256"
    assert hash_entry["value"] == artifact_hash
    assert hash_entry["redaction_status"] == "passed"
