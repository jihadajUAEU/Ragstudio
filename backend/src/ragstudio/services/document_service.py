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
from ragstudio.services.index_artifact_cleanup import cleanup_document_index_artifacts
from ragstudio.services.index_lifecycle_service import (
    IndexLifecycleService,
    RuntimeHealthBlockedError,
)
from ragstudio.services.index_progress import (
    IndexStage,
    index_shape_compatible,
    update_job_stage,
)
from ragstudio.services.job_worker import JobWorker
from ragstudio.services.runtime_factory import RuntimeUnavailableError
from ragstudio.services.runtime_profile_service import (
    RuntimeProfileNotConfiguredError,
    RuntimeProfileService,
)
from sqlalchemy import delete, func, select, text
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
            job = JobWorker.build(
                "index_document",
                document.id,
                options=self._job_options_payload(options),
            )
            self.session.add(job)
            self.queued_index_job_id = job.id
            await self.session.flush()
            if index_immediately:
                try:
                    await self._index_document_for_job(document, job, options)
                except Exception as exc:
                    if not self._should_persist_index_failure(options, exc):
                        raise
                    await self._mark_index_failed(document, job, exc)
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

    async def create_index_job(
        self,
        document_id: str,
        options: IndexDocumentIn | None = None,
    ) -> Job | None:
        await self.lock_document_workflow(document_id)
        document = await self.session.get(Document, document_id)
        if document is None:
            return None
        if await self.active_index_job(document_id) is not None:
            raise ActiveIndexJobError("Document already has an active indexing job")
        return await self._enqueue_index_job(document, options)

    async def lock_document_workflow(self, document_id: str) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"ragstudio:document:{document_id}"},
        )

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

    async def _enqueue_index_job(
        self,
        document: Document,
        options: IndexDocumentIn | None = None,
    ) -> Job:
        job = JobWorker.build(
            "index_document",
            document.id,
            options=self._job_options_payload(options),
        )
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
        if parser_mode == "mineru_strict":
            return parser_mode

        backend = parser_metadata.get("backend")
        if backend == "mineru":
            return "mineru_strict"
        return None

    def _job_options_payload(self, options: IndexDocumentIn | None) -> dict[str, Any]:
        return (options or IndexDocumentIn()).model_dump(mode="json", exclude_none=True)

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

        await self._enqueue_index_job(document, options)

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

        job = JobWorker.build(
            "index_document",
            document.id,
            options=self._job_options_payload(options),
        )
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
            await self._mark_index_failed(document, job, exc)
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

            async def on_stage(
                stage: IndexStage,
                *,
                detail: str,
                chunk_count: int | None = None,
            ) -> None:
                update_job_stage(job, stage, detail=detail, chunk_count=chunk_count)
                await self.session.commit()

            lifecycle_result = await IndexLifecycleService(
                self.session,
                self.settings,
            ).reindex_document(
                document.id,
                options=options,
                on_mineru_status=on_mineru_status,
                on_stage=on_stage,
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
        parser_quality = self._parser_quality_summary(chunks or [])
        parser_warning = self._parser_quality_warning(parser_quality)
        document.status = StageStatus.SUCCEEDED.value
        job.status = StageStatus.SUCCEEDED.value
        job.progress = 100
        job.result = {
            **job.result,
            "document_id": document.id,
            "chunk_count": chunk_count,
            "graph_materialization": graph_materialization,
            "parser_quality": parser_quality,
        }
        job.logs = [*job.logs, f"Indexed {chunk_count} chunks."]
        if parser_warning:
            job.logs = [*job.logs, f"Parser quality warnings: {parser_warning}"]
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
        graph_warning = self._graph_materialization_warning(graph_materialization)
        warning_entries = [item for item in (graph_warning, parser_warning) if item]
        combined_warning = "; ".join(warning_entries) if warning_entries else None
        if graph_warning:
            job.logs = [*(job.logs or []), f"Ready with warnings: {graph_warning}"]
        update_job_stage(
            job,
            IndexStage.READY_WITH_WARNINGS if combined_warning else IndexStage.READY,
            detail=(
                f"Indexed {chunk_count} chunks with warnings."
                if combined_warning
                else f"Indexed {chunk_count} chunks."
            ),
            chunk_count=chunk_count,
        )
        self._record_warning_entries(
            job,
            warning_entries,
            stage_warning=combined_warning,
        )

    def _record_warning_entries(
        self,
        job: Job,
        warnings: list[str],
        *,
        stage_warning: str | None = None,
    ) -> None:
        if not warnings and not stage_warning:
            return
        result = dict(job.result or {})
        if stage_warning and isinstance(result.get("indexing_stage"), dict):
            indexing_stage = dict(result["indexing_stage"])
            indexing_stage["warning"] = stage_warning
            result["indexing_stage"] = indexing_stage
        warning_entries = list(result.get("warnings") or [])
        for warning in warnings:
            if warning not in warning_entries:
                warning_entries.append(warning)
        if warning_entries:
            result["warnings"] = warning_entries
        job.result = result

    def _parser_quality_summary(self, chunks: list[Any]) -> dict[str, Any]:
        warning_counts: dict[str, int] = {}
        affected_chunks = 0
        for chunk in chunks:
            codes = sorted(set(self._parser_warning_codes(chunk)))
            if not codes:
                continue
            affected_chunks += 1
            for code in codes:
                warning_counts[code] = warning_counts.get(code, 0) + 1
        return {
            "warning_counts": dict(sorted(warning_counts.items())),
            "affected_chunks": affected_chunks,
        }

    def _parser_warning_codes(self, chunk: Any) -> list[str]:
        extraction_quality = getattr(chunk, "extraction_quality", None)
        if not isinstance(extraction_quality, dict):
            metadata = getattr(chunk, "metadata", None)
            if isinstance(metadata, dict):
                extraction_quality = metadata.get("extraction_quality")
        if not isinstance(extraction_quality, dict):
            return []
        warnings = extraction_quality.get("parser_warnings")
        if not isinstance(warnings, list):
            return []
        codes: list[str] = []
        for warning in warnings:
            if not isinstance(warning, dict):
                continue
            code = warning.get("code")
            if isinstance(code, str) and code:
                codes.append(code)
        return codes

    def _parser_quality_warning(self, parser_quality: dict[str, Any]) -> str | None:
        warning_counts = parser_quality.get("warning_counts")
        if not isinstance(warning_counts, dict) or not warning_counts:
            return None
        return ", ".join(
            f"{code}={count}"
            for code, count in warning_counts.items()
            if isinstance(code, str) and isinstance(count, int)
        )

    def _graph_materialization_warning(self, graph_materialization: dict[str, Any]) -> str | None:
        status = graph_materialization.get("status")
        if status not in {"failed", "skipped"}:
            return None
        fallback = f"Graph materialization {status}."
        return str(
            graph_materialization.get("reason")
            or graph_materialization.get("error")
            or fallback
        )

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
            index_shape_compatible(record.index_shape, profile.index_shape)
            for record in result.scalars().all()
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

    async def _mark_index_failed(self, document: Document, job: Job, exc: Exception) -> None:
        await cleanup_document_index_artifacts(self.session, document.id)
        document.status = StageStatus.FAILED.value
        job.status = StageStatus.FAILED.value
        job.progress = 100
        job.logs = [*(job.logs or []), str(exc)]
        job.result = self._index_failure_result(document, job, exc)

    def _index_failure_result(
        self,
        document: Document,
        job: Job,
        exc: Exception,
    ) -> dict[str, Any]:
        detail = str(exc)
        return {
            **(job.result or {}),
            "document_id": document.id,
            "error": detail,
            "indexing_stage": {
                "stage": "failed",
                "label": "Failed",
                "detail": detail,
                "progress": 100,
            },
        }

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
            result = job.result or {}
            existing_mineru = result.get("mineru")
            mineru = dict(existing_mineru) if isinstance(existing_mineru, dict) else {}

            status_payload = payload.get("status")
            if status_payload is not None:
                mineru["status"] = str(status_payload)
            status = str(mineru.get("status") or "unknown")

            progress_value = payload.get("progress")
            if isinstance(progress_value, int):
                mineru["progress"] = progress_value
                progress = progress_value
            else:
                progress = None

            remote_job_id = payload.get("jobId")
            if remote_job_id is not None:
                mineru["job_id"] = str(remote_job_id)

            detail_payload = payload.get("detail")
            if detail_payload is not None:
                mineru["detail"] = str(detail_payload)
            detail = str(mineru.get("detail") or status)

            updated_at = payload.get("updatedAt")
            if updated_at is not None:
                mineru["updated_at"] = updated_at

            for payload_key, result_key in (
                ("chunkCount", "chunk_count"),
                ("characterCount", "character_count"),
                ("pageCount", "page_count"),
                ("error", "error"),
            ):
                value = payload.get(payload_key)
                if value is not None:
                    mineru[result_key] = value

            job.result = {**result, "mineru": mineru}
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
            await cleanup_document_index_artifacts(self.session, document.id)
            document.status = StageStatus.FAILED.value
            job.status = StageStatus.FAILED.value
            job.progress = 100
            job.logs = [*(job.logs or []), str(exc)]
            job.result = self._index_failure_result(document, job, exc)
            await self.session.commit()
