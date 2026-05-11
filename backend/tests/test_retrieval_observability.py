from ragstudio.services.retrieval_observability import RetrievalObservability, retrieval_cache_key


def test_exact_arabic_queries_bypass_answer_cache():
    trace = RetrievalObservability().cache_decision(
        query="وحنانا",
        document_ids=["doc-quran"],
        query_type="exact_arabic_token",
    )

    assert trace["answer_cache"] == "bypass"
    assert trace["reason"] == "direct_evidence_query"


def test_retrieval_trace_records_stage_counts_and_latency():
    obs = RetrievalObservability()

    obs.record_stage("arabic_lexical", candidate_count=2, latency_ms=12.5)
    obs.record_stage(
        "fusion",
        candidate_count=1,
        latency_ms=1.0,
        detail={"compat_stage": "retrieval_fusion"},
    )

    assert obs.trace["stages"][0]["stage"] == "arabic_lexical"
    assert obs.trace["stages"][0]["candidate_count"] == 2
    assert obs.trace["stages"][1]["latency_ms"] == 1.0
    assert obs.trace["stages"][1]["compat_stage"] == "retrieval_fusion"


def test_cache_key_includes_index_profile_dimension_and_reranker_state():
    key = retrieval_cache_key(
        query="وحنانا",
        document_ids=["doc-b", "doc-a"],
        index_version="idx-7",
        runtime_profile="postgres_pgvector_neo4j",
        parser_mode="mineru_strict",
        embedding_model_id="Qwen/Qwen3-Embedding-8B",
        embedding_dimension=1536,
        reranker_enabled=False,
    )

    assert "doc-a,doc-b" in key
    assert "idx-7" in key
    assert "mineru_strict" in key
    assert "1536" in key
    assert "reranker=False" in key
