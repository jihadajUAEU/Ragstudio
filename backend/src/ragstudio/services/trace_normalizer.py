from typing import Any

from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.runtime_types import RuntimeChunk, RuntimeQueryResult


class TraceNormalizer:
    def chunk_to_adapter_chunk(
        self,
        chunk: RuntimeChunk,
        *,
        document_id: str,
        runtime_profile_id: str,
        index_shape: dict[str, Any],
    ) -> AdapterChunk:
        metadata = {
            **chunk.metadata,
            "runtime_profile_id": runtime_profile_id,
            "runtime_source_id": chunk.runtime_source_id,
            "document_id": document_id,
            "content_type": chunk.content_type,
            "preview_ref": chunk.preview_ref,
            "index_shape": index_shape,
            "mirrored_snapshot": True,
        }
        return AdapterChunk(
            text=chunk.text,
            source_location=chunk.source_location,
            metadata=metadata,
        )

    def query_result(self, result: RuntimeQueryResult) -> dict[str, Any]:
        return {
            "answer": result.answer,
            "sources": result.sources,
            "chunk_traces": result.chunk_traces,
            "reranker_traces": result.reranker_traces,
            "timings": result.timings,
            "token_metadata": result.token_metadata,
            "error": result.error,
            "error_type": result.error_type,
        }
