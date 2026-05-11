from ragstudio.db.models import Chunk, GraphProjectionRecord, IndexRecord
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession


async def cleanup_document_index_artifacts(
    session: AsyncSession,
    document_id: str,
    *,
    commit: bool = False,
) -> None:
    await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
    await session.execute(delete(IndexRecord).where(IndexRecord.document_id == document_id))
    await session.execute(
        delete(GraphProjectionRecord).where(GraphProjectionRecord.document_id == document_id)
    )
    if commit:
        await session.commit()
    else:
        await session.flush()
