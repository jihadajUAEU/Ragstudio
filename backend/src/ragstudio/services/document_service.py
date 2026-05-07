from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.db.models import Document
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.documents import DocumentOut
from ragstudio.services.artifact_store import ArtifactStore
from ragstudio.services.job_worker import JobWorker


class DocumentService:
    def __init__(self, session: AsyncSession, data_dir: Path):
        self.session = session
        self.store = ArtifactStore(data_dir)

    async def upload(self, filename: str, content_type: str, content: bytes) -> DocumentOut:
        digest, artifact_path = self.store.write_upload(filename, content)
        document = Document(
            filename=filename,
            content_type=content_type,
            sha256=digest,
            artifact_path=str(artifact_path),
            status=StageStatus.READY.value,
        )
        self.session.add(document)
        await self.session.commit()
        await self.session.refresh(document)
        await JobWorker(self.session).enqueue("index_document", document.id)
        return DocumentOut.model_validate(document)

    async def list(self) -> list[DocumentOut]:
        result = await self.session.execute(select(Document).order_by(Document.created_at.desc()))
        return [DocumentOut.model_validate(item) for item in result.scalars().all()]
