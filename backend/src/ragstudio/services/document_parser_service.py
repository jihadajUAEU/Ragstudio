from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
from ragstudio.db.models import Document, SettingsProfile
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.adapter import AdapterChunk, RAGAnythingAdapter
from ragstudio.services.mineru_client import MinerUClient, MinerUParseOptions
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
        settings, client = await self.validated_mineru_client()
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
            parse_options=self._mineru_parse_options(settings, options.domain_metadata),
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

    def _mineru_parse_options(
        self,
        settings: SettingsProfile,
        domain_metadata: Any | None = None,
    ) -> MinerUParseOptions:
        mineru_formula = getattr(settings, "mineru_formula", None)
        mineru_table = getattr(settings, "mineru_table", None)
        options = MinerUParseOptions(
            parser=getattr(settings, "parser", None) or "mineru",
            parse_method=getattr(settings, "parse_method", None) or "auto",
            backend=getattr(settings, "mineru_backend", None) or "pipeline",
            device=getattr(settings, "mineru_device", None) or "cuda:0",
            lang=getattr(settings, "mineru_lang", None),
            formula=True if mineru_formula is None else bool(mineru_formula),
            table=True if mineru_table is None else bool(mineru_table),
            source=getattr(settings, "mineru_source", None),
            max_concurrent_files=getattr(settings, "mineru_max_concurrent_files", None) or 1,
        )
        overrides = self._mineru_parse_overrides(domain_metadata)
        if overrides:
            options = replace(options, **overrides)

        metadata_defaults = self._metadata_inferred_mineru_overrides(
            domain_metadata,
            explicit_keys=set(overrides),
            current=options,
        )
        if metadata_defaults:
            options = replace(options, **metadata_defaults)
        return options

    def _mineru_parse_overrides(self, domain_metadata: Any | None) -> dict[str, Any]:
        custom_json = getattr(domain_metadata, "custom_json", None)
        if not isinstance(custom_json, dict):
            return {}
        raw = custom_json.get("mineru_parse_options")
        if not isinstance(raw, dict):
            return {}

        overrides: dict[str, Any] = {}
        for key in ("parser", "parse_method", "backend", "device", "lang", "source"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                overrides[key] = value.strip()
        for key in ("formula", "table"):
            value = raw.get(key)
            if isinstance(value, bool):
                overrides[key] = value
        max_concurrent_files = raw.get("max_concurrent_files")
        if isinstance(max_concurrent_files, int) and not isinstance(max_concurrent_files, bool):
            overrides["max_concurrent_files"] = max(1, min(max_concurrent_files, 8))
        return overrides

    def _metadata_inferred_mineru_overrides(
        self,
        domain_metadata: Any | None,
        *,
        explicit_keys: set[str],
        current: MinerUParseOptions,
    ) -> dict[str, Any]:
        if domain_metadata is None or not self._metadata_prefers_arabic_ocr(domain_metadata):
            return {}

        inferred: dict[str, Any] = {}
        if "lang" not in explicit_keys and not current.lang:
            inferred["lang"] = "arabic"
        if "parse_method" not in explicit_keys and current.parse_method == "auto":
            inferred["parse_method"] = "ocr"
        if "formula" not in explicit_keys:
            inferred["formula"] = False
        if "table" not in explicit_keys and not self._metadata_mentions_tables(domain_metadata):
            inferred["table"] = False
        return inferred

    def _metadata_prefers_arabic_ocr(self, domain_metadata: Any) -> bool:
        custom_json = getattr(domain_metadata, "custom_json", None)
        parser_normalization = (
            custom_json.get("parser_normalization")
            if isinstance(custom_json, dict)
            else None
        )
        equations_as_content = (
            parser_normalization.get("allow_equations_as_content")
            if isinstance(parser_normalization, dict)
            else None
        )
        tokens = self._metadata_tokens(domain_metadata)
        return (
            "arabic" in tokens
            and bool(tokens & {"quran", "tafseer", "hadith", "islamic", "religious_text"})
            and equations_as_content is not True
        )

    def _metadata_mentions_tables(self, domain_metadata: Any) -> bool:
        return bool(self._metadata_tokens(domain_metadata) & {"table", "tables", "spreadsheet"})

    def _metadata_tokens(self, domain_metadata: Any) -> set[str]:
        values: list[str] = []
        for field in (
            "domain",
            "document_type",
            "language",
            "script",
            "content_role",
            "expected_structure",
        ):
            value = getattr(domain_metadata, field, None)
            if isinstance(value, str):
                values.extend(value.replace("-", "_").split("_"))
                values.append(value)
        tags = getattr(domain_metadata, "tags", None)
        if isinstance(tags, list):
            values.extend(tag for tag in tags if isinstance(tag, str))
        return {value.strip().casefold() for value in values if value.strip()}

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
