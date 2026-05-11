from ragstudio.db.models import Chunk, GraphProjectionRecord, IndexRecord
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

_DELETABLE_GRAPH_STATUSES = {"pending", "failed", "skipped"}


async def cleanup_document_index_artifacts(
    session: AsyncSession,
    document_id: str,
    *,
    commit: bool = False,
) -> None:
    await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
    await session.execute(delete(IndexRecord).where(IndexRecord.document_id == document_id))
    await session.execute(
        update(GraphProjectionRecord)
        .where(
            GraphProjectionRecord.document_id == document_id,
            GraphProjectionRecord.status == "succeeded",
        )
        .values(
            status="stale",
            error="Superseded by a newer indexing attempt.",
        )
    )
    await session.execute(
        delete(GraphProjectionRecord).where(
            GraphProjectionRecord.document_id == document_id,
            GraphProjectionRecord.status.in_(_DELETABLE_GRAPH_STATUSES),
            GraphProjectionRecord.node_count == 0,
            GraphProjectionRecord.edge_count == 0,
        )
    )
    if commit:
        await session.commit()
    else:
        await session.flush()
