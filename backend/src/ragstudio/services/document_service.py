from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError
from ragstudio.config import AppSettings
from ragstudio.db.models import Chunk, Document, GraphProjectionRecord, IndexRecord, Job
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.documents import DocumentOut
from ragstudio.schemas.parsing import DomainMetadata, IndexDocumentIn, ParserMode
from ragstudio.schemas.runtime import RuntimeProfile
from ragstudio.services.artifact_store import ArtifactStore
from ragstudio.services.chunk_service import ChunkService
from ragstudio.services.graph_projection_runner import GraphProjectionRunner
from ragstudio.services.index_lifecycle_service import (
    IndexLifecycleService,
    RuntimeHealthBlockedError,
)
from ragstudio.services.job_worker import JobWorker
from ragstudio.services.runtime_factory import RuntimeUnavailableError
from ragstudio.services.runtime_profile_service import (
    RuntimeProfileNotConfiguredError,
    RuntimeProfileService,
)
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

DeleteDocumentResult = Literal["deleted", "not_found"]


class ActiveIndexJobError(RuntimeError):
    pass


class DocumentService:
    def __init__(self, session: AsyncSession, data_dir: Path, settings: AppSettings | None = None):
        self.session = session
        self.store = ArtifactStore(data_dir)
        self.settings = settings
        self.queued_index_job_id: str | None = None

    async def upload(
        self,
        filename: str,
        content_type: str,
        content: bytes,
        *,
        options: IndexDocumentIn | None = None,
        index_immediately: bool = True,
    ) -> DocumentOut:
        digest, artifact_path = self.store.prepare_upload(filename, content)
        existing = await self.session.scalar(select(Document).where(Document.sha256 == digest))
        if existing is not None:
            if index_immediately:
                await self._ensure_indexed(existing, options)
            else:
                await self._ensure_queued_index_job(existing, options)
            return DocumentOut.model_validate(existing)

        _, artifact_path = self.store.write_upload(filename, content)
        document = Document(
            filename=filename,
            content_type=content_type,
            sha256=digest,
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        self.session.add(document)
        try:
            await self.session.flush()
            job = JobWorker.build("index_document", document.id)
            self.session.add(job)
            self.queued_index_job_id = job.id
            await self.session.flush()
            if index_immediately:
                try:
                    await self._index_document_for_job(document, job, options)
                except Exception as exc:
                    if not self._should_persist_index_failure(options, exc):
                        raise
                    self._mark_index_failed(document, job, exc)
            else:
                document.status = StageStatus.RUNNING.value
                job.logs = [*(job.logs or []), "Indexing queued."]
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.session.scalar(select(Document).where(Document.sha256 == digest))
            if existing is not None:
                if index_immediately:
                    await self._ensure_indexed(existing, options)
                else:
                    await self._ensure_queued_index_job(existing, options)
                return DocumentOut.model_validate(existing)
            raise
        except Exception:
            await self.session.rollback()
            raise
        await self.session.refresh(document)
        return DocumentOut.model_validate(document)

    async def list(self) -> list[DocumentOut]:
        result = await self.session.execute(select(Document).order_by(Document.created_at.desc()))
        documents = list(result.scalars().all())
        latest_options = await self._latest_index_options_by_document(
            [document.id for document in documents]
        )
        outputs = []
        for document in documents:
            output = DocumentOut.model_validate(document)
            output.latest_index_options = latest_options.get(document.id)
            outputs.append(output)
        return outputs

    async def document_exists(self, document_id: str) -> bool:
        return await self.session.get(Document, document_id) is not None

    async def active_index_job(self, document_id: str) -> Job | None:
        return await self.session.scalar(
            select(Job)
            .where(
                Job.type == "index_document",
                Job.target_id == document_id,
                Job.status.in_([StageStatus.READY.value, StageStatus.RUNNING.value]),
            )
            .order_by(Job.created_at.desc())
            .limit(1)
        )

    async def delete_document(self, document_id: str) -> DeleteDocumentResult:
        document = await self.session.get(Document, document_id)
        if document is None:
            return "not_found"

        artifact_path = Path(document.artifact_path)
        try:
            if self.settings is not None:
                await GraphProjectionRunner(
                    self.session,
                    self.settings,
                ).delete_document_graph(document.id)
            else:
                await self.session.execute(
                    delete(GraphProjectionRecord).where(
                        GraphProjectionRecord.document_id == document.id
                    )
                )
            await self.session.execute(
                delete(Job).where(Job.type == "index_document", Job.target_id == document.id)
            )
            await self.session.execute(
                delete(IndexRecord).where(IndexRecord.document_id == document.id)
            )
            artifact_path.unlink(missing_ok=True)
            await self.session.delete(document)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return "deleted"

    async def create_index_job(self, document_id: str) -> Job | None:
        document = await self.session.get(Document, document_id)
        if document is None:
            return None
        if await self.active_index_job(document_id) is not None:
            raise ActiveIndexJobError("Document already has an active indexing job")
        return await self._enqueue_index_job(document)

    async def latest_index_job(self, document_id: str) -> Job | None:
        return await self.session.scalar(
            select(Job)
            .where(Job.type == "index_document", Job.target_id == document_id)
            .order_by(Job.created_at.desc())
            .limit(1)
        )

    async def mark_index_job_failed(
        self,
        document_id: str,
        job_id: str,
        reason: str,
    ) -> None:
        document = await self.session.get(Document, document_id)
        job = await self.session.get(Job, job_id)
        if document is not None:
            document.status = StageStatus.FAILED.value
        if job is not None:
            job.status = StageStatus.FAILED.value
            job.progress = 100
            job.logs = [*(job.logs or []), reason]
            job.result = {**(job.result or {}), "document_id": document_id, "error": reason}
        await self.session.commit()

    async def _enqueue_index_job(self, document: Document) -> Job:
        job = JobWorker.build("index_document", document.id)
        self.session.add(job)
        document.status = StageStatus.RUNNING.value
        self.queued_index_job_id = job.id
        job.logs = [*(job.logs or []), "Indexing queued."]
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ActiveIndexJobError("Document already has an active indexing job") from exc
        await self.session.refresh(document)
        await self.session.refresh(job)
        return job

    async def _latest_index_options_by_document(
        self,
        document_ids: list[str],
    ) -> dict[str, IndexDocumentIn]:
        if not document_ids:
            return {}

        ranked_chunks = (
            select(
                Chunk.document_id.label("document_id"),
                Chunk.metadata_json.label("metadata_json"),
                func.row_number()
                .over(
                    partition_by=Chunk.document_id,
                    order_by=(Chunk.created_at.desc(), Chunk.id.desc()),
                )
                .label("rank"),
            )
            .where(Chunk.document_id.in_(document_ids))
            .subquery()
        )
        result = await self.session.execute(
            select(ranked_chunks.c.document_id, ranked_chunks.c.metadata_json).where(
                ranked_chunks.c.rank == 1
            )
        )

        options: dict[str, IndexDocumentIn] = {}
        for document_id, metadata in result.all():
            latest = self._index_options_from_metadata(metadata)
            if latest is not None:
                options[document_id] = latest
        return options

    def _index_options_from_metadata(self, metadata: Any) -> IndexDocumentIn | None:
        if not isinstance(metadata, dict):
            return None
        parser_metadata = metadata.get("parser_metadata")
        domain_metadata = metadata.get("domain_metadata")
        parser_mode = self._parser_mode_from_metadata(parser_metadata)
        if parser_mode is None:
            return None

        try:
            metadata_model = (
                DomainMetadata.model_validate(domain_metadata)
                if isinstance(domain_metadata, dict)
                else DomainMetadata()
            )
        except ValidationError:
            metadata_model = DomainMetadata()
        return IndexDocumentIn(parser_mode=parser_mode, domain_metadata=metadata_model)

    def _parser_mode_from_metadata(self, parser_metadata: Any) -> ParserMode | None:
        if not isinstance(parser_metadata, dict):
            return None

        parser_mode = parser_metadata.get("parser_mode")
        if parser_mode in {"local_fallback", "mineru_strict", "mineru_with_fallback"}:
            return parser_mode

        backend = parser_metadata.get("backend")
        if backend == "mineru":
            return "mineru_strict"
        if parser_metadata.get("fallback_used") is True:
            return "mineru_with_fallback"
        if backend == "fallback":
            return "local_fallback"
        return None

    async def _ensure_queued_index_job(
        self,
        document: Document,
        options: IndexDocumentIn | None,
    ) -> None:
        if await self.active_index_job(document.id) is not None:
            self.queued_index_job_id = None
            return
        if options is None:
            existing_chunk_id = await self.session.scalar(
                select(Chunk.id).where(Chunk.document_id == document.id).limit(1)
            )
            if existing_chunk_id is not None:
                return

        await self._enqueue_index_job(document)

    async def _ensure_indexed(
        self,
        document: Document,
        options: IndexDocumentIn | None = None,
    ) -> None:
        existing_chunk_id = await self.session.scalar(
            select(Chunk.id).where(Chunk.document_id == document.id).limit(1)
        )
        if existing_chunk_id is not None and options is None:
            profile = await self._active_runtime_profile()
            if profile is None or profile.runtime_mode == "fallback":
                return
            if await self._has_ready_runtime_index(document.id, profile):
                return

        job = JobWorker.build("index_document", document.id)
        add_job = True
        if options is None:
            existing_job = await self.session.scalar(
                select(Job)
                .where(Job.type == "index_document", Job.target_id == document.id)
                .order_by(Job.created_at.desc())
                .limit(1)
            )
            if existing_job is not None:
                job = existing_job
                add_job = False
        if add_job:
            self.session.add(job)
            await self.session.flush()
        try:
            await self._index_document_for_job(document, job, options)
        except Exception as exc:
            if not self._should_persist_index_failure(options, exc):
                raise
            self._mark_index_failed(document, job, exc)
        await self.session.commit()
        await self.session.refresh(document)

    async def _index_document_for_job(
        self,
        document: Document,
        job: Job,
        options: IndexDocumentIn | None = None,
        on_mineru_status=None,
    ) -> None:
        job.status = StageStatus.RUNNING.value
        job.progress = 50
        job.logs = [*job.logs, "Indexing document chunks."]
        profile = await self._active_runtime_profile()
        graph_materialization: dict[str, Any] = {}
        if profile is not None and profile.runtime_mode != "fallback":
            assert self.settings is not None
            lifecycle_result = await IndexLifecycleService(
                self.session,
                self.settings,
            ).reindex_document(
                document.id,
                options=options,
                on_mineru_status=on_mineru_status,
            )
            chunks = lifecycle_result.chunks if lifecycle_result is not None else []
            graph_materialization = (
                dict(lifecycle_result.graph_materialization)
                if lifecycle_result is not None
                else {}
            )
        else:
            chunks = await ChunkService(self.session, self.store.root).index_document(
                document.id,
                options=options,
                commit=False,
                on_mineru_status=on_mineru_status,
            )
        chunk_count = len(chunks or [])
        document.status = StageStatus.SUCCEEDED.value
        job.status = StageStatus.SUCCEEDED.value
        job.progress = 100
        job.result = {
            **job.result,
            "document_id": document.id,
            "chunk_count": chunk_count,
            "graph_materialization": graph_materialization,
        }
        job.logs = [*job.logs, f"Indexed {chunk_count} chunks."]
        if graph_materialization.get("status") == "pending" and self.settings is not None:
            await self.session.commit()
            graph_materialization = await GraphProjectionRunner(
                self.session,
                self.settings,
            ).materialize_pending(document.id)
            job.result = {
                **job.result,
                "graph_materialization": graph_materialization,
            }
            status = str(graph_materialization.get("status") or "unknown")
            job.logs = [*job.logs, f"Graph projection materialization {status}."]

    async def _active_runtime_profile(self) -> RuntimeProfile | None:
        if self.settings is None:
            return None
        try:
            return await RuntimeProfileService(
                self.session,
                self.settings,
            ).get_active_profile()
        except RuntimeProfileNotConfiguredError:
            return None

    async def _has_ready_runtime_index(
        self,
        document_id: str,
        profile: RuntimeProfile,
    ) -> bool:
        result = await self.session.execute(
            select(IndexRecord).where(
                IndexRecord.document_id == document_id,
                IndexRecord.runtime_profile_id == profile.id,
                IndexRecord.status == StageStatus.SUCCEEDED.value,
            )
        )
        return any(
            record.index_shape == profile.index_shape for record in result.scalars().all()
        )

    def _should_persist_index_failure(
        self,
        options: IndexDocumentIn | None,
        exc: Exception,
    ) -> bool:
        return (
            not self._is_runtime_blocker(exc)
            and options is not None
            and options.parser_mode == "mineru_strict"
        )

    def _is_runtime_blocker(self, exc: Exception) -> bool:
        return isinstance(exc, (RuntimeHealthBlockedError, RuntimeUnavailableError))

    def _mark_index_failed(self, document: Document, job: Job, exc: Exception) -> None:
        document.status = StageStatus.FAILED.value
        job.status = StageStatus.FAILED.value
        job.progress = 100
        job.logs = [*job.logs, str(exc)]
        job.result = {"document_id": document.id, "error": str(exc)}

    async def run_index_job(
        self,
        document_id: str,
        job_id: str,
        options: IndexDocumentIn,
    ) -> None:
        document = await self.session.get(Document, document_id)
        job = await self.session.get(Job, job_id)
        if document is None or job is None:
            return

        async def on_mineru_status(payload: dict[str, Any]) -> None:
            status = str(payload.get("status") or "unknown")
            progress_value = payload.get("progress")
            progress = progress_value if isinstance(progress_value, int) else None
            remote_job_id = payload.get("jobId")
            detail = str(payload.get("detail") or status)
            job.result = {
                **job.result,
                "mineru": {
                    "job_id": str(remote_job_id) if remote_job_id else None,
                    "status": status,
                    "progress": progress,
                    "detail": detail,
                    "updated_at": payload.get("updatedAt"),
                },
            }
            if progress is not None:
                job.progress = max(1, min(progress, 99))
            job.logs = [*job.logs, f"MinerU {status}: {detail}"][-20:]
            await self.session.commit()

        try:
            job.status = StageStatus.RUNNING.value
            job.progress = max(job.progress, 1)
            job.logs = [*job.logs, "Indexing document chunks."]
            document.status = StageStatus.RUNNING.value
            await self.session.commit()
            await self._index_document_for_job(
                document,
                job,
                options,
                on_mineru_status=on_mineru_status,
            )
            await self.session.commit()
        except Exception as exc:
            document.status = StageStatus.FAILED.value
            job.status = StageStatus.FAILED.value
            job.progress = 100
            job.logs = [*job.logs, str(exc)]
            job.result = {**job.result, "document_id": document.id, "error": str(exc)}
            await self.session.commit()
