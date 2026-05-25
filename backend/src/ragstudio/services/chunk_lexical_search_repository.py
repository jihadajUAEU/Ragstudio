from __future__ import annotations

import json
import re

from ragstudio.db.models import Chunk, Document
from ragstudio.services.arabic_text import arabic_query_variants, arabic_tokens
from ragstudio.services.reference_query_parser import (
    parse_legacy_reference_query,
    parse_query_references,
)
from sqlalchemy import and_, cast, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

_ENGLISH_PREFILTER_STOPWORDS = {
    "a",
    "an",
    "about",
    "and",
    "are",
    "as",
    "at",
    "be",
    "book",
    "by",
    "collection",
    "document",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "pdf",
    "saying",
    "says",
    "say",
    "the",
    "this",
    "to",
    "was",
    "what",
    "which",
    "who",
    "with",
}


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
        reference_contracts = await self._reference_contracts(document_ids)
        references = parse_query_references(query, reference_contracts)
        if not references:
            references = parse_legacy_reference_query(
                query,
                enabled_profiles=_legacy_reference_profiles(reference_contracts),
            )
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

    async def _reference_contracts(self, document_ids: list[str]) -> list[dict[str, object]]:
        if not document_ids:
            return []
        result = await self.session.execute(
            select(Document.index_contract).where(Document.id.in_(document_ids))
        )
        contracts: list[dict[str, object]] = []
        for contract in result.scalars().all():
            if isinstance(contract, dict) and isinstance(contract.get("reference_contract"), dict):
                contracts.append(contract)
        return contracts

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

    async def english_prefilter(
        self,
        *,
        query: str,
        document_ids: list[str],
        limit: int,
    ) -> list[Chunk]:
        terms = _english_prefilter_terms(query)
        if not terms or limit <= 0:
            return []

        statement = select(Chunk)
        if document_ids:
            statement = statement.where(Chunk.document_id.in_(document_ids))

        filters = [
            Chunk.text.ilike(f"%{_escape_like(term)}%", escape="\\") for term in terms
        ]
        if len(filters) > 1:
            exact_statement = select(Chunk)
            if document_ids:
                exact_statement = exact_statement.where(Chunk.document_id.in_(document_ids))
            exact_statement = (
                exact_statement.where(and_(*filters))
                .order_by(Chunk.created_at.asc(), Chunk.id.asc())
                .limit(limit)
            )
            exact_result = await self.session.execute(exact_statement)
            exact_chunks = list(exact_result.scalars().all())
            if exact_chunks:
                return exact_chunks

        statement = (
            statement.where(or_(*filters))
            .order_by(Chunk.created_at.asc(), Chunk.id.asc())
            .limit(max(limit * 4, limit))
        )

        result = await self.session.execute(statement)
        return list(result.scalars().all())[:limit]


def _english_prefilter_terms(query: str) -> list[str]:
    if re.search(r"[\u0600-\u06FF]", query):
        return []
    terms: list[str] = []
    for match in re.finditer(r"[A-Za-z][A-Za-z_'-]{2,79}", query):
        term = match.group(0).strip("_'-").casefold()
        if len(term) < 3 or term in _ENGLISH_PREFILTER_STOPWORDS:
            continue
        if term == "eid":
            terms.extend(["eid", "id", "adha"])
        else:
            terms.append(term)
    return list(dict.fromkeys(terms))[:5]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _supports_reference_prefilter(chunk: Chunk) -> bool:
    metadata = chunk.metadata_json if isinstance(chunk.metadata_json, dict) else {}
    if isinstance(metadata.get("reference_metadata"), dict):
        return True

    domain_metadata = metadata.get("domain_metadata")
    if not isinstance(domain_metadata, dict):
        return False

    custom_json = domain_metadata.get("custom_json")
    if isinstance(custom_json, dict) and any(
        key in custom_json
        for key in ("reference_schema", "reference_resolution", "domain_structure")
    ):
        return True

    return any(
        isinstance(domain_metadata.get(key), str) and bool(domain_metadata.get(key))
        for key in ("citation_style", "reference_unit")
    )


def _legacy_reference_profiles(contracts: list[dict[str, object]]) -> set[str]:
    profiles: set[str] = set()
    for contract in contracts:
        reference_contract = contract.get("reference_contract")
        if not isinstance(reference_contract, dict):
            continue
        schema_type = reference_contract.get("schema_type")
        if isinstance(schema_type, str) and reference_contract.get("verified") is True:
            profiles.add(schema_type)
    return profiles
