from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import httpx

from ragstudio.schemas.parsing import ParserMode
from ragstudio.services.adapter import AdapterChunk


class MinerUArtifactError(RuntimeError):
    pass


@dataclass(frozen=True)
class MinerUJobResult:
    parse_job_id: str
    artifact_zip: Path


class MinerUClient:
    def __init__(self, base_url: str, timeout_ms: int, poll_interval_ms: int):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_ms / 1000
        self.poll_interval_seconds = poll_interval_ms / 1000

    async def parse_document(
        self,
        *,
        artifact_path: str | Path,
        document_id: str,
        artifact_dir: Path,
    ) -> MinerUJobResult:
        parse_job_id = await self.submit_parse(artifact_path, document_id)
        ready_job = await self.poll_until_ready(parse_job_id)
        artifact_zip = await self.download_artifacts(
            str(ready_job.get("jobId") or parse_job_id),
            artifact_dir / "artifacts.zip",
        )
        return MinerUJobResult(parse_job_id=parse_job_id, artifact_zip=artifact_zip)

    async def submit_parse(self, artifact_path: str | Path, document_id: str) -> str:
        path = Path(artifact_path)
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            with path.open("rb") as file_obj:
                response = await client.post(
                    f"{self.base_url}/parse-async",
                    files={"file": (path.name, file_obj, "application/octet-stream")},
                    data={
                        "sourceId": document_id,
                        "sourceType": "uploaded_document",
                        "title": path.name,
                    },
                )
        response.raise_for_status()
        payload = response.json()
        return str(payload["jobId"])

    async def poll_parse_job(self, parse_job_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(f"{self.base_url}/parse-jobs/{parse_job_id}")
        response.raise_for_status()
        return response.json()

    async def poll_until_ready(self, parse_job_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            payload = await self.poll_parse_job(parse_job_id)
            status = str(payload.get("status") or "").lower()
            if status == "ready":
                return payload
            if status == "failed":
                detail = str(payload.get("error") or payload.get("detail") or "MinerU parse failed.")
                raise RuntimeError(detail)
            if time.monotonic() >= deadline:
                raise TimeoutError(f"MinerU parse timed out for job {parse_job_id}.")
            await asyncio.sleep(self.poll_interval_seconds)

    async def download_artifacts(self, parse_job_id: str, target_path: Path) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(f"{self.base_url}/parse-jobs/{parse_job_id}/artifacts")
        response.raise_for_status()
        target_path.write_bytes(response.content)
        return target_path

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
        chunks: list[AdapterChunk] = []
        for index, item in enumerate(self._manifest_entries(manifest, extract_dir)):
            rel_path = str(item.get("path") or "")
            if not rel_path:
                continue
            artifact_path = extract_dir / rel_path
            if not artifact_path.exists() or artifact_path.is_dir():
                continue
            text = artifact_path.read_text(encoding="utf-8", errors="replace").strip()
            if not text:
                continue
            page_number = item.get("pageNumber") or item.get("page")
            source_location: dict[str, Any] = {"artifact": rel_path}
            if isinstance(page_number, int):
                source_location["page"] = page_number
            chunks.append(
                AdapterChunk(
                    text=text,
                    source_location=source_location,
                    metadata={
                        "parser_metadata": {
                            "backend": "mineru",
                            "parser_mode": parser_mode,
                            "parse_job_id": parse_job_id,
                            "artifact_ref": rel_path,
                            "content_type": str(
                                item.get("contentType") or item.get("kind") or "text"
                            ),
                            "chunk_index": index,
                            "document_id": document_id,
                        }
                    },
                )
            )
        return chunks

    def _extract_safe(self, artifact_zip: Path, extract_dir: Path) -> None:
        extract_dir.mkdir(parents=True, exist_ok=True)
        root = extract_dir.resolve()
        with ZipFile(artifact_zip) as archive:
            for member in archive.infolist():
                target = (extract_dir / member.filename).resolve()
                if root not in target.parents and target != root:
                    raise MinerUArtifactError(f"Unsafe artifact path: {member.filename}")
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
        text_kinds = {"text", "markdown", "md"}
        filtered = [
            item
            for item in entries
            if str(item.get("contentType") or item.get("kind") or "").lower() in text_kinds
        ]
        if filtered:
            return filtered
        return [
            {"path": path.relative_to(extract_dir).as_posix(), "kind": "markdown"}
            for path in sorted(extract_dir.rglob("*.md"))
        ]
