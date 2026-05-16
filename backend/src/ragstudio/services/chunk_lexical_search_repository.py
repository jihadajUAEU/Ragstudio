from __future__ import annotations

import json
import re

from sqlalchemy import cast, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from ragstudio.db.models import Chunk
from ragstudio.services.arabic_text import arabic_query_variants, arabic_tokens


class ChunkLexicalSearchRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def reference_prefilter(
        self,
        *,
        query: str,
        document_ids: list[str],
        limit: int,
    ) -> list[Chunk]:
        references = _query_references(query)
        if not references or limit <= 0:
            return []

        statement = select(Chunk).where(Chunk.preview_ref.in_(references))
        if document_ids:
            statement = statement.where(Chunk.document_id.in_(document_ids))
        statement = statement.order_by(Chunk.created_at.asc(), Chunk.id.asc()).limit(
            max(limit * 4, limit)
        )

        result = await self.session.execute(statement)
        chunks = list(result.scalars().all())
        supported = [chunk for chunk in chunks if _supports_reference_prefilter(chunk)]
        return supported[:limit]

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


def _query_references(query: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\b\d{1,3}:\d{1,3}\b", query)))


def _supports_reference_prefilter(chunk: Chunk) -> bool:
    metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
    if isinstance(metadata.get("reference_metadata"), dict):
        return True

    domain_metadata = metadata.get("domain_metadata")
    if not isinstance(domain_metadata, dict):
        return False

    raw_tags = domain_metadata.get("tags")
    tags = (
        {str(tag).casefold() for tag in raw_tags if isinstance(tag, str)}
        if isinstance(raw_tags, list)
        else set()
    )
    tokens = {
        str(domain_metadata.get("domain") or "").casefold(),
        str(domain_metadata.get("document_type") or "").casefold(),
        str(domain_metadata.get("citation_style") or "").casefold(),
        *tags,
    }
    return bool(
        tokens
        & {
            "quran_tafseer",
            "tafseer",
            "quran",
            "hadith",
            "legal",
            "law",
            "statute",
            "policy",
        }
    )
