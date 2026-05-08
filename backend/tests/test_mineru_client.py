from zipfile import ZipFile

import pytest
from ragstudio.services.mineru_client import MinerUArtifactError, MinerUClient


@pytest.mark.asyncio
async def test_mineru_client_parses_artifact_zip(tmp_path):
    artifact_zip = tmp_path / "artifact.zip"
    with ZipFile(artifact_zip, "w") as archive:
        archive.writestr(
            "manifest.json",
            '{"parseMethod":"auto","items":[{"path":"pages/page-1.md","pageNumber":1,"contentType":"text"}]}',
        )
        archive.writestr("pages/page-1.md", "Alpha page text")

    client = MinerUClient(base_url="http://mineru.test", timeout_ms=1000, poll_interval_ms=100)

    chunks = client.normalize_artifact_zip(
        artifact_zip=artifact_zip,
        extract_dir=tmp_path / "extract",
        document_id="doc-1",
        parser_mode="mineru_strict",
        parse_job_id="job-1",
    )

    assert len(chunks) == 1
    assert chunks[0].text == "Alpha page text"
    assert chunks[0].source_location == {"page": 1, "artifact": "pages/page-1.md"}
    assert chunks[0].metadata["parser_metadata"]["backend"] == "mineru"
    assert chunks[0].metadata["parser_metadata"]["content_type"] == "text"
    assert chunks[0].metadata["parser_metadata"]["parse_job_id"] == "job-1"


def test_mineru_client_rejects_unsafe_zip_paths(tmp_path):
    artifact_zip = tmp_path / "unsafe.zip"
    with ZipFile(artifact_zip, "w") as archive:
        archive.writestr("../escape.md", "bad")

    client = MinerUClient(base_url="http://mineru.test", timeout_ms=1000, poll_interval_ms=100)

    with pytest.raises(MinerUArtifactError):
        client.normalize_artifact_zip(
            artifact_zip=artifact_zip,
            extract_dir=tmp_path / "extract",
            document_id="doc-1",
            parser_mode="mineru_strict",
            parse_job_id="job-1",
        )
