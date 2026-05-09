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


def test_mineru_client_rejects_unsafe_manifest_paths(tmp_path):
    artifact_zip = tmp_path / "unsafe-manifest.zip"
    with ZipFile(artifact_zip, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({"files": [{"path": "../secret.md", "kind": "markdown"}]}),
        )

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
async def test_mineru_client_health_reports_invalid_json(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("bad json")

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url):
            return FakeResponse()

    monkeypatch.setattr("ragstudio.services.mineru_client.httpx.AsyncClient", FakeAsyncClient)
    client = MinerUClient(base_url="http://mineru.test", timeout_ms=1000, poll_interval_ms=100)

    health = await client.health()

    assert health.ready is False
    assert health.detail == "MinerU health check returned invalid JSON."
    assert health.raw == {}


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


def test_mineru_client_collects_related_artifacts_from_items_manifest(tmp_path):
    artifact_zip = tmp_path / "items.zip"
    with ZipFile(artifact_zip, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "items": [
                        {"path": "pages/page-1.md", "contentType": "text"},
                        {"path": "images/page-1.png", "contentType": "image"},
                    ]
                }
            ),
        )
        archive.writestr("pages/page-1.md", "Alpha")

    client = MinerUClient(base_url="http://mineru.test", timeout_ms=1000, poll_interval_ms=100)
    chunks = client.normalize_artifact_zip(
        artifact_zip=artifact_zip,
        extract_dir=tmp_path / "extract",
        document_id="doc-1",
        parser_mode="mineru_strict",
        parse_job_id="job-1",
    )

    assert chunks[0].metadata["parser_metadata"]["related_artifacts"] == [
        {"path": "images/page-1.png", "kind": "image"}
    ]


def test_mineru_client_collects_related_artifacts_from_files_and_items(tmp_path):
    artifact_zip = tmp_path / "combined.zip"
    with ZipFile(artifact_zip, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "files": [
                        {"path": "tables/table-1.json", "kind": "application/json"},
                        {"path": "images/page-1.png", "kind": "image"},
                    ],
                    "items": [
                        {"path": "pages/page-1.md", "contentType": "text/markdown"},
                        {"path": "pages/page-2.txt", "contentType": "text/plain"},
                        {"path": "images/page-1.png", "contentType": "image/png"},
                    ],
                }
            ),
        )
        archive.writestr("pages/page-1.md", "Alpha")
        archive.writestr("pages/page-2.txt", "Beta")

    client = MinerUClient(base_url="http://mineru.test", timeout_ms=1000, poll_interval_ms=100)
    chunks = client.normalize_artifact_zip(
        artifact_zip=artifact_zip,
        extract_dir=tmp_path / "extract",
        document_id="doc-1",
        parser_mode="mineru_strict",
        parse_job_id="job-1",
    )

    assert [chunk.text for chunk in chunks] == ["Alpha", "Beta"]
    assert chunks[0].metadata["parser_metadata"]["related_artifacts"] == [
        {"path": "tables/table-1.json", "kind": "application/json"},
        {"path": "images/page-1.png", "kind": "image"},
    ]


@pytest.mark.asyncio
async def test_mineru_client_health_reads_hpc_coordinator(monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ready": True,
                "detail": "RAG-Anything sidecar ready",
                "version": "hybrid",
                "hpcMineru": {"enabled": True, "mode": "coordinator"},
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url):
            requests.append({"url": url, "timeout": self.timeout})
            return FakeResponse()

    monkeypatch.setattr("ragstudio.services.mineru_client.httpx.AsyncClient", FakeAsyncClient)

    health = await MinerUClient(
        base_url="http://mineru.test",
        timeout_ms=2000,
        poll_interval_ms=100,
    ).health()

    assert requests == [{"url": "http://mineru.test/health", "timeout": 2.0}]
    assert health.ready is True
    assert health.detail == "RAG-Anything sidecar ready"
    assert health.hpc_enabled is True
    assert health.hpc_mode == "coordinator"
    assert health.is_hpc_coordinator is True


@pytest.mark.asyncio
async def test_mineru_client_health_reads_local_sidecar(monkeypatch):
    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ready": True,
                "detail": "RAG-Anything sidecar ready",
                "hpcMineru": {"enabled": False, "mode": "local"},
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url):
            return FakeResponse()

    monkeypatch.setattr("ragstudio.services.mineru_client.httpx.AsyncClient", FakeAsyncClient)

    health = await MinerUClient(
        base_url="http://mineru.test",
        timeout_ms=2000,
        poll_interval_ms=100,
    ).health()

    assert health.ready is True
    assert health.hpc_enabled is False
    assert health.hpc_mode == "local"
    assert health.is_hpc_coordinator is False
