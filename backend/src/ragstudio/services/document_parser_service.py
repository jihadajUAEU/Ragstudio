from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
from ragstudio.db.models import Document, SettingsProfile
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.adapter import AdapterChunk, RAGAnythingAdapter
from ragstudio.services.mineru_client import MinerUClient
from ragstudio.services.mineru_extraction_validator import MinerUExtractionValidator
from sqlalchemy.ext.asyncio import AsyncSession

MinerUStatusCallback = Callable[[dict[str, Any]], Awaitable[None]]


class DocumentParserService:
    def __init__(
        self,
        session: AsyncSession,
        data_dir: Path,
        *,
        local_parser: RAGAnythingAdapter | None = None,
        mineru_client_factory: type[MinerUClient] | None = None,
        extraction_validator: MinerUExtractionValidator | None = None,
        commit_before_remote_parse: bool = False,
    ):
        self.session = session
        self.data_dir = data_dir
        self.local_parser = local_parser or RAGAnythingAdapter()
        self.mineru_client_factory = mineru_client_factory or MinerUClient
        self.extraction_validator = extraction_validator or MinerUExtractionValidator()
        self.commit_before_remote_parse = commit_before_remote_parse

    async def parse(
        self,
        document: Document,
        options: IndexDocumentIn,
        *,
        on_mineru_status: MinerUStatusCallback | None = None,
    ) -> list[AdapterChunk]:
        if options.parser_mode != "mineru_strict":
            raise RuntimeError(
                f"Unsupported parser mode for production indexing: {options.parser_mode}"
            )
        return await self.mineru_parse(
            document,
            options,
            on_mineru_status=on_mineru_status,
        )

    async def local_parse(self, document: Document) -> list[AdapterChunk]:
        return await self.local_parser.index_document(document.artifact_path)

    async def local_parse_with_mineru_failure(
        self,
        document: Document,
        options: IndexDocumentIn,
        exc: Exception,
    ) -> list[AdapterChunk]:
        chunks = await self.local_parse(document)
        return [
            AdapterChunk(
                text=chunk.text,
                source_location=chunk.source_location,
                metadata={
                    **chunk.metadata,
                    "parser_metadata": {
                        "backend": "fallback",
                        "parser_mode": options.parser_mode,
                        "mineru_error": str(exc),
                        "fallback_used": True,
                    },
                },
                runtime_source_id=chunk.runtime_source_id,
                content_type=chunk.content_type,
                preview_ref=chunk.preview_ref,
            )
            for chunk in chunks
        ]

    async def validate_strict_mineru_sidecar(self, options: IndexDocumentIn) -> None:
        if options.parser_mode != "mineru_strict":
            raise RuntimeError(
                f"Unsupported parser mode for production indexing: {options.parser_mode}"
            )
        await self.validated_mineru_client()

    async def mineru_parse(
        self,
        document: Document,
        options: IndexDocumentIn,
        *,
        on_mineru_status: MinerUStatusCallback | None = None,
    ) -> list[AdapterChunk]:
        _, client = await self.validated_mineru_client()
        artifact_dir = self.data_dir / "mineru-artifacts" / document.id
        if self.commit_before_remote_parse:
            await self.session.commit()
        job_result = await client.parse_document(
            artifact_path=document.artifact_path,
            document_id=document.id,
            artifact_dir=artifact_dir,
            content_type=document.content_type,
            sha256=document.sha256,
            domain_metadata=options.domain_metadata.model_dump(exclude_none=True),
            on_status=on_mineru_status,
        )
        chunks = client.normalize_artifact_zip(
            artifact_zip=job_result.artifact_zip,
            extract_dir=artifact_dir / "extracted",
            document_id=document.id,
            parser_mode=options.parser_mode,
            parse_job_id=job_result.parse_job_id,
        )
        report = self.extraction_validator.validate(
            chunks,
            expected_language=self._expected_language(options),
        )
        if on_mineru_status is not None:
            await on_mineru_status(
                {
                    "jobId": job_result.parse_job_id,
                    "status": "validated",
                    "chunkCount": report.chunk_count,
                    "characterCount": report.character_count,
                    "pageCount": report.page_count,
                }
            )
        return chunks

    def _expected_language(self, options: IndexDocumentIn) -> str:
        metadata = options.domain_metadata
        for value in (metadata.language, metadata.script):
            if value and value.lower() in {"arabic", "ar"}:
                return "arabic"
        domain = metadata.domain.lower()
        if "quran" in domain or "arabic" in domain:
            return "arabic"
        return metadata.language

    async def validated_mineru_client(self) -> tuple[SettingsProfile, MinerUClient]:
        settings = await self.session.get(SettingsProfile, "default")
        if settings is None or not settings.mineru_base_url:
            raise RuntimeError("MinerU base URL is not configured.")
        if not settings.mineru_enabled:
            raise RuntimeError("MinerU is disabled in settings.")
        client = self.mineru_client_factory(
            base_url=settings.mineru_base_url,
            timeout_ms=settings.mineru_timeout_ms or 14_400_000,
            poll_interval_ms=settings.mineru_poll_interval_ms or 1_000,
        )
        try:
            health = await client.health()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"MinerU health check failed: {exc}") from exc
        if not health.ready:
            raise RuntimeError(health.detail or "MinerU sidecar is not ready.")
        if settings.mineru_require_hpc and not health.is_hpc_coordinator:
            mode = health.hpc_mode or "unknown"
            raise RuntimeError(
                "MinerU sidecar is not in HPC coordinator mode. "
                f"Health detail: {health.detail or 'no detail'}; "
                f"hpcMineru.enabled={health.hpc_enabled}; mode={mode}. "
                "Start the HPC MinerU sidecar/coordinator or disable "
                "'Require HPC MinerU coordinator' in Settings."
            )
        return settings, client
