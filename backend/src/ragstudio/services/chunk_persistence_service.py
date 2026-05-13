from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Any

from ragstudio.db.models import Chunk, Document
from ragstudio.schemas.chunks import ChunkOut
from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn, ParserMode
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.arabic_text import arabic_tokens, normalize_arabic_text
from ragstudio.services.chunk_sanitizer import sanitize_db_text, sanitize_db_value
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

_SCRUBBED_PATH = object()


class ChunkPersistenceService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def persist(
        self,
        document: Document,
        adapter_chunks: list[AdapterChunk],
        options: IndexDocumentIn,
        *,
        commit: bool = True,
        runtime_profile_id: str | None = None,
        index_shape: dict[str, Any] | None = None,
    ) -> list[ChunkOut]:
        await self.session.execute(delete(Chunk).where(Chunk.document_id == document.id))
        indexed_at = datetime.now(UTC)
        chunks = [
            self._chunk_row(
                document,
                adapter_chunk,
                options=options,
                indexed_at=indexed_at,
                runtime_profile_id=runtime_profile_id,
                index_shape=index_shape or {},
            )
            for adapter_chunk in adapter_chunks
        ]
        self.session.add_all(chunks)
        if commit:
            await self.session.commit()
        else:
            await self.session.flush()
        for chunk in chunks:
            await self.session.refresh(chunk)
        return [ChunkOut.model_validate(chunk) for chunk in chunks]

    def _chunk_row(
        self,
        document: Document,
        adapter_chunk: AdapterChunk,
        *,
        options: IndexDocumentIn,
        indexed_at: datetime,
        runtime_profile_id: str | None,
        index_shape: dict[str, Any],
    ) -> Chunk:
        text = sanitize_db_text(adapter_chunk.text)
        metadata = self._merge_metadata(
            adapter_chunk.metadata,
            options.domain_metadata,
            options.parser_mode,
            options.mineru_parse_options.model_dump(mode="json", exclude_none=True)
            if options.mineru_parse_options is not None
            else None,
            document.id,
            index_shape,
        )
        return Chunk(
            document_id=document.id,
            text=text,
            text_search_ar=normalize_arabic_text(text)
            if self._index_exact_arabic(metadata)
            else "",
            tokens_ar=arabic_tokens(text) if self._index_exact_arabic(metadata) else [],
            extraction_quality=self._extraction_quality(metadata),
            source_location=sanitize_db_value(adapter_chunk.source_location),
            metadata_json=sanitize_db_value(metadata),
            runtime_profile_id=sanitize_db_value(runtime_profile_id),
            runtime_source_id=sanitize_db_value(
                self._direct_or_metadata(
                    adapter_chunk.runtime_source_id,
                    adapter_chunk.metadata.get("runtime_source_id"),
                )
            ),
            content_type=sanitize_db_text(
                str(
                    self._direct_or_metadata(
                        adapter_chunk.content_type,
                        adapter_chunk.metadata.get("content_type"),
                        default="text",
                    )
                )
            ),
            preview_ref=sanitize_db_value(
                self._preview_ref(adapter_chunk.preview_ref, metadata.get("preview_ref"))
            ),
            indexed_at=indexed_at,
        )

    def _merge_metadata(
        self,
        metadata: dict[str, Any],
        domain_metadata: DomainMetadata,
        parser_mode: ParserMode,
        mineru_parse_options: dict[str, Any] | None,
        document_id: str,
        index_shape: dict[str, Any],
    ) -> dict[str, Any]:
        merged = self._scrub_path_metadata(metadata)
        merged["document_id"] = document_id
        merged["domain_metadata"] = domain_metadata.model_dump(exclude_none=True)
        merged["index_shape"] = index_shape
        merged["chunk_identity"] = self._chunk_identity(document_id, merged)
        parser_metadata = dict(merged.get("parser_metadata") or {})
        parser_metadata.setdefault("backend", "mineru")
        parser_metadata["parser_mode"] = parser_mode
        if mineru_parse_options is not None:
            parser_metadata["mineru_parse_options"] = mineru_parse_options
        merged["parser_metadata"] = parser_metadata
        return merged

    def _extraction_quality(self, metadata: dict[str, Any]) -> dict[str, Any]:
        extraction_quality = metadata.get("extraction_quality")
        if isinstance(extraction_quality, dict):
            return sanitize_db_value(extraction_quality)
        return {}

    def _index_exact_arabic(self, metadata: dict[str, Any]) -> bool:
        policy = metadata.get("quality_action_policy")
        if not isinstance(policy, dict):
            return True
        return bool(policy.get("index_exact_arabic", True))

    def _is_absolute_path_value(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        return Path(value).is_absolute() or PureWindowsPath(value).is_absolute()

    def _scrub_path_metadata(self, value: Any) -> Any:
        if isinstance(value, dict):
            scrubbed: dict[str, Any] = {}
            for key, item in value.items():
                if key in {"artifact_path", "path", "file_path"}:
                    continue
                scrubbed_item = self._scrub_path_metadata(item)
                if scrubbed_item is _SCRUBBED_PATH:
                    continue
                scrubbed[key] = scrubbed_item
            return scrubbed
        if isinstance(value, list):
            return [
                scrubbed_item
                for item in value
                if (scrubbed_item := self._scrub_path_metadata(item)) is not _SCRUBBED_PATH
            ]
        if self._is_absolute_path_value(value):
            return _SCRUBBED_PATH
        return value

    def _direct_or_metadata(
        self,
        direct_value: Any,
        metadata_value: Any,
        *,
        default: Any = None,
    ) -> Any:
        if direct_value not in (None, ""):
            return direct_value
        if metadata_value not in (None, ""):
            return metadata_value
        return default

    def _preview_ref(self, direct_value: Any, metadata_value: Any) -> Any:
        direct_preview = self._scrub_path_metadata(direct_value)
        if direct_preview is _SCRUBBED_PATH:
            direct_preview = None
        return self._direct_or_metadata(direct_preview, metadata_value)

    def _chunk_identity(self, document_id: str, metadata: dict[str, Any]) -> str:
        parser_metadata = metadata.get("parser_metadata") or {}
        artifact_ref = parser_metadata.get("artifact_ref")
        chunk_index = parser_metadata.get("chunk_index")
        preview_ref = metadata.get("preview_ref")
        return "|".join(str(part) for part in (document_id, artifact_ref, preview_ref, chunk_index))
