from __future__ import annotations

import asyncio
import json
import shutil
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import httpx
from ragstudio.schemas.parsing import ParserMode
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.http_retry import raise_for_transient_status, retry_async_http


class MinerUArtifactError(RuntimeError):
    pass


@dataclass(frozen=True)
class MinerUJobResult:
    parse_job_id: str
    artifact_zip: Path


@dataclass(frozen=True)
class MinerUParseOptions:
    parser: str = "mineru"
    parse_method: str = "auto"
    backend: str = "pipeline"
    device: str = "cuda:0"
    lang: str | None = None
    formula: bool = True
    table: bool = True
    source: str | None = None
    max_concurrent_files: int = 1

    def to_metadata(self) -> dict[str, Any]:
        parser_kwargs: dict[str, Any] = {
            "backend": self.backend or "pipeline",
            "device": self.device or "cuda:0",
            "formula": self.formula,
            "table": self.table,
        }
        if self.lang:
            parser_kwargs["lang"] = self.lang
        if self.source:
            parser_kwargs["source"] = self.source
        return {
            "parser": self.parser or "mineru",
            "parseMethod": self.parse_method or "auto",
            "parserKwargs": parser_kwargs,
            "maxConcurrentFiles": max(1, min(self.max_concurrent_files, 8)),
        }


@dataclass(frozen=True)
class MinerUSidecarHealth:
    ready: bool
    detail: str
    version: str | None
    hpc_enabled: bool
    hpc_mode: str | None
    raw: dict[str, Any]

    @property
    def is_hpc_coordinator(self) -> bool:
        return self.ready and self.hpc_enabled and self.hpc_mode == "coordinator"

    @property
    def optimization(self) -> dict[str, object]:
        hpc = self.raw.get("hpcMineru")
        if not isinstance(hpc, dict):
            return {}

        result: dict[str, object] = {}
        backend = hpc.get("backend")
        device = hpc.get("device")
        max_concurrent = hpc.get("maxConcurrentFiles")
        if isinstance(backend, str) and backend:
            result["backend"] = backend
        if isinstance(device, str) and device:
            result["device"] = device
        if isinstance(max_concurrent, int) and not isinstance(max_concurrent, bool):
            result["max_concurrent_files"] = max_concurrent
        return result


MinerUStatusCallback = Callable[[dict[str, Any]], Awaitable[None]]

class MinerUClient:
    def __init__(
        self,
        base_url: str,
        timeout_ms: int,
        poll_interval_ms: int,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_ms / 1000
        self.poll_interval_seconds = poll_interval_ms / 1000
        self._http_client = http_client

    async def parse_document(
        self,
        *,
        artifact_path: str | Path,
        document_id: str,
        artifact_dir: Path,
        content_type: str = "application/octet-stream",
        sha256: str | None = None,
        domain_metadata: dict[str, Any] | None = None,
        parse_options: MinerUParseOptions | None = None,
        on_status: MinerUStatusCallback | None = None,
    ) -> MinerUJobResult:
        parse_job_id = await self.submit_parse(
            artifact_path,
            document_id,
            content_type=content_type,
            sha256=sha256,
            domain_metadata=domain_metadata,
            parse_options=parse_options,
        )
        if on_status is not None:
            await on_status({"jobId": parse_job_id, "status": "submitted", "progress": 0})
        ready_job = await self.poll_until_ready(parse_job_id, on_status=on_status)
        artifact_zip = await self.download_artifacts(
            str(ready_job.get("jobId") or parse_job_id),
            artifact_dir / "artifacts.zip",
        )
        return MinerUJobResult(parse_job_id=parse_job_id, artifact_zip=artifact_zip)

    async def submit_parse(
        self,
        artifact_path: str | Path,
        document_id: str,
        *,
        content_type: str = "application/octet-stream",
        sha256: str | None = None,
        domain_metadata: dict[str, Any] | None = None,
        parse_options: MinerUParseOptions | None = None,
    ) -> str:
        path = Path(artifact_path)
        metadata = {
            "mimeType": content_type,
            "domainMetadata": domain_metadata or {},
        }
        if parse_options is not None:
            metadata["ragAnything"] = parse_options.to_metadata()
        form_data = {
            "sourceId": document_id,
            "sourceType": "uploaded_document",
            "title": path.name,
            "metadata": json.dumps(metadata),
        }
        if sha256:
            form_data["sha256"] = sha256
        async with self._client() as client:
            with path.open("rb") as file_obj:
                response = await client.post(
                    f"{self.base_url}/parse-async",
                    files={"file": (path.name, file_obj, content_type)},
                    data=form_data,
                )
        response.raise_for_status()
        payload = response.json()
        return str(payload["jobId"])

    async def poll_parse_job(self, parse_job_id: str) -> dict[str, Any]:
        response = await self._retry_get(
            f"{self.base_url}/parse-jobs/{parse_job_id}",
            attempts=3,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise MinerUArtifactError("MinerU parse status returned non-object JSON.")
        return payload

    async def health(self) -> MinerUSidecarHealth:
        response = await self._retry_get(f"{self.base_url}/health", attempts=3)
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            return MinerUSidecarHealth(
                ready=False,
                detail="MinerU health check returned invalid JSON.",
                version=None,
                hpc_enabled=False,
                hpc_mode=None,
                raw={},
            )
        if not isinstance(payload, dict):
            return MinerUSidecarHealth(
                ready=False,
                detail="MinerU health check returned non-object JSON.",
                version=None,
                hpc_enabled=False,
                hpc_mode=None,
                raw={},
            )
        hpc = payload.get("hpcMineru")
        hpc_payload = hpc if isinstance(hpc, dict) else {}
        return MinerUSidecarHealth(
            ready=bool(payload.get("ready")),
            detail=str(payload.get("detail") or payload.get("status") or ""),
            version=str(payload["version"]) if payload.get("version") is not None else None,
            hpc_enabled=bool(hpc_payload.get("enabled")),
            hpc_mode=str(hpc_payload["mode"]) if hpc_payload.get("mode") is not None else None,
            raw=payload,
        )

    async def poll_until_ready(
        self,
        parse_job_id: str,
        *,
        on_status: MinerUStatusCallback | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            payload = await self.poll_parse_job(parse_job_id)
            if on_status is not None:
                await on_status(payload)
            status = str(payload.get("status") or "").lower()
            if status == "ready":
                return payload
            if status == "failed":
                detail = str(
                    payload.get("error") or payload.get("detail") or "MinerU parse failed."
                )
                raise RuntimeError(detail)
            if time.monotonic() >= deadline:
                raise TimeoutError(f"MinerU parse timed out for job {parse_job_id}.")
            await asyncio.sleep(self.poll_interval_seconds)

    async def download_artifacts(self, parse_job_id: str, target_path: Path) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"{self.base_url}/parse-jobs/{parse_job_id}/artifacts"
        partial_path = target_path.with_name(f"{target_path.name}.part")

        async def download() -> Path:
            if partial_path.exists():
                partial_path.unlink()
            async with self._client() as client:
                async with client.stream("GET", url) as response:
                    raise_for_transient_status(response)
                    response.raise_for_status()
                    with partial_path.open("wb") as fh:
                        async for chunk in response.aiter_bytes(chunk_size=1024 * 256):
                            fh.write(chunk)
            partial_path.replace(target_path)
            return target_path

        return await retry_async_http(download, attempts=3)

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._http_client is not None:
            yield self._http_client
            return
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            yield client

    async def _retry_get(self, url: str, *, attempts: int) -> httpx.Response:
        async with self._client() as client:
            return await retry_async_http(
                lambda: self._get_for_retry(client, url),
                attempts=attempts,
            )

    async def _get_for_retry(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        response = await client.get(url)
        raise_for_transient_status(response)
        return response

    def normalize_artifact_zip(
        self,
        *,
        artifact_zip: Path,
        extract_dir: Path,
        document_id: str,
        parser_mode: ParserMode,
        parse_job_id: str,
    ) -> list[AdapterChunk]:
        self._extract_safe(artifact_zip, extract_dir)
        manifest = self._read_manifest(extract_dir)
        related_artifacts = self._related_artifacts(manifest, extract_dir)
        content_list_ref = self._content_list_ref(manifest, extract_dir)
        chunks: list[AdapterChunk] = []
        for index, item in enumerate(self._manifest_entries(manifest, extract_dir)):
            rel_path = str(item.get("path") or "")
            if not rel_path:
                continue
            artifact_path = self._safe_manifest_path(extract_dir, rel_path)
            if not artifact_path.exists() or artifact_path.is_dir():
                continue
            safe_rel_path = artifact_path.relative_to(extract_dir.resolve()).as_posix()
            text = artifact_path.read_text(encoding="utf-8", errors="replace").strip()
            if not text:
                continue
            source_location: dict[str, Any] = {"artifact": safe_rel_path}
            for source_key, manifest_key in (
                ("page", "pageNumber"),
                ("page", "page"),
                ("page_start", "pageStart"),
                ("page_end", "pageEnd"),
            ):
                page_value = item.get(manifest_key)
                if isinstance(page_value, int):
                    source_location[source_key] = page_value
            parser_metadata = {
                "backend": "mineru",
                "parser_mode": parser_mode,
                "parse_job_id": parse_job_id,
                "parse_method": manifest.get("parseMethod"),
                "source_id": manifest.get("sourceId"),
                "sha256": manifest.get("sha256"),
                "parser": manifest.get("parser"),
                "artifact_ref": safe_rel_path,
                "content_type": str(item.get("contentType") or item.get("kind") or "text"),
                "chunk_index": index,
                "document_id": document_id,
                "related_artifacts": related_artifacts,
            }
            if content_list_ref is not None:
                parser_metadata["artifact_extract_dir"] = str(extract_dir.resolve())
                parser_metadata["content_list_ref"] = content_list_ref
            chunks.append(
                AdapterChunk(
                    text=text,
                    source_location=source_location,
                    metadata={"parser_metadata": parser_metadata},
                )
            )
        return chunks

    def _extract_safe(self, artifact_zip: Path, extract_dir: Path) -> None:
        root = extract_dir.resolve()
        with ZipFile(artifact_zip) as archive:
            for member in archive.infolist():
                target = (extract_dir / member.filename).resolve()
                if root not in target.parents and target != root:
                    raise MinerUArtifactError(f"Unsafe artifact path: {member.filename}")
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            extract_dir.mkdir(parents=True, exist_ok=True)
            archive.extractall(extract_dir)

    def _read_manifest(self, extract_dir: Path) -> dict[str, Any]:
        manifest_path = extract_dir / "manifest.json"
        if not manifest_path.exists():
            return {
                "files": [
                    {"path": path.relative_to(extract_dir).as_posix(), "kind": "markdown"}
                    for path in sorted(extract_dir.rglob("*.md"))
                ]
            }
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def _manifest_entries(
        self,
        manifest: dict[str, Any],
        extract_dir: Path,
    ) -> list[dict[str, Any]]:
        raw_entries = manifest.get("items") or manifest.get("files") or []
        entries = [item for item in raw_entries if isinstance(item, dict)]
        filtered = [item for item in entries if self._is_text_artifact(item)]
        if filtered:
            return filtered
        return [
            {"path": path.relative_to(extract_dir).as_posix(), "kind": "markdown"}
            for path in sorted(extract_dir.rglob("*.md"))
        ]

    def _related_artifacts(
        self,
        manifest: dict[str, Any],
        extract_dir: Path,
    ) -> list[dict[str, str]]:
        raw_entries = [*self._raw_manifest_entries(manifest, "files")]
        raw_entries.extend(self._raw_manifest_entries(manifest, "items"))
        related: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in raw_entries:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "")
            kind = str(item.get("kind") or item.get("contentType") or "")
            if not path or self._is_text_artifact(item) or path == "manifest.json":
                continue
            safe_path = self._safe_manifest_path(extract_dir, path)
            safe_ref = safe_path.relative_to(extract_dir.resolve()).as_posix()
            if safe_ref in seen:
                continue
            seen.add(safe_ref)
            related.append({"path": safe_ref, "kind": kind})
        return related

    def _content_list_ref(self, manifest: dict[str, Any], extract_dir: Path) -> str | None:
        names = {"source_content_list.json", "source_content_list_v2.json"}
        raw_entries = [*self._raw_manifest_entries(manifest, "files")]
        raw_entries.extend(self._raw_manifest_entries(manifest, "items"))
        for item in raw_entries:
            path = str(item.get("path") or "")
            if not path or Path(path).name not in names:
                continue
            safe_path = self._safe_manifest_path(extract_dir, path)
            if safe_path.exists() and safe_path.is_file():
                return safe_path.relative_to(extract_dir.resolve()).as_posix()
        for name in sorted(names):
            matches = sorted(extract_dir.rglob(name))
            for path in matches:
                rel_path = path.resolve().relative_to(extract_dir.resolve()).as_posix()
                safe_path = self._safe_manifest_path(
                    extract_dir,
                    rel_path,
                )
                if safe_path.is_file():
                    return safe_path.relative_to(extract_dir.resolve()).as_posix()
        return None

    def _is_text_artifact(self, item: dict[str, Any]) -> bool:
        path = str(item.get("path") or "").lower()
        kind = str(item.get("contentType") or item.get("kind") or "").lower()
        text_extensions = (".md", ".markdown", ".txt")
        return (
            kind in {"text", "markdown", "md"}
            or kind.startswith("text/")
            or "markdown" in kind
            or path.endswith(text_extensions)
        )

    def _raw_manifest_entries(self, manifest: dict[str, Any], key: str) -> list[dict[str, Any]]:
        value = manifest.get(key)
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _safe_manifest_path(self, extract_dir: Path, rel_path: str) -> Path:
        root = extract_dir.resolve()
        target = (extract_dir / rel_path).resolve()
        if root not in target.parents and target != root:
            raise MinerUArtifactError(f"Unsafe manifest artifact path: {rel_path}")
        return target
