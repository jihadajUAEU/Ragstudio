import json
from collections.abc import Awaitable, Callable
from pathlib import Path, PureWindowsPath
from typing import Any

from ragstudio.db.models import Chunk, Document, IndexRecord
from ragstudio.schemas.chunks import ChunkOut, ChunkSearchIn, ChunkSearchOut
from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn, ParserMode
from ragstudio.services.adapter import AdapterChunk, RAGAnythingAdapter
from ragstudio.services.arabic_text import arabic_tokens, normalize_arabic_text
from ragstudio.services.chunk_lexical_search_repository import ChunkLexicalSearchRepository
from ragstudio.services.chunk_persistence_service import ChunkPersistenceService
from ragstudio.services.chunk_sanitizer import sanitize_db_value
from ragstudio.services.chunk_splitter import ChunkSplitter
from ragstudio.services.document_parser_service import DocumentParserService
from ragstudio.services.domain_metadata_quality_gate import DomainMetadataQualityGate
from ragstudio.services.http_client_provider import HttpClientProviderProtocol
from ragstudio.services.hybrid_chunk_search import ChunkScore, HybridChunkSearch
from ragstudio.services.index_quality_gate import IndexQualityGate
from ragstudio.services.mineru_client import MinerUClient
from ragstudio.services.mineru_relationship_builder import MinerURelationshipBuilder
from ragstudio.services.modal_preprocessor import ModalPreprocessor
from ragstudio.services.reference_metadata import ReferenceSemantics
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

MinerUStatusCallback = Callable[[dict[str, Any]], Awaitable[None]]
_SCRUBBED_DOMAIN_METADATA_VALUE = object()
_UNSAFE_DOMAIN_METADATA_PATH_KEYS = {"artifact_path", "file_path", "path"}
_FALLBACK_SEARCH_CANDIDATE_LIMIT = 100


class ChunkService:
    def __init__(
        self,
        session: AsyncSession,
        data_dir: Path,
        adapter: RAGAnythingAdapter | None = None,
        mineru_client_factory: type[MinerUClient] | None = None,
        chunk_splitter: ChunkSplitter | None = None,
        chunk_search: HybridChunkSearch | None = None,
        relationship_builder: MinerURelationshipBuilder | None = None,
        document_parser: DocumentParserService | None = None,
        quality_gate: IndexQualityGate | None = None,
        http_client_provider: HttpClientProviderProtocol | None = None,
    ):
        self.session = session
        self.data_dir = data_dir
        self.adapter = adapter or RAGAnythingAdapter()
        self.mineru_client_factory = mineru_client_factory or MinerUClient
        self.chunk_splitter = chunk_splitter or ChunkSplitter(
            http_client_provider=http_client_provider
        )
        self.chunk_search = chunk_search or HybridChunkSearch()
        self.relationship_builder = relationship_builder or MinerURelationshipBuilder()
        self.quality_gate = quality_gate or IndexQualityGate()
        self.document_parser = document_parser or DocumentParserService(
            session,
            data_dir,
            local_parser=self.adapter,
            mineru_client_factory=self.mineru_client_factory,
            http_client_provider=http_client_provider,
        )

    async def index_document(
        self,
        document_id: str,
        *,
        options: IndexDocumentIn | None = None,
        artifact_path: str | Path | None = None,
        commit: bool = True,
        on_mineru_status: MinerUStatusCallback | None = None,
    ) -> list[ChunkOut] | None:
        document = await self.session.get(Document, document_id)
        if document is None:
            return None

        options = options or IndexDocumentIn()
        adapter_chunks = await self._adapter_chunks(
            document,
            options,
            artifact_path=artifact_path,
            on_mineru_status=on_mineru_status,
        )
        adapter_chunks = [
            self._chunk_with_parser_metadata(adapter_chunk, options.parser_mode)
            for adapter_chunk in adapter_chunks
        ]
        
        if not self._uses_canonical_reference_units(options.domain_metadata):
            adapter_chunks = ModalPreprocessor().preprocess(
                adapter_chunks,
                domain_metadata=options.domain_metadata,
            )

        adapter_chunks = await self.chunk_splitter.split(
            adapter_chunks,
            domain_metadata=options.domain_metadata,
            parser_mode=options.parser_mode,
        )
        adapter_chunks = self.relationship_builder.annotate(
            adapter_chunks,
            options.domain_metadata,
        )
        self.quality_gate.validate_adapter_chunks(
            adapter_chunks,
            language=self._quality_language(options.domain_metadata),
            domain_metadata=options.domain_metadata,
        )
        chunks = await ChunkPersistenceService(self.session).persist(
            document,
            adapter_chunks,
            options=options,
            commit=commit,
        )
        return [self._chunk_out_with_materialized_metadata(chunk) for chunk in chunks]

    async def _adapter_chunks(
        self,
        document: Document,
        options: IndexDocumentIn,
        *,
        artifact_path: str | Path | None = None,
        on_mineru_status: MinerUStatusCallback | None = None,
    ) -> list[AdapterChunk]:
        return await self.document_parser.parse(
            document,
            options,
            artifact_path=artifact_path,
            on_mineru_status=on_mineru_status,
        )

    async def validate_strict_mineru_sidecar(self, options: IndexDocumentIn) -> None:
        await self.document_parser.validate_strict_mineru_sidecar(options)

    def _uses_canonical_reference_units(self, domain_metadata: DomainMetadata) -> bool:
        return ReferenceSemantics.from_metadata(domain_metadata).canonical_units_enabled

    async def search(self, search_in: ChunkSearchIn) -> ChunkSearchOut:
        limit = max(search_in.limit, 0)
        offset = max(search_in.offset, 0)
        repository = ChunkLexicalSearchRepository(self.session)
        prefilter_limit = max(offset + limit, 100)
        reference_prefiltered = await repository.reference_prefilter(
            query=search_in.query,
            document_ids=search_in.document_ids,
            limit=prefilter_limit,
        )
        if reference_prefiltered:
            chunks = reference_prefiltered
        else:
            english_prefiltered = await repository.english_prefilter(
                query=search_in.query,
                document_ids=search_in.document_ids,
                limit=prefilter_limit,
            )
            arabic_prefiltered = await repository.arabic_prefilter(
                query=search_in.query,
                document_ids=search_in.document_ids,
                limit=prefilter_limit,
            )
            prefiltered_ids = {
                chunk.id for chunk in [*english_prefiltered, *arabic_prefiltered]
            }
            if prefiltered_ids:
                chunks = [*english_prefiltered, *arabic_prefiltered]
                if self._metadata_fallback_requested(search_in):
                    statement = select(Chunk)
                    if search_in.document_ids:
                        statement = statement.where(
                            Chunk.document_id.in_(search_in.document_ids)
                        )
                    result = await self.session.execute(
                        statement.order_by(Chunk.created_at.asc(), Chunk.id.asc())
                        .limit(_FALLBACK_SEARCH_CANDIDATE_LIMIT)
                    )
                    chunks = self._dedupe_chunks([*chunks, *result.scalars().all()])
            else:
                statement = select(Chunk)
                if search_in.document_ids:
                    statement = statement.where(Chunk.document_id.in_(search_in.document_ids))
                result = await self.session.execute(
                    statement.order_by(Chunk.created_at.asc(), Chunk.id.asc())
                    .limit(_FALLBACK_SEARCH_CANDIDATE_LIMIT)
                )
                chunks = list(result.scalars().all())

        ranked = sorted(
            (
                (
                    self.chunk_search.score(
                        search_in.query,
                        chunk,
                        search_weights=(
                            search_in.search_weights.model_dump(exclude_none=True)
                            if search_in.search_weights is not None
                            else None
                        ),
                    ),
                    source_order,
                    chunk,
                )
                for source_order, chunk in enumerate(chunks)
            ),
            key=lambda item: (
                -item[0].score,
                self._source_order(item[2], item[1]),
            ),
        )
        if search_in.query.strip():
            ranked = [item for item in ranked if item[0].score > 0]

        total = len(ranked)
        page = ranked[offset : offset + limit] if limit else []
        items = [
            self._chunk_out_with_score(
                chunk,
                score,
                explain=search_in.explain,
                include_neighbors=search_in.include_neighbors,
            )
            for score, _, chunk in page
        ]
        return ChunkSearchOut(
            items=items,
            total=total,
            has_more=offset + len(items) < total,
        )

    async def chunks_by_id(self, chunk_ids: list[str]) -> list[ChunkOut]:
        unique_ids = list(dict.fromkeys(chunk_id for chunk_id in chunk_ids if chunk_id))
        if not unique_ids:
            return []

        result = await self.session.execute(select(Chunk).where(Chunk.id.in_(unique_ids)))
        chunks_by_id = {chunk.id: chunk for chunk in result.scalars().all()}
        return [
            ChunkOut.model_validate(chunks_by_id[chunk_id])
            for chunk_id in unique_ids
            if chunk_id in chunks_by_id
        ]

    async def domain_metadata_for_documents(
        self,
        document_ids: list[str],
    ) -> list[dict[str, Any]]:
        requested = list(dict.fromkeys(document_id for document_id in document_ids if document_id))
        if not requested:
            return []

        metadata_by_document: dict[str, list[dict[str, Any]]] = {
            document_id: [] for document_id in requested
        }
        seen_by_document: dict[str, set[str]] = {
            document_id: set() for document_id in requested
        }
        document_rows = (
            await self.session.execute(
                select(Document.id, Document.index_contract).where(
                    Document.id.in_(requested)
                )
            )
        ).all()
        for document_id, index_contract in document_rows:
            if not isinstance(index_contract, dict):
                continue
            domain_metadata = index_contract.get("domain_metadata")
            if not isinstance(domain_metadata, dict):
                continue
            metadata_copy = sanitize_db_value(domain_metadata)
            scrubbed_metadata = self._scrub_domain_metadata_lookup_value(metadata_copy)
            if not isinstance(scrubbed_metadata, dict):
                continue
            scrubbed_metadata["document_id"] = document_id
            contract_status = index_contract.get("contract_status")
            if isinstance(contract_status, str):
                scrubbed_metadata["contract_status"] = contract_status
            dedupe_key = json.dumps(
                scrubbed_metadata,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            if dedupe_key in seen_by_document[document_id]:
                continue
            seen_by_document[document_id].add(dedupe_key)
            metadata_by_document[document_id].append(scrubbed_metadata)

        for document_id in requested:
            if metadata_by_document[document_id]:
                continue
            rows = (
                await self.session.execute(
                    select(Chunk.metadata_json)
                    .where(Chunk.document_id == document_id)
                    .order_by(Chunk.created_at.asc(), Chunk.id.asc())
                    .limit(100)
                )
            ).scalars()
            for metadata_json in rows:
                if not isinstance(metadata_json, dict):
                    continue
                domain_metadata = metadata_json.get("domain_metadata")
                if not isinstance(domain_metadata, dict):
                    continue
                metadata_copy = sanitize_db_value(domain_metadata)
                scrubbed_metadata = self._scrub_domain_metadata_lookup_value(metadata_copy)
                if not isinstance(scrubbed_metadata, dict):
                    continue
                dedupe_key = json.dumps(
                    scrubbed_metadata,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
                if dedupe_key in seen_by_document[document_id]:
                    continue
                seen_by_document[document_id].add(dedupe_key)
                metadata_by_document[document_id].append(
                    {
                        **scrubbed_metadata,
                        "document_id": document_id,
                    }
                )
                if len(metadata_by_document[document_id]) >= 5:
                    break

        return [
            metadata
            for document_id in requested
            for metadata in metadata_by_document[document_id]
        ]

    async def quality_reports_for_documents(
        self,
        document_ids: list[str],
    ) -> list[dict[str, Any]]:
        requested = list(dict.fromkeys(document_id for document_id in document_ids if document_id))
        if not requested:
            return []

        gate = getattr(self.quality_gate, "domain_gate", DomainMetadataQualityGate())
        reports_by_document: dict[str, dict[str, Any]] = {}
        records = (
            await self.session.execute(
                select(IndexRecord)
                .where(IndexRecord.document_id.in_(requested))
                .order_by(IndexRecord.created_at.desc(), IndexRecord.id.desc())
            )
        ).scalars()
        for record in records:
            if record.document_id in reports_by_document:
                continue
            index_shape = record.index_shape if isinstance(record.index_shape, dict) else {}
            report = index_shape.get("index_quality_report")
            if isinstance(report, dict) and report.get("quality_report_version"):
                report = dict(report)
                report.setdefault("document_id", record.document_id)
                report.setdefault("runtime_profile_id", record.runtime_profile_id)
                reports_by_document[record.document_id] = report

        missing = [
            document_id
            for document_id in requested
            if document_id not in reports_by_document
        ]
        if missing:
            chunk_rows = (
                await self.session.execute(
                    select(Chunk)
                    .where(Chunk.document_id.in_(missing))
                    .order_by(Chunk.created_at.asc(), Chunk.id.asc())
                )
            ).scalars()
            chunks_by_document: dict[str, list[Chunk]] = {
                document_id: [] for document_id in missing
            }
            for chunk in chunk_rows:
                chunks_by_document.setdefault(chunk.document_id, []).append(chunk)
            for document_id in missing:
                reports_by_document[document_id] = gate.index_quality_report_from_chunks(
                    chunks_by_document.get(document_id, []),
                    document_id=document_id,
                )

        return [reports_by_document[document_id] for document_id in requested]

    def _chunk_out_with_score(
        self,
        chunk: Chunk,
        score: ChunkScore,
        *,
        explain: bool = True,
        include_neighbors: bool = True,
    ) -> ChunkOut:
        output = ChunkOut.model_validate(chunk)
        breakdown = dict(score.breakdown)
        retrieval_explain = breakdown.pop("retrieval_explain", None)
        metadata = {
            **output.metadata,
            "score": score.score,
            "score_breakdown": breakdown,
        }
        self._materialize_search_metadata(output, metadata, chunk)
        if explain and isinstance(retrieval_explain, dict):
            metadata["retrieval_explain"] = retrieval_explain
            output.retrieval_explain = retrieval_explain
            relationship_refs = retrieval_explain.get("relationship_refs")
            if include_neighbors and isinstance(relationship_refs, dict):
                output.relationship_refs = {
                    key: value
                    for key, value in relationship_refs.items()
                    if isinstance(key, str) and isinstance(value, str)
                }
        output.metadata = metadata
        return output

    def _chunk_out_with_materialized_metadata(self, output: ChunkOut) -> ChunkOut:
        metadata = dict(output.metadata)
        self._materialize_search_metadata(output, metadata)
        output.metadata = metadata
        return output

    def _materialize_search_metadata(
        self,
        output: ChunkOut,
        metadata: dict[str, Any],
        chunk: Chunk | None = None,
    ) -> None:
        allows_exact_arabic = self._metadata_allows_exact_arabic(metadata)
        if not allows_exact_arabic:
            metadata["text_search_ar"] = ""
            metadata["tokens_ar"] = []
        elif not metadata.get("text_search_ar"):
            metadata["text_search_ar"] = (
                chunk.text_search_ar if chunk is not None else None
            ) or normalize_arabic_text(output.text)
        if allows_exact_arabic and not metadata.get("tokens_ar"):
            tokens_ar = chunk.tokens_ar if chunk is not None else None
            metadata["tokens_ar"] = tokens_ar or arabic_tokens(output.text)
        if not metadata.get("extraction_quality"):
            metadata["extraction_quality"] = (
                chunk.extraction_quality if chunk is not None else None
            ) or {}

    def _metadata_allows_exact_arabic(self, metadata: dict[str, Any]) -> bool:
        policy = metadata.get("quality_action_policy")
        if not isinstance(policy, dict):
            return True
        return bool(policy.get("index_exact_arabic", True))

    def _safe_metadata(self, metadata: dict[str, Any], document_id: str) -> dict[str, Any]:
        safe = {
            key: value
            for key, value in metadata.items()
            if key not in {"artifact_path", "path", "file_path"}
            and not self._is_absolute_path_value(value)
        }
        safe["document_id"] = document_id
        return sanitize_db_value(safe)

    def _merge_metadata(
        self,
        parser_metadata: dict[str, Any],
        domain_metadata: DomainMetadata,
        parser_mode: ParserMode,
    ) -> dict[str, Any]:
        metadata = dict(parser_metadata)
        metadata["domain_metadata"] = domain_metadata.model_dump(exclude_none=True)
        if "parser_metadata" not in metadata:
            metadata["parser_metadata"] = {
                "backend": metadata.get("backend", "fallback"),
                "parser_mode": parser_mode,
                "artifact_ref": metadata.get("artifact_ref"),
                "chunk_index": metadata.get("chunk_index"),
                "source_type": metadata.get("source_type"),
            }
        metadata.pop("backend", None)
        metadata.pop("artifact_ref", None)
        metadata.pop("chunk_index", None)
        metadata.pop("source_type", None)
        return metadata

    def _extraction_quality(self, metadata: dict[str, Any]) -> dict[str, Any]:
        extraction_quality = metadata.get("extraction_quality")
        if isinstance(extraction_quality, dict):
            return sanitize_db_value(extraction_quality)
        return {}

    def _chunk_with_parser_metadata(
        self,
        chunk: AdapterChunk,
        parser_mode: ParserMode,
    ) -> AdapterChunk:
        if isinstance(chunk.metadata.get("parser_metadata"), dict):
            return chunk

        metadata = dict(chunk.metadata)
        metadata["parser_metadata"] = {
            "backend": metadata.get("backend", "fallback"),
            "parser_mode": parser_mode,
            "artifact_ref": metadata.get("artifact_ref"),
            "chunk_index": metadata.get("chunk_index"),
            "source_type": metadata.get("source_type"),
        }
        return AdapterChunk(
            text=chunk.text,
            source_location=chunk.source_location,
            metadata=metadata,
            runtime_source_id=chunk.runtime_source_id,
            content_type=chunk.content_type,
            preview_ref=chunk.preview_ref,
        )

    def _is_absolute_path_value(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        return Path(value).is_absolute() or PureWindowsPath(value).is_absolute()

    def _scrub_domain_metadata_lookup_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            scrubbed: dict[str, Any] = {}
            for key, item in value.items():
                if self._is_unsafe_domain_metadata_path_key(key):
                    continue
                scrubbed_item = self._scrub_domain_metadata_lookup_value(item)
                if scrubbed_item is _SCRUBBED_DOMAIN_METADATA_VALUE:
                    continue
                scrubbed[key] = scrubbed_item
            return scrubbed
        if isinstance(value, list):
            return [
                scrubbed_item
                for item in value
                if (
                    scrubbed_item := self._scrub_domain_metadata_lookup_value(item)
                )
                is not _SCRUBBED_DOMAIN_METADATA_VALUE
            ]
        if self._is_absolute_path_value(value):
            return _SCRUBBED_DOMAIN_METADATA_VALUE
        return value

    def _is_unsafe_domain_metadata_path_key(self, key: Any) -> bool:
        if not isinstance(key, str):
            return False
        normalized = key.casefold()
        return (
            normalized in _UNSAFE_DOMAIN_METADATA_PATH_KEYS
            or normalized.endswith("_path")
        )

    def _quality_language(self, metadata: DomainMetadata) -> str:
        values = [
            metadata.domain,
            metadata.document_type,
            metadata.collection,
            metadata.content_role,
            *metadata.tags,
        ]
        combined = " ".join(value for value in values if value).casefold()
        if "quran" in combined or "arabic" in combined:
            return "quran"
        return "unknown"

    def _source_order(self, chunk: Chunk, fallback_order: int) -> tuple[int, Any, Any, Any]:
        chunk_index = chunk.metadata_json.get("chunk_index")
        if isinstance(chunk_index, int):
            return (0, chunk_index, chunk.created_at, chunk.id)
        return (1, fallback_order, chunk.created_at, chunk.id)

    def _metadata_fallback_requested(self, search_in: ChunkSearchIn) -> bool:
        if search_in.search_weights is None:
            return False
        weights = search_in.search_weights.model_dump(exclude_none=True)
        for key in (
            "metadata_boost",
            "domain_intent",
            "reference_exact",
            "same_chapter",
            "neighbor_match",
        ):
            value = weights.get(key)
            if isinstance(value, int | float) and value > 0:
                return True
        return False

    def _dedupe_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        by_id: dict[str, Chunk] = {}
        for chunk in chunks:
            by_id.setdefault(chunk.id, chunk)
        return list(by_id.values())
