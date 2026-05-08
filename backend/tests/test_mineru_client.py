import json
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


@pytest.mark.asyncio
async def test_mineru_client_submits_pdf_mime_and_metadata(tmp_path, monkeypatch):
    requests = []
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF fake")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"jobId": "job-1"}

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, files, data):
            requests.append({"url": url, "files": files, "data": data, "timeout": self.timeout})
            return FakeResponse()

    monkeypatch.setattr("ragstudio.services.mineru_client.httpx.AsyncClient", FakeAsyncClient)
    client = MinerUClient(base_url="http://mineru.test", timeout_ms=1000, poll_interval_ms=100)

    job_id = await client.submit_parse(
        pdf_path,
        document_id="doc-1",
        content_type="application/pdf",
        sha256="abc123",
        domain_metadata={"domain": "research"},
    )

    assert job_id == "job-1"
    assert requests[0]["files"]["file"][2] == "application/pdf"
    assert requests[0]["data"]["sha256"] == "abc123"
    metadata = json.loads(requests[0]["data"]["metadata"])
    assert metadata["mimeType"] == "application/pdf"
    assert metadata["domainMetadata"]["domain"] == "research"


@pytest.mark.asyncio
async def test_mineru_client_preserves_files_manifest_page_ranges_and_artifacts(tmp_path):
    artifact_zip = tmp_path / "artifact.zip"
    with ZipFile(artifact_zip, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "sourceId": "doc-1",
                    "sha256": "abc123",
                    "parser": "mineru",
                    "parseMethod": "ocr",
                    "files": [
                        {
                            "path": "pages/page-1.md",
                            "kind": "markdown",
                            "pageStart": 1,
                            "pageEnd": 2,
                        },
                        {"path": "images/page-1.png", "kind": "image"},
                        {"path": "tables/table-1.json", "kind": "json"},
                    ],
                }
            ),
        )
        archive.writestr("pages/page-1.md", "Alpha page text")
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    (extract_dir / "old.md").write_text("stale", encoding="utf-8")

    client = MinerUClient(base_url="http://mineru.test", timeout_ms=1000, poll_interval_ms=100)
    chunks = client.normalize_artifact_zip(
        artifact_zip=artifact_zip,
        extract_dir=extract_dir,
        document_id="doc-1",
        parser_mode="mineru_strict",
        parse_job_id="job-1",
    )

    assert not (extract_dir / "old.md").exists()
    assert chunks[0].source_location == {
        "artifact": "pages/page-1.md",
        "page_start": 1,
        "page_end": 2,
    }
    parser_metadata = chunks[0].metadata["parser_metadata"]
    assert parser_metadata["parse_method"] == "ocr"
    assert parser_metadata["source_id"] == "doc-1"
    assert parser_metadata["sha256"] == "abc123"
    assert parser_metadata["related_artifacts"] == [
        {"path": "images/page-1.png", "kind": "image"},
        {"path": "tables/table-1.json", "kind": "json"},
    ]
