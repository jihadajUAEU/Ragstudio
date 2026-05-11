from __future__ import annotations

import json

from ragstudio.db.models import Chunk
from ragstudio.services.arabic_text import arabic_query_variants, arabic_tokens
from sqlalchemy import cast, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession


class ChunkLexicalSearchRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def arabic_prefilter(
        self,
        *,
        query: str,
        document_ids: list[str],
        limit: int,
    ) -> list[Chunk]:
        variants = list(dict.fromkeys([*arabic_query_variants(query), *arabic_tokens(query)]))
        if not variants or limit <= 0:
            return []

        statement = select(Chunk)
        if document_ids:
            statement = statement.where(Chunk.document_id.in_(document_ids))

        token_filters = [
            Chunk.tokens_ar.op("@>")(
                cast(literal(json.dumps([variant], ensure_ascii=False)), JSONB)
            )
            for variant in variants
        ]
        statement = (
            statement.where(or_(*token_filters))
            .order_by(Chunk.created_at.asc(), Chunk.id.asc())
            .limit(limit)
        )

        result = await self.session.execute(statement)
        return list(result.scalars().all())
