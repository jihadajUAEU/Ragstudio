from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from functools import partial
from importlib import import_module
from pathlib import Path
from typing import Any

from ragstudio.config import AppSettings
from ragstudio.schemas.runtime import RuntimeProfile
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.evidence_context import (
    evidence_context_from_metadata,
    prefixed_embedding_text,
)
from ragstudio.services.graph_workspace import workspace_label
from ragstudio.services.native_storage_config import (
    NATIVE_STORAGE_ENV_LOCK,
    derive_native_storage_config,
    scoped_native_storage_env,
)
from ragstudio.services.runtime_types import RuntimeChunk, RuntimeQueryResult

RUNTIME_BRIDGE_MISSING_RISK = "runtime_bridge_missing"


class ScopedVectorStorageProxy:
    """Filters LightRAG chunk vector results to selected RAG-Anything doc IDs."""

    def __init__(
        self,
        base: Any,
        document_ids: list[str],
        *,
        overfetch_multiplier: int = 8,
        max_fetch: int = 200,
        require_storage_filter: bool = False,
    ) -> None:
        self.base = base
        self.document_ids = {str(document_id) for document_id in document_ids}
        self.overfetch_multiplier = max(1, overfetch_multiplier)
        self.max_fetch = max(1, max_fetch)
        self.require_storage_filter = require_storage_filter
        self.raw_results: list[dict[str, Any]] = []
        self.collected_results: list[dict[str, Any]] = []
        self.query_error: Exception | None = None

    async def query(
        self,
        query: str,
        top_k: int,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            if self._supports_direct_full_doc_filter():
                rows = await self.base.query_by_full_doc_ids(
                    query,
                    top_k,
                    list(self.document_ids),
                    query_embedding=query_embedding,
                )
                return self._record_scoped_rows(rows, top_k)

            if self._supports_pgvector_full_doc_filter():
                rows = await self._query_pgvector_by_full_doc_ids(
                    query,
                    top_k,
                    query_embedding=query_embedding,
                )
                return self._record_scoped_rows(rows, top_k)

            if self.require_storage_filter:
                raise RuntimeError(
                    "LightRAG vector storage does not support storage-level full_doc_id filtering."
                )

            requested_top_k = min(
                max(top_k * self.overfetch_multiplier, top_k),
                self.max_fetch,
            )
            rows = await self.base.query(
                query,
                top_k=requested_top_k,
                query_embedding=query_embedding,
            )
            rows = await self._with_full_doc_ids(rows)
            self.raw_results.extend(rows)
            scoped_rows = [
                row
                for row in rows
                if str(row.get("full_doc_id") or "") in self.document_ids
            ][:top_k]
            self.collected_results.extend(scoped_rows)
            return scoped_rows
        except Exception as exc:
            self.query_error = exc
            raise

    def supports_storage_filter(self) -> bool:
        return (
            self._supports_direct_full_doc_filter()
            or self._supports_pgvector_full_doc_filter()
        )

    def _supports_direct_full_doc_filter(self) -> bool:
        return callable(getattr(self.base, "query_by_full_doc_ids", None))

    def _supports_pgvector_full_doc_filter(self) -> bool:
        return all(
            hasattr(self.base, name)
            for name in (
                "db",
                "table_name",
                "workspace",
                "embedding_func",
                "cosine_better_than_threshold",
            )
        )

    async def _query_pgvector_by_full_doc_ids(
        self,
        query: str,
        top_k: int,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        if query_embedding is not None:
            embedding = query_embedding
        else:
            embeddings = await self.base.embedding_func(
                [query],
                context="query",
                _priority=5,
            )
            embedding = embeddings[0]

        vector_cast = (
            "halfvec"
            if getattr(self.base.db, "vector_index_type", None) == "HNSW_HALFVEC"
            else "vector"
        )
        sql = f"""
            SELECT id,
                   content,
                   file_path,
                   full_doc_id,
                   EXTRACT(EPOCH FROM create_time)::BIGINT AS created_at,
                   1 - (content_vector <=> $4::{vector_cast}) AS score
            FROM {self.base.table_name}
            WHERE workspace = $1
              AND content_vector <=> $4::{vector_cast} < $2
              AND full_doc_id = ANY($5)
            ORDER BY content_vector <=> $4::{vector_cast}
            LIMIT $3;
        """
        params = [
            self.base.workspace,
            1 - self.base.cosine_better_than_threshold,
            top_k,
            embedding,
            list(self.document_ids),
        ]
        rows = await self.base.db.query(sql, params=params, multirows=True)
        return [dict(row) for row in rows if row is not None]

    def _record_scoped_rows(
        self,
        rows: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        rows = [dict(row) for row in rows if row is not None]
        self.raw_results.extend(rows)
        scoped_rows = [
            row
            for row in rows
            if str(row.get("full_doc_id") or "") in self.document_ids
        ][:top_k]
        self.collected_results.extend(scoped_rows)
        return scoped_rows

    async def _with_full_doc_ids(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        missing_ids = [
            str(row.get("id"))
            for row in rows
            if row.get("id") is not None and not row.get("full_doc_id")
        ]
        if not missing_ids or not hasattr(self.base, "get_by_ids"):
            return rows

        hydrated_rows = await self.base.get_by_ids(missing_ids)
        hydrated_by_id = {
            str(row.get("id")): dict(row)
            for row in hydrated_rows
            if isinstance(row, dict) and row.get("id") is not None
        }
        return [
            {**hydrated_by_id.get(str(row.get("id")), {}), **row}
            if row.get("full_doc_id")
            else {**row, **hydrated_by_id.get(str(row.get("id")), {})}
            for row in rows
        ]

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)


class NativeScopedStorageUnsupported(RuntimeError):
    pass


class NativeRAGAnythingAdapter:
    """Runtime adapter for the real RAG-Anything and LightRAG stack."""

    _env_lock = NATIVE_STORAGE_ENV_LOCK

    def __init__(self, profile: RuntimeProfile, settings: AppSettings | None = None):
        self.profile = profile
        self.settings = settings or AppSettings()
        self._rag: Any | None = None

    def capability_report(self) -> dict[str, Any]:
        return {
            "raganything_available": True,
            "active_backend": "runtime",
            "indexing": "raganything",
            "query": "raganything",
            "graph": "neo4j",
            "native_scoped_query": "conditional",
            "scoped_query": "requires_storage_verification",
            "scoped_query_detail": (
                "Selected-document native query requires LightRAG chunk storage with "
                "full_doc_id filtering support; the storage backend is verified when "
                "a scoped query initializes LightRAG."
            ),
        }

    async def index_document(
        self,
        artifact_path: str | Path,
        *,
        document_id: str | None = None,
    ) -> list[RuntimeChunk]:
        path = Path(artifact_path)
        output_dir = self._output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        rag = self._raganything()
        async with self._storage_env():
            content_list, generated_doc_id = await rag.parse_document(
                str(path),
                str(output_dir),
                self.profile.parse_method,
                False,
            )
            await rag.insert_content_list(
                content_list,
                file_path=str(path),
                doc_id=document_id or generated_doc_id,
                display_stats=False,
            )
            await self._raise_for_failed_doc_status(rag, document_id or generated_doc_id)
        return self._mirrored_chunks(content_list, path)

    async def index_preparsed_chunks(
        self,
        artifact_path: str | Path,
        chunks: list[AdapterChunk],
        *,
        document_id: str,
    ) -> list[RuntimeChunk]:
        path = Path(artifact_path)
        content_list = self._content_list_from_preparsed_chunks(
            chunks,
            document_id=document_id,
        )
        rag = self._raganything()
        async with self._storage_env():
            await rag.insert_content_list(
                content_list,
                file_path=str(path),
                doc_id=document_id,
                display_stats=False,
            )
            await self._raise_for_failed_doc_status(rag, document_id)
        return self._runtime_chunks_from_adapter_chunks(
            chunks,
            path,
            document_id=document_id,
        )

    async def preflight_scoped_retrieval(self, document_ids: list[str]) -> dict[str, Any]:
        if not document_ids:
            return {
                "status": "ok",
                "storage_filter": "not_required",
                "embedding_dimensions": self.profile.embedding_dimensions,
                "send_dimensions": True,
                "scoped_cache_policy": "not_required",
            }

        rag = self._raganything()
        async with self._storage_env():
            try:
                await self._ensure_lightrag(rag)
                lightrag = getattr(rag, "lightrag", None)
                chunks_vdb = getattr(lightrag, "chunks_vdb", None)
                if chunks_vdb is None:
                    raise NativeScopedStorageUnsupported(
                        "LightRAG chunks vector storage is not initialized."
                    )
                proxy = ScopedVectorStorageProxy(
                    chunks_vdb,
                    document_ids,
                    require_storage_filter=True,
                )
                if not proxy.supports_storage_filter():
                    raise NativeScopedStorageUnsupported(
                        "LightRAG vector storage does not support storage-level "
                        "full_doc_id filtering."
                    )
            except NativeScopedStorageUnsupported as exc:
                return {
                    "status": "degraded",
                    "error_type": "native_document_scope_unsupported",
                    "detail": str(exc),
                    "embedding_dimensions": self.profile.embedding_dimensions,
                    "send_dimensions": True,
                    "scoped_cache_policy": "disabled_for_query",
                }

        return {
            "status": "ok",
            "storage_filter": "supported",
            "embedding_dimensions": self.profile.embedding_dimensions,
            "send_dimensions": True,
            "scoped_cache_policy": "disabled_for_query",
        }

    async def query(
        self,
        query: str,
        *,
        document_ids: list[str],
        query_config: dict[str, Any],
    ) -> RuntimeQueryResult:
        rag = self._raganything()
        mode = str(query_config.get("mode") or self.profile.query_mode)
        kwargs = self._query_kwargs(query_config)
        started = asyncio.get_running_loop().time()
        async with self._storage_env():
            if document_ids:
                effective_mode = "naive"
                kwargs["vlm_enhanced"] = False
                try:
                    async with self._scoped_chunks_vdb(rag, document_ids) as scoped_proxy:
                        answer = await rag.aquery(query, mode=effective_mode, **kwargs)
                        timings = self._scoped_query_timings(started, mode, effective_mode)
                        if scoped_proxy.query_error is not None:
                            return RuntimeQueryResult(
                                answer="",
                                sources=[],
                                timings=timings,
                                error=(
                                    "Native RAG-Anything scoped query failed while applying "
                                    "full_doc_id storage filter: "
                                    f"{scoped_proxy.query_error}"
                                ),
                                error_type="native_document_scope_filter_failed",
                            )
                        leak = self._scope_leak_error(scoped_proxy, document_ids)
                        if leak is not None:
                            return leak
                        return RuntimeQueryResult(
                            answer=str(answer or ""),
                            sources=self._native_sources_from_proxy(
                                scoped_proxy,
                                document_ids,
                            ),
                            timings=timings,
                        )
                except NativeScopedStorageUnsupported as exc:
                    return RuntimeQueryResult(
                        answer="",
                        sources=[],
                        timings=self._scoped_query_timings(started, mode, effective_mode),
                        error=str(exc),
                        error_type="native_document_scope_unsupported",
                    )

            await self._ensure_lightrag(rag)
            answer = await rag.aquery(query, mode=mode, **kwargs)
        return RuntimeQueryResult(
            answer=str(answer or ""),
            sources=[],
            timings={
                "runtime_query_ms": round(
                    (asyncio.get_running_loop().time() - started) * 1000,
                    3,
                ),
                "native_scoped_query": False,
            },
        )

    async def delete_document_index(self, document_id: str) -> None:
        rag = self._raganything()
        async with self._storage_env():
            await self._ensure_lightrag(rag)
            lightrag = getattr(rag, "lightrag", None)
            if lightrag is not None and hasattr(lightrag, "adelete_by_doc_id"):
                await lightrag.adelete_by_doc_id(document_id)

    async def graph(self) -> dict[str, Any]:
        if not self.profile.neo4j_uri:
            raise RuntimeError("Neo4j URI is not configured.")

        graph_database = import_module("neo4j").GraphDatabase
        auth = None
        if self.profile.neo4j_username or self.profile.neo4j_password:
            auth = (self.profile.neo4j_username or "", self.profile.neo4j_password or "")
        driver = graph_database.driver(
            self.profile.neo4j_uri,
            auth=auth,
            connection_timeout=3.0,
            max_transaction_retry_time=1.0,
        )
        try:
            nodes, edges = await asyncio.to_thread(self._read_neo4j_graph, driver)
        finally:
            await asyncio.to_thread(driver.close)
        return {"nodes": nodes, "edges": edges}

    def _raganything(self) -> Any:
        if self._rag is not None:
            return self._rag

        raganything = import_module("raganything")
        rag_config_module = import_module("raganything.config")
        openai_module = import_module("lightrag.llm.openai")
        utils_module = import_module("lightrag.utils")

        async def llm_func(prompt: str, *args: Any, **kwargs: Any) -> str:
            kwargs.pop("model", None)
            return await openai_module.openai_complete_if_cache(
                self.profile.llm_model,
                prompt,
                *args,
                base_url=self.profile.llm_base_url,
                api_key=self._openai_client_api_key(
                    self.profile.llm_api_key,
                    self.profile.llm_base_url,
                ),
                timeout=self.profile.llm_timeout_ms / 1000,
                **kwargs,
            )

        embedding_impl = getattr(openai_module.openai_embed, "func", openai_module.openai_embed)
        embedding_func = utils_module.EmbeddingFunc(
            embedding_dim=self.profile.embedding_dimensions,
            func=partial(
                embedding_impl,
                model=self.profile.embedding_model,
                base_url=self.profile.embedding_base_url,
                api_key=self._openai_client_api_key(
                    self.profile.embedding_api_key,
                    self.profile.embedding_base_url,
                ),
            ),
            model_name=self.profile.embedding_model,
            send_dimensions=True,
        )
        vision_func = None
        if self.profile.vision_base_url or "vision" in self.profile.llm_capabilities:
            async def vision_func(prompt: str, *args: Any, **kwargs: Any) -> str:
                kwargs.pop("model", None)
                return await openai_module.openai_complete_if_cache(
                    self.profile.vision_model or self.profile.llm_model,
                    prompt,
                    *args,
                    base_url=self.profile.vision_base_url or self.profile.llm_base_url,
                    api_key=self._openai_client_api_key(
                        self.profile.vision_api_key or self.profile.llm_api_key,
                        self.profile.vision_base_url or self.profile.llm_base_url,
                    ),
                    timeout=self.profile.vision_timeout_ms / 1000,
                    **kwargs,
                )

        config = rag_config_module.RAGAnythingConfig(
            working_dir=str(self.profile.runtime_working_dir),
            parser_output_dir=str(self._output_dir()),
            parser=self.profile.parser,
            parse_method=self.profile.parse_method,
            display_content_stats=False,
            enable_image_processing=self.profile.enable_image_processing,
            enable_table_processing=self.profile.enable_table_processing,
            enable_equation_processing=self.profile.enable_equation_processing,
            context_window=self.profile.context_window,
            context_mode=self.profile.context_mode,
            max_context_tokens=self.profile.max_context_tokens,
            include_headers=self.profile.include_headers,
            include_captions=self.profile.include_captions,
        )
        self._rag = raganything.RAGAnything(
            llm_model_func=llm_func,
            vision_model_func=vision_func,
            embedding_func=embedding_func,
            config=config,
            lightrag_kwargs=self._lightrag_kwargs(),
        )
        return self._rag

    def _openai_client_api_key(self, api_key: str | None, base_url: str | None) -> str | None:
        if api_key:
            return api_key
        if base_url:
            return "unused"
        return None

    def _lightrag_kwargs(self) -> dict[str, Any]:
        return {
            "kv_storage": "PGKVStorage",
            "vector_storage": "PGVectorStorage",
            "graph_storage": "Neo4JStorage",
            "doc_status_storage": "PGDocStatusStorage",
            "workspace": self._workspace(),
            "llm_model_name": self.profile.llm_model,
            "llm_model_max_async": self.profile.llm_model_max_async,
            "embedding_batch_num": self.profile.embedding_batch_size,
            "embedding_func_max_async": self.profile.embedding_func_max_async,
            "chunk_token_size": self.profile.chunk_token_size,
            "chunk_overlap_token_size": self.profile.chunk_overlap_token_size,
            "top_k": self.profile.top_k,
            "chunk_top_k": self.profile.chunk_top_k,
            "max_total_tokens": self.profile.max_total_tokens,
            "max_entity_tokens": self.profile.max_entity_tokens,
            "max_relation_tokens": self.profile.max_relation_tokens,
            "cosine_better_than_threshold": self.profile.cosine_better_than_threshold,
            "enable_llm_cache": self.profile.enable_llm_cache,
            "enable_llm_cache_for_entity_extract": self.profile.enable_llm_cache_for_entity_extract,
            "max_parallel_insert": self.profile.max_parallel_insert,
        }

    def _query_kwargs(self, query_config: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "top_k",
            "chunk_top_k",
            "max_total_tokens",
            "max_entity_tokens",
            "max_relation_tokens",
            "enable_rerank",
            "conversation_history",
            "response_type",
            "vlm_enhanced",
        }
        return {key: value for key, value in query_config.items() if key in allowed}

    async def _ensure_lightrag(self, rag: Any) -> None:
        ensure = getattr(rag, "_ensure_lightrag_initialized", None)
        if ensure is not None:
            result = await ensure()
            if isinstance(result, dict) and not result.get("success", True):
                raise RuntimeError(result.get("error") or "LightRAG initialization failed.")

    def _scoped_query_timings(
        self,
        started: float,
        requested_mode: str,
        effective_mode: str,
    ) -> dict[str, Any]:
        return {
            "runtime_query_ms": round(
                (asyncio.get_running_loop().time() - started) * 1000,
                3,
            ),
            "native_scoped_query": True,
            "requested_query_mode": requested_mode,
            "effective_query_mode": effective_mode,
        }

    @asynccontextmanager
    async def _scoped_chunks_vdb(
        self,
        rag: Any,
        document_ids: list[str],
    ) -> AsyncIterator[ScopedVectorStorageProxy]:
        await self._ensure_lightrag(rag)
        lightrag = getattr(rag, "lightrag", None)
        if lightrag is None or not hasattr(lightrag, "chunks_vdb"):
            raise NativeScopedStorageUnsupported(
                "LightRAG chunks vector storage is not initialized."
            )

        original_chunks_vdb = lightrag.chunks_vdb
        cache_config = self._llm_cache_config(lightrag)
        cache_had_enabled_key = (
            "enable_llm_cache" in cache_config if cache_config is not None else False
        )
        original_cache_enabled = (
            cache_config.get("enable_llm_cache") if cache_config is not None else None
        )
        proxy = ScopedVectorStorageProxy(
            original_chunks_vdb,
            document_ids,
            require_storage_filter=True,
        )
        if not proxy.supports_storage_filter():
            raise NativeScopedStorageUnsupported(
                "LightRAG vector storage does not support storage-level full_doc_id filtering."
            )
        lightrag.chunks_vdb = proxy
        if cache_config is not None:
            cache_config["enable_llm_cache"] = False
        try:
            yield proxy
        finally:
            lightrag.chunks_vdb = original_chunks_vdb
            if cache_config is not None:
                if cache_had_enabled_key:
                    cache_config["enable_llm_cache"] = original_cache_enabled
                else:
                    cache_config.pop("enable_llm_cache", None)

    def _llm_cache_config(self, lightrag: Any) -> dict[str, Any] | None:
        cache = getattr(lightrag, "llm_response_cache", None)
        global_config = getattr(cache, "global_config", None)
        return global_config if isinstance(global_config, dict) else None

    def _native_sources_from_proxy(
        self,
        proxy: ScopedVectorStorageProxy,
        document_ids: list[str],
    ) -> list[dict[str, Any]]:
        allowed = set(document_ids)
        deduped: dict[str, dict[str, Any]] = {}
        for row in proxy.collected_results:
            document_id = str(row.get("full_doc_id") or "")
            if document_id not in allowed:
                continue
            chunk_id = str(row.get("id") or "")
            if not chunk_id or chunk_id in deduped:
                continue
            chunk_identity = str(
                row.get("chunk_identity")
                or row.get("canonical_chunk_id")
                or row.get("runtime_source_id")
                or chunk_id
            )
            source_location = {
                key: value
                for key, value in row.items()
                if key in {"page", "page_idx", "reference"} and value is not None
            }
            metadata = self._native_source_metadata(
                row,
                document_id=document_id,
                chunk_identity=chunk_identity,
            )
            deduped[chunk_id] = {
                "chunk_id": chunk_id,
                "document_id": document_id,
                "text": str(row.get("content") or ""),
                "source_location": source_location,
                "metadata": metadata,
            }
        return list(deduped.values())

    def _native_source_metadata(
        self,
        row: Mapping[str, Any],
        *,
        document_id: str,
        chunk_identity: str,
    ) -> dict[str, Any]:
        row_metadata = row.get("metadata")
        metadata = dict(row_metadata) if isinstance(row_metadata, Mapping) else {}
        metadata.update(
            {
                "chunk_identity": chunk_identity,
                "full_doc_id": document_id,
                "runtime_source_id": chunk_identity,
                "score": row.get("score"),
                "native_scope": True,
                "source_role": "retrieved_candidate",
                "retrieval_scope": "document_ids",
                "retrieval_mode": "native_vector_naive",
            }
        )
        if not _has_canonical_layout_context(metadata):
            metadata.setdefault("canonical_hydration_status", "missing")
            metadata.setdefault("layout_context_status", "runtime_minimal")
            metadata["risk_flags"] = _merge_risk_flags(
                metadata.get("risk_flags"),
                [RUNTIME_BRIDGE_MISSING_RISK],
            )
        return metadata

    def _scope_leak_error(
        self,
        proxy: ScopedVectorStorageProxy,
        document_ids: list[str],
    ) -> RuntimeQueryResult | None:
        allowed = set(document_ids)
        leaked_ids = sorted(
            {
                str(row.get("full_doc_id") or "")
                for row in proxy.collected_results
                if str(row.get("full_doc_id") or "") not in allowed
            }
        )
        if not leaked_ids:
            return None
        return RuntimeQueryResult(
            answer="",
            sources=[],
            timings={},
            error=(
                "Native RAG-Anything scoped query returned chunks outside selected "
                f"document_ids: {', '.join(leaked_ids)}"
            ),
            error_type="native_document_scope_leak",
        )

    @asynccontextmanager
    async def _storage_env(self) -> AsyncIterator[None]:
        config = derive_native_storage_config(self.profile, self.settings)
        async with scoped_native_storage_env(config):
            yield

    def _workspace(self) -> str:
        return workspace_label(self.profile)

    def _workspace_label(self) -> str:
        return self._workspace().replace("`", "``")

    def _output_dir(self) -> Path:
        return Path(self.profile.runtime_working_dir) / "parsed"

    def _mirrored_chunks(
        self,
        content_list: list[dict[str, Any]],
        path: Path,
    ) -> list[RuntimeChunk]:
        chunks: list[RuntimeChunk] = []
        for index, item in enumerate(content_list):
            if not isinstance(item, dict):
                continue
            text = self._content_text(item)
            if not text:
                continue
            chunks.append(
                RuntimeChunk(
                    text=text,
                    source_location={
                        "page": item.get("page_idx"),
                        "block": index,
                    },
                    metadata={
                        "backend": "raganything",
                        "artifact_ref": path.name,
                        "chunk_index": index,
                        "source_type": item.get("type") or "text",
                    },
                    runtime_source_id=str(item.get("id") or index),
                    content_type=str(item.get("type") or "text"),
                    preview_ref=str(item.get("img_path") or item.get("image_path") or ""),
                )
            )
        return chunks

    def _content_list_from_preparsed_chunks(
        self,
        chunks: list[AdapterChunk],
        *,
        document_id: str,
    ) -> list[dict[str, Any]]:
        content_list: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks):
            metadata = dict(chunk.metadata)
            page_idx = chunk.source_location.get("page")
            if not isinstance(page_idx, int):
                page = chunk.source_location.get("page_start")
                page_idx = page - 1 if isinstance(page, int) and page > 0 else None
            chunk_identity = self._preparsed_chunk_identity(
                chunk,
                index,
                document_id=document_id,
            )
            metadata["chunk_identity"] = chunk_identity
            content_type = chunk.content_type or "text"
            metadata.setdefault("content_type", content_type)
            if isinstance(chunk.runtime_source_id, str) and chunk.runtime_source_id.strip():
                metadata.setdefault("runtime_source_id", chunk.runtime_source_id)
            evidence_context = evidence_context_from_metadata(
                metadata,
                source_location=chunk.source_location,
                content_type=chunk.content_type,
            )
            if evidence_context:
                metadata["evidence_context"] = evidence_context
            item: dict[str, Any] = {
                "id": chunk_identity,
                "chunk_identity": chunk_identity,
                "canonical_chunk_id": chunk_identity,
                "full_doc_id": document_id,
                "type": "text",
                "text": prefixed_embedding_text(
                    chunk.text,
                    metadata,
                    source_location=chunk.source_location,
                    content_type=chunk.content_type,
                ),
                "metadata": {
                    key: metadata[key]
                    for key in (
                        "chunk_identity",
                        "reference_metadata",
                        "quality_action_policy",
                        "evidence_context",
                        "content_type",
                        "runtime_source_id",
                        "bbox",
                        "coordinates",
                        "layout_group_id",
                        "layout_role",
                        "reading_order",
                        "block_index",
                        "parent_chunk_id",
                        "previous_chunk_id",
                        "next_chunk_id",
                        "layout_types",
                        "layout_hint",
                        "modality",
                        "provenance",
                    )
                    if key in metadata
                },
            }
            if isinstance(page_idx, int):
                item["page_idx"] = page_idx
                item["metadata"]["page_idx"] = page_idx
            content_list.append(item)
        return content_list

    def _runtime_chunks_from_adapter_chunks(
        self,
        chunks: list[AdapterChunk],
        path: Path,
        *,
        document_id: str,
    ) -> list[RuntimeChunk]:
        output: list[RuntimeChunk] = []
        for index, chunk in enumerate(chunks):
            parser_metadata = chunk.metadata.get("parser_metadata")
            metadata = dict(parser_metadata) if isinstance(parser_metadata, dict) else {}
            chunk_identity = self._preparsed_chunk_identity(
                chunk,
                index,
                document_id=document_id,
            )
            metadata.update(
                {
                    "backend": metadata.get("backend", "mineru"),
                    "artifact_ref": metadata.get("artifact_ref", path.name),
                    "chunk_index": metadata.get("chunk_index", index),
                    "chunk_identity": chunk_identity,
                    "source_type": metadata.get("content_type", chunk.content_type),
                }
            )
            output.append(
                RuntimeChunk(
                    text=chunk.text,
                    source_location=chunk.source_location,
                    metadata=metadata,
                    runtime_source_id=chunk_identity,
                    content_type=chunk.content_type,
                    preview_ref=chunk.preview_ref,
                )
            )
        return output

    def _preparsed_chunk_identity(
        self,
        chunk: AdapterChunk,
        index: int,
        *,
        document_id: str,
    ) -> str:
        metadata_identity = chunk.metadata.get("chunk_identity")
        if isinstance(metadata_identity, str) and metadata_identity.strip():
            return metadata_identity

        if isinstance(chunk.runtime_source_id, str) and chunk.runtime_source_id.strip():
            return chunk.runtime_source_id

        parser_metadata = chunk.metadata.get("parser_metadata")
        parser_metadata = dict(parser_metadata) if isinstance(parser_metadata, dict) else {}
        artifact_ref = parser_metadata.get("artifact_ref") or chunk.source_location.get("artifact")
        chunk_index = parser_metadata.get("chunk_index", index)
        preview_ref = chunk.preview_ref or chunk.metadata.get("preview_ref")
        return "|".join(
            str(part)
            for part in (
                document_id,
                artifact_ref,
                preview_ref,
                chunk_index,
            )
        )

    async def _raise_for_failed_doc_status(self, rag: Any, document_id: str | None) -> None:
        if not document_id:
            return
        lightrag = getattr(rag, "lightrag", None)
        doc_status = getattr(lightrag, "doc_status", None)
        if doc_status is None or not hasattr(doc_status, "get_by_id"):
            return
        try:
            record = await doc_status.get_by_id(document_id)
        except Exception:
            return
        if not isinstance(record, dict):
            return
        status = str(record.get("status") or "").casefold()
        if status != "failed":
            return
        reason = str(record.get("error_msg") or "").strip()
        if not reason:
            reason = "LightRAG document processing failed."
        raise RuntimeError(reason)

    def _content_text(self, item: dict[str, Any]) -> str:
        for key in ("text", "content", "table_body", "latex"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        captions = item.get("image_caption") or item.get("table_caption")
        if isinstance(captions, list):
            return " ".join(str(value).strip() for value in captions if str(value).strip())
        return ""

    def _read_neo4j_graph(self, driver: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        workspace_label = self._workspace_label()
        with driver.session() as session:
            node_rows = session.run(
                f"""
                MATCH (n:`{workspace_label}`)
                RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS properties
                LIMIT 500
                """
            )
            edge_rows = session.run(
                f"""
                MATCH (source:`{workspace_label}`)-[relationship]->(target:`{workspace_label}`)
                RETURN elementId(relationship) AS id,
                       type(relationship) AS type,
                       elementId(source) AS source,
                       elementId(target) AS target,
                       properties(relationship) AS properties
                LIMIT 1000
                """
            )
            nodes = [
                {
                    "id": row["id"],
                    "labels": row["labels"],
                    "properties": dict(row["properties"] or {}),
                }
                for row in node_rows
            ]
            edges = [
                {
                    "id": row["id"],
                    "type": row["type"],
                    "source": row["source"],
                    "target": row["target"],
                    "properties": dict(row["properties"] or {}),
                }
                for row in edge_rows
            ]
        return nodes, edges


def _has_canonical_layout_context(metadata: Mapping[str, Any]) -> bool:
    evidence_context = metadata.get("evidence_context")
    return isinstance(evidence_context, Mapping) and bool(
        evidence_context.get("breadcrumb")
        or evidence_context.get("layout_summary")
        or evidence_context.get("source_location")
    )


def _merge_risk_flags(*flag_groups: Any) -> list[str]:
    merged: list[str] = []
    for group in flag_groups:
        if isinstance(group, str):
            flags = [group]
        elif isinstance(group, (list, tuple, set)):
            flags = group
        else:
            continue
        for flag in flags:
            if isinstance(flag, str) and flag and flag not in merged:
                merged.append(flag)
    return merged
