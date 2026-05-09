from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from ragstudio.config import AppSettings
from ragstudio.schemas.runtime import RuntimeProfile
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.runtime_types import RuntimeChunk, RuntimeQueryResult
from sqlalchemy.engine import make_url


class ScopedVectorStorageProxy:
    """Filters LightRAG chunk vector results to selected RAG-Anything doc IDs."""

    def __init__(
        self,
        base: Any,
        document_ids: list[str],
        *,
        overfetch_multiplier: int = 8,
        max_fetch: int = 200,
    ) -> None:
        self.base = base
        self.document_ids = {str(document_id) for document_id in document_ids}
        self.overfetch_multiplier = max(1, overfetch_multiplier)
        self.max_fetch = max(1, max_fetch)
        self.raw_results: list[dict[str, Any]] = []
        self.collected_results: list[dict[str, Any]] = []

    async def query(
        self,
        query: str,
        top_k: int,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        requested_top_k = min(max(top_k * self.overfetch_multiplier, top_k), self.max_fetch)
        rows = await self.base.query(
            query,
            top_k=requested_top_k,
            query_embedding=query_embedding,
        )
        self.raw_results.extend(rows)
        scoped_rows = [
            row
            for row in rows
            if str(row.get("full_doc_id") or "") in self.document_ids
        ][:top_k]
        self.collected_results.extend(scoped_rows)
        return scoped_rows

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)


class NativeRAGAnythingAdapter:
    """Runtime adapter for the real RAG-Anything and LightRAG stack."""

    _env_lock = asyncio.Lock()

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
            "native_scoped_query": True,
            "scoped_query": "raganything_full_doc_id_vector",
            "scoped_query_detail": (
                "Selected-document native query uses LightRAG chunk full_doc_id "
                "filtering with vector/naive retrieval; graph modes are not used "
                "under document scope."
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
        return self._mirrored_chunks(content_list, path)

    async def index_preparsed_chunks(
        self,
        artifact_path: str | Path,
        chunks: list[AdapterChunk],
        *,
        document_id: str,
    ) -> list[RuntimeChunk]:
        path = Path(artifact_path)
        content_list = self._content_list_from_preparsed_chunks(chunks)
        rag = self._raganything()
        async with self._storage_env():
            await rag.insert_content_list(
                content_list,
                file_path=str(path),
                doc_id=document_id,
                display_stats=False,
            )
        return self._runtime_chunks_from_adapter_chunks(chunks, path)

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
                async with self._scoped_chunks_vdb(rag, document_ids) as scoped_proxy:
                    answer = await rag.aquery(query, mode=effective_mode, **kwargs)
                    leak = self._scope_leak_error(scoped_proxy, document_ids)
                    if leak is not None:
                        return leak
                    return RuntimeQueryResult(
                        answer=str(answer or ""),
                        sources=self._native_sources_from_proxy(
                            scoped_proxy,
                            document_ids,
                        ),
                        timings={
                            "runtime_query_ms": round(
                                (asyncio.get_running_loop().time() - started) * 1000,
                                3,
                            ),
                            "native_scoped_query": True,
                            "requested_query_mode": mode,
                            "effective_query_mode": effective_mode,
                        },
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

        llm_func = self._completion_func(
            openai_module.openai_complete_if_cache,
            model=self.profile.llm_model,
            base_url=self.profile.llm_base_url,
            api_key=self._api_key_or_placeholder(self.profile.llm_api_key),
            timeout_ms=self.profile.llm_timeout_ms,
        )
        embedding_impl = getattr(openai_module.openai_embed, "func", openai_module.openai_embed)
        embedding_func = utils_module.EmbeddingFunc(
            embedding_dim=self.profile.embedding_dimensions,
            func=partial(
                embedding_impl,
                model=self.profile.embedding_model,
                base_url=self.profile.embedding_base_url,
                api_key=self._api_key_or_placeholder(self.profile.embedding_api_key),
            ),
            send_dimensions=True,
            model_name=self.profile.embedding_model,
        )
        vision_func = None
        if self.profile.vision_base_url or "vision" in self.profile.llm_capabilities:
            vision_func = self._completion_func(
                openai_module.openai_complete_if_cache,
                model=self.profile.vision_model or self.profile.llm_model,
                base_url=self.profile.vision_base_url or self.profile.llm_base_url,
                api_key=self._api_key_or_placeholder(
                    self.profile.vision_api_key or self.profile.llm_api_key,
                ),
                timeout_ms=self.profile.vision_timeout_ms,
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

    def _api_key_or_placeholder(self, api_key: str | None) -> str:
        return api_key or "ragstudio-local-runtime"

    def _completion_func(
        self,
        completion_impl: Any,
        *,
        model: str,
        base_url: str | None,
        api_key: str,
        timeout_ms: int,
    ) -> Any:
        async def complete(prompt: str, *args: Any, **kwargs: Any) -> str:
            kwargs.pop("model", None)
            return await completion_impl(
                model,
                prompt,
                *args,
                base_url=base_url,
                api_key=api_key,
                timeout=timeout_ms / 1000,
                **kwargs,
            )

        complete._ragstudio_model = model
        complete._ragstudio_base_url = base_url
        complete._ragstudio_api_key = api_key
        return complete

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

    @asynccontextmanager
    async def _scoped_chunks_vdb(
        self,
        rag: Any,
        document_ids: list[str],
    ) -> AsyncIterator[ScopedVectorStorageProxy]:
        await self._ensure_lightrag(rag)
        lightrag = getattr(rag, "lightrag", None)
        if lightrag is None or not hasattr(lightrag, "chunks_vdb"):
            raise RuntimeError("LightRAG chunks vector storage is not initialized.")

        original_chunks_vdb = lightrag.chunks_vdb
        proxy = ScopedVectorStorageProxy(original_chunks_vdb, document_ids)
        lightrag.chunks_vdb = proxy
        try:
            yield proxy
        finally:
            lightrag.chunks_vdb = original_chunks_vdb

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
            deduped[chunk_id] = {
                "chunk_id": chunk_id,
                "document_id": document_id,
                "text": str(row.get("content") or ""),
                "source_location": {"file_path": row.get("file_path")},
                "metadata": {
                    "full_doc_id": document_id,
                    "score": row.get("score"),
                    "native_scope": True,
                    "source_role": "retrieved_candidate",
                    "retrieval_scope": "document_ids",
                    "retrieval_mode": "native_vector_naive",
                },
            }
        return list(deduped.values())

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
        updates = {
            **self._postgres_env(),
            "POSTGRES_WORKSPACE": self._workspace(),
            "NEO4J_URI": self.profile.neo4j_uri or "",
            "NEO4J_USERNAME": self.profile.neo4j_username or "",
            "NEO4J_PASSWORD": self.profile.neo4j_password or "",
            "NEO4J_WORKSPACE": self._workspace(),
        }
        async with self._env_lock:
            previous = {key: os.environ.get(key) for key in updates}
            try:
                for key, value in updates.items():
                    if value:
                        os.environ[key] = value
                    else:
                        os.environ.pop(key, None)
                yield
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    def _postgres_env(self) -> dict[str, str]:
        url = make_url(self.settings.resolved_database_url)
        return {
            "POSTGRES_HOST": url.host or "127.0.0.1",
            "POSTGRES_PORT": str(url.port or 5432),
            "POSTGRES_USER": unquote(url.username or "postgres"),
            "POSTGRES_PASSWORD": unquote(url.password or ""),
            "POSTGRES_DATABASE": url.database or "ragstudio",
        }

    def _workspace(self) -> str:
        safe = "".join(
            character if character.isalnum() or character in {"_", "-"} else "_"
            for character in f"ragstudio_{self.profile.id}"
        ).strip("_")
        return safe or "ragstudio_default"

    def _workspace_label(self) -> str:
        return (self._workspace().strip() or "base").replace("`", "``")

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
    ) -> list[dict[str, Any]]:
        for chunk in chunks:
            parser_metadata = chunk.metadata.get("parser_metadata")
            if not isinstance(parser_metadata, dict):
                continue
            extract_dir = parser_metadata.get("artifact_extract_dir")
            content_ref = parser_metadata.get("content_list_ref")
            if not isinstance(extract_dir, str) or not isinstance(content_ref, str):
                continue
            root = Path(extract_dir).resolve()
            target = (root / content_ref).resolve()
            if target != root and root not in target.parents:
                continue
            try:
                data = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, list) and data:
                return [item for item in data if isinstance(item, dict)]

        content_list: list[dict[str, Any]] = []
        for chunk in chunks:
            page_idx = chunk.source_location.get("page")
            if not isinstance(page_idx, int):
                page = chunk.source_location.get("page_start")
                page_idx = page - 1 if isinstance(page, int) and page > 0 else None
            item: dict[str, Any] = {"type": chunk.content_type or "text", "text": chunk.text}
            if isinstance(page_idx, int):
                item["page_idx"] = page_idx
            content_list.append(item)
        return content_list

    def _runtime_chunks_from_adapter_chunks(
        self,
        chunks: list[AdapterChunk],
        path: Path,
    ) -> list[RuntimeChunk]:
        output: list[RuntimeChunk] = []
        seen_content_lists: set[tuple[str, str]] = set()
        for index, chunk in enumerate(chunks):
            parser_metadata = chunk.metadata.get("parser_metadata")
            metadata = dict(parser_metadata) if isinstance(parser_metadata, dict) else {}
            extract_dir = metadata.get("artifact_extract_dir")
            content_ref = metadata.get("content_list_ref")
            if isinstance(extract_dir, str) and isinstance(content_ref, str):
                content_key = (extract_dir, content_ref)
                if content_key in seen_content_lists:
                    continue
                seen_content_lists.add(content_key)
            metadata.update(
                {
                    "backend": metadata.get("backend", "mineru"),
                    "artifact_ref": metadata.get("artifact_ref", path.name),
                    "chunk_index": metadata.get("chunk_index", index),
                    "source_type": metadata.get("content_type", chunk.content_type),
                }
            )
            output.append(
                RuntimeChunk(
                    text=chunk.text,
                    source_location=chunk.source_location,
                    metadata=metadata,
                    runtime_source_id=str(metadata.get("artifact_ref") or index),
                    content_type=chunk.content_type,
                    preview_ref=chunk.preview_ref,
                )
            )
        return output

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
