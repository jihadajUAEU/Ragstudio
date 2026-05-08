from pathlib import Path
from typing import Any

from ragstudio.db.models import Chunk, Document, Job
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.documents import DocumentOut
from ragstudio.schemas.parsing import IndexDocumentIn
from ragstudio.services.artifact_store import ArtifactStore
from ragstudio.services.chunk_service import ChunkService
from ragstudio.services.job_worker import JobWorker
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class DocumentService:
    def __init__(self, session: AsyncSession, data_dir: Path):
        self.session = session
        self.store = ArtifactStore(data_dir)

    async def upload(
        self,
        filename: str,
        content_type: str,
        content: bytes,
        *,
        options: IndexDocumentIn | None = None,
    ) -> DocumentOut:
        digest, artifact_path = self.store.prepare_upload(filename, content)
        existing = await self.session.scalar(select(Document).where(Document.sha256 == digest))
        if existing is not None:
            await self._ensure_indexed(existing, options)
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
            await self.session.flush()
            try:
                await self._index_document_for_job(document, job, options)
            except Exception as exc:
                if not self._should_persist_index_failure(options):
                    raise
                self._mark_index_failed(document, job, exc)
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.session.scalar(select(Document).where(Document.sha256 == digest))
            if existing is not None:
                await self._ensure_indexed(existing, options)
                return DocumentOut.model_validate(existing)
            raise
        except Exception:
            await self.session.rollback()
            raise
        await self.session.refresh(document)
        return DocumentOut.model_validate(document)

    async def list(self) -> list[DocumentOut]:
        result = await self.session.execute(select(Document).order_by(Document.created_at.desc()))
        return [DocumentOut.model_validate(item) for item in result.scalars().all()]

    async def create_index_job(self, document_id: str) -> Job | None:
        document = await self.session.get(Document, document_id)
        if document is None:
            return None
        job = JobWorker.build("index_document", document.id)
        self.session.add(job)
        document.status = StageStatus.RUNNING.value
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def _ensure_indexed(
        self,
        document: Document,
        options: IndexDocumentIn | None = None,
    ) -> None:
        existing_chunk_id = await self.session.scalar(
            select(Chunk.id).where(Chunk.document_id == document.id).limit(1)
        )
        if existing_chunk_id is not None and options is None:
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
            if not self._should_persist_index_failure(options):
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
        job.result = {"document_id": document.id, "chunk_count": chunk_count}
        job.logs = [*job.logs, f"Indexed {chunk_count} chunks."]

    def _should_persist_index_failure(self, options: IndexDocumentIn | None) -> bool:
        return options is not None and options.parser_mode == "mineru_strict"

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
