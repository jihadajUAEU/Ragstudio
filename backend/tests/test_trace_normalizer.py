from ragstudio.services.runtime_types import RuntimeChunk, RuntimeQueryResult
from ragstudio.services.trace_normalizer import TraceNormalizer


def test_normalize_chunk_adds_runtime_metadata():
    chunk = RuntimeChunk(
        text="Evidence text",
        source_location={"page": 2},
        metadata={"score": 0.93},
        runtime_source_id="runtime-chunk-1",
        content_type="text",
        preview_ref=None,
    )

    normalized = TraceNormalizer().chunk_to_adapter_chunk(
        chunk,
        document_id="doc-1",
        runtime_profile_id="default",
        index_shape={"embedding_model": "text-embedding-3-large"},
    )

    assert normalized.text == "Evidence text"
    assert normalized.metadata["runtime_profile_id"] == "default"
    assert normalized.metadata["runtime_source_id"] == "runtime-chunk-1"
    assert normalized.metadata["index_shape"]["embedding_model"] == "text-embedding-3-large"


def test_normalize_query_result_keeps_reranker_and_token_metadata():
    result = RuntimeQueryResult(
        answer="Grounded answer",
        sources=[{"chunk_id": "chunk-1"}],
        chunk_traces=[{"rank": 1}],
        reranker_traces=[{"rank": 1, "score": 0.99}],
        timings={"query_ms": 12},
        token_metadata={"prompt_tokens": 10},
        error=None,
        error_type=None,
    )

    normalized = TraceNormalizer().query_result(result)

    assert normalized["answer"] == "Grounded answer"
    assert normalized["reranker_traces"][0]["score"] == 0.99
    assert normalized["token_metadata"]["prompt_tokens"] == 10
