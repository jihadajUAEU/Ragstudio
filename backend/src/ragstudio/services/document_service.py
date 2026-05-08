from pathlib import Path

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
                document.status = StageStatus.FAILED.value
                job.status = StageStatus.FAILED.value
                job.progress = 100
                job.logs = [*job.logs, str(exc)]
                job.result = {"document_id": document.id, "error": str(exc)}
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.session.scalar(select(Document).where(Document.sha256 == digest))
            if existing is not None:
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

        existing_job = await self.session.scalar(
            select(Job)
            .where(Job.type == "index_document", Job.target_id == document.id)
            .order_by(Job.created_at.desc())
            .limit(1)
        )
        job = existing_job or JobWorker.build("index_document", document.id)
        if existing_job is None:
            self.session.add(job)
            await self.session.flush()
        await self._index_document_for_job(document, job, options)
        await self.session.commit()
        await self.session.refresh(document)

    async def _index_document_for_job(
        self,
        document: Document,
        job: Job,
        options: IndexDocumentIn | None = None,
    ) -> None:
        job.status = StageStatus.RUNNING.value
        job.progress = 50
        job.logs = [*job.logs, "Indexing document chunks."]
        chunks = await ChunkService(self.session, self.store.root).index_document(
            document.id,
            options=options,
            commit=False,
        )
        chunk_count = len(chunks or [])
        document.status = StageStatus.SUCCEEDED.value
        job.status = StageStatus.SUCCEEDED.value
        job.progress = 100
        job.result = {"document_id": document.id, "chunk_count": chunk_count}
        job.logs = [*job.logs, f"Indexed {chunk_count} chunks."]
