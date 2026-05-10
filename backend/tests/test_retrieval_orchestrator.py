import pytest
from ragstudio.schemas.chunks import ChunkOut
from ragstudio.services.retrieval_evidence import (
    EvidenceCandidate,
    fuse_candidates,
    plan_for_query,
)
from ragstudio.services.retrieval_orchestrator import RetrievalOrchestrator
from ragstudio.services.runtime_types import RuntimeQueryResult


def test_plan_for_count_query_prefers_metadata_and_native():
    plan = plan_for_query("how many hadith in bukhari", document_ids=["doc-1"], limit=8)

    assert plan.intent == "count"
    assert plan.use_native is True
    assert plan.use_metadata is True
    assert plan.use_relationships is True
    assert plan.candidate_limit == 20
    assert plan.document_ids == ["doc-1"]


def test_plan_for_reference_query_marks_reference_intent():
    plan = plan_for_query("show Book 64 Hadith 486", document_ids=[], limit=8)

    assert plan.intent == "reference"
    assert plan.use_native is True
    assert plan.use_metadata is True
    assert plan.use_relationships is True


def test_evidence_candidate_serializes_source_and_trace():
    candidate = EvidenceCandidate(
        candidate_id="metadata:chunk-1",
        text="Sahih al-Bukhari\n\n7277 Hadith Collection",
        document_id="doc-1",
        chunk_id="chunk-1",
        source_location={"page": 1},
        metadata={"document_metadata": {"title": "Sahih al-Bukhari 7277 Hadith Collection"}},
        tool="metadata",
        tool_rank=1,
        base_score=10.0,
        boost_score=12.0,
        final_score=22.0,
        reasons=["title_count_match"],
    )

    assert candidate.to_source()["chunk_id"] == "chunk-1"
    assert candidate.to_source()["metadata"]["retrieval_tool"] == "metadata"
    assert candidate.to_trace()["candidate_id"] == "metadata:chunk-1"
    assert candidate.to_trace()["reasons"] == ["title_count_match"]


def test_fusion_boosts_title_count_chunk_for_count_query():
    plan = plan_for_query("how many hadith in bukhari", document_ids=["doc-1"], limit=3)
    weak_native = EvidenceCandidate(
        candidate_id="native:n1",
        text="Book 65, Hadith 201",
        document_id="doc-1",
        chunk_id="n1",
        source_location={},
        metadata={"native_scope": True},
        tool="native",
        tool_rank=1,
        base_score=8.0,
    )
    title_count = EvidenceCandidate(
        candidate_id="metadata:m1",
        text="Sahih al-Bukhari\n\n7277 Hadith Collection",
        document_id="doc-1",
        chunk_id="m1",
        source_location={},
        metadata={"document_metadata": {"title": "Sahih al-Bukhari 7277 Hadith Collection"}},
        tool="metadata",
        tool_rank=1,
        base_score=6.0,
    )

    fused = fuse_candidates(plan, [weak_native, title_count])

    assert fused[0].chunk_id == "m1"
    assert "answer_bearing_count" in fused[0].reasons
    assert fused[0].final_score > weak_native.base_score


def test_fusion_dedupes_by_text_and_keeps_best_candidate():
    plan = plan_for_query("alpha", document_ids=["doc-1"], limit=3)
    native = EvidenceCandidate(
        candidate_id="native:n1",
        text="Same text",
        document_id="doc-1",
        chunk_id=None,
        source_location={},
        metadata={"runtime_source_id": "shared"},
        tool="native",
        tool_rank=1,
        base_score=8.0,
    )
    metadata = EvidenceCandidate(
        candidate_id="metadata:m1",
        text="Same text",
        document_id="doc-1",
        chunk_id=None,
        source_location={},
        metadata={"runtime_source_id": "shared", "score": 10.0},
        tool="metadata",
        tool_rank=1,
        base_score=10.0,
    )

    fused = fuse_candidates(plan, [native, metadata])

    assert len(fused) == 1
    assert fused[0].tool == "metadata"
    assert fused[0].metadata["deduped_tools"] == ["native", "metadata"]


class FakeChunkSearchService:
    def __init__(self):
        self.calls = 0
        self.chunk_lookup_calls = []

    async def search(self, search_in):
        self.calls += 1
        return type(
            "SearchResult",
            (),
            {
                "items": [
                    ChunkOut(
                        id="metadata-1",
                        document_id="doc-1",
                        text="Sahih al-Bukhari\n\n7277 Hadith Collection",
                        source_location={"page": 1},
                        metadata={
                            "document_metadata": {
                                "title": "Sahih al-Bukhari 7277 Hadith Collection"
                            },
                            "score": 10.0,
                        },
                    )
                ],
                "total": 1,
            },
        )()

    async def chunks_by_id(self, chunk_ids):
        self.chunk_lookup_calls.append(chunk_ids)
        return [
            ChunkOut(
                id="graph-1",
                document_id="doc-1",
                text="Full hydrated graph chunk confirms 7277 hadith in Sahih al-Bukhari.",
                source_location={"page": 9},
                metadata={"reference_metadata": {"references": ["collection:bukhari"]}},
            )
            for chunk_id in chunk_ids
            if chunk_id == "graph-1"
        ]


class FakeRuntimeTool:
    def __init__(self, *, error_type=None, error=None, timings=None):
        self.error_type = error_type
        self.error = error
        self.timings = timings or {"runtime_query_ms": 5, "native_scoped_query": True}

    async def query(self, query, *, document_ids, query_config):
        return RuntimeQueryResult(
            answer="native answer ignored",
            sources=[
                {
                    "chunk_id": "native-1",
                    "document_id": "doc-1",
                    "text": "Book 65, Hadith 201",
                    "source_location": {},
                    "metadata": {"native_scope": True},
                }
            ],
            error=self.error,
            error_type=self.error_type,
            timings=self.timings,
        )


class FailingRuntimeTool:
    async def query(self, query, *, document_ids, query_config):
        return RuntimeQueryResult(
            answer="",
            sources=[],
            error="runtime exploded",
            error_type="runtime_query_error",
            timings={"runtime_query_ms": 4},
        )


class ExplodingNativeRuntimeTool:
    async def query(self, query, *, document_ids, query_config):
        raise RuntimeError("native query crashed")


class ExplodingChunkSearchService:
    async def search(self, search_in):
        raise RuntimeError("metadata search exploded")


class MetadataSearchShouldNotRun:
    def __init__(self):
        self.calls = 0

    async def search(self, search_in):
        self.calls += 1
        raise AssertionError("metadata search should not run")


class FakeAnswerService:
    def __init__(self):
        self.evidence = []
        self.called = False

    async def answer(self, query, evidence, profile):
        self.called = True
        self.evidence = evidence
        return "Sahih al-Bukhari contains 7277 hadith.", {"prompt_tokens": 12}


class FakeRerankerService:
    async def rerank(self, query, chunks, profile):
        return chunks, [{"provider": "disabled", "status": "disabled"}]


class FakeGraphExpansionService:
    async def expand(self, query, *, seeds, profile, document_ids, limit):
        return [
            EvidenceCandidate(
                candidate_id="graph:g1",
                text="Preview-only graph text",
                document_id="doc-1",
                chunk_id="graph-1",
                source_location={"page": 2},
                metadata={
                    "text_preview": "Preview-only graph text",
                    "graph_relationship": {
                        "type": "RELATED",
                        "seed": {"chunk_id": seeds[0].chunk_id},
                    }
                },
                tool="graph",
                tool_rank=1,
                base_score=12.0,
                boost_score=2.0,
                final_score=14.0,
                reasons=["graph_neighbor"],
            )
        ], [{"stage": "graph_expansion", "status": "ok", "expanded_candidates": 1}]


class FailingGraphExpansionService:
    async def expand(self, query, *, seeds, profile, document_ids, limit):
        raise RuntimeError("neo4j unavailable")


@pytest.mark.asyncio
async def test_orchestrator_fuses_native_metadata_and_graph_before_answering():
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "how many hadith in bukhari",
        runtime=FakeRuntimeTool(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 8},
    )

    assert result.answer == "Sahih al-Bukhari contains 7277 hadith."
    assert result.sources[0]["chunk_id"] == "metadata-1"
    assert answer_service.evidence[0].chunk_id == "metadata-1"
    assert result.timings["orchestrated_query"] is True
    assert result.timings["planner_ms"] >= 0
    assert result.timings["native_stage_ms"] >= 0
    assert result.timings["graph_hydration_ms"] >= 0
    assert any(trace["stage"] == "planner" for trace in result.chunk_traces)
    assert any(source["metadata"]["retrieval_tool"] == "graph" for source in result.sources)
    assert any(trace["stage"] == "graph_expansion" for trace in result.chunk_traces)
    assert any(trace["stage"] == "graph_hydration" for trace in result.chunk_traces)
    graph_evidence = next(
        candidate for candidate in answer_service.evidence if candidate.tool == "graph"
    )
    assert graph_evidence.text == (
        "Full hydrated graph chunk confirms 7277 hadith in Sahih al-Bukhari."
    )
    assert graph_evidence.source_location == {"page": 9}
    assert graph_evidence.metadata["graph_hydration"]["status"] == "hydrated"


@pytest.mark.asyncio
async def test_orchestrator_preserves_runtime_query_errors():
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "boom",
        runtime=FailingRuntimeTool(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 8},
    )

    assert result.answer == ""
    assert result.error == "runtime exploded"
    assert result.error_type == "runtime_query_error"
    assert result.sources == []
    assert result.timings["runtime_query_ms"] == 4
    assert result.timings["metadata_ms"] >= 0
    assert answer_service.called is False


@pytest.mark.asyncio
async def test_orchestrator_fails_when_native_scoped_query_is_unsupported():
    answer_service = FakeAnswerService()
    chunk_service = MetadataSearchShouldNotRun()
    orchestrator = RetrievalOrchestrator(
        chunk_service=chunk_service,
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "how many hadith in bukhari",
        runtime=FakeRuntimeTool(
            error=(
                "LightRAG vector storage does not support storage-level "
                "full_doc_id filtering."
            ),
            error_type="native_document_scope_unsupported",
            timings={"runtime_query_ms": 7, "native_scoped_query": True},
        ),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 8},
    )

    assert result.answer == ""
    assert result.error_type == "native_document_scope_unsupported"
    assert "full_doc_id filtering" in (result.error or "")
    assert result.sources == []
    assert result.timings["runtime_query_ms"] == 7
    assert result.timings["native_scoped_query"] is True
    assert result.timings["native_stage_ms"] >= 0
    assert "metadata_ms" not in result.timings
    assert result.chunk_traces == []
    assert chunk_service.calls == 0
    assert answer_service.called is False


@pytest.mark.asyncio
async def test_orchestrator_graph_failure_degrades_gracefully():
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FailingGraphExpansionService(),
    )

    result = await orchestrator.query(
        "how many hadith in bukhari",
        runtime=FakeRuntimeTool(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 8},
    )

    assert result.error is None
    assert result.answer == "Sahih al-Bukhari contains 7277 hadith."
    graph_trace = next(
        trace for trace in result.chunk_traces if trace["stage"] == "graph_expansion"
    )
    assert graph_trace["status"] == "failed"
    assert graph_trace["reason"] == "RuntimeError"
    assert result.timings["graph_ms"] >= 0
    assert result.timings["graph_degraded"] is True
    assert result.timings["graph_error_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_orchestrator_preserves_native_context_when_both_retrieval_paths_fail():
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=ExplodingChunkSearchService(),
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "boom",
        runtime=FailingRuntimeTool(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 8},
    )

    assert result.answer == ""
    assert result.error_type == "parallel_retrieval_failed"
    assert "native=runtime exploded" in (result.error or "")
    assert "metadata=metadata search exploded" in (result.error or "")
    assert result.timings["runtime_query_ms"] == 4
    assert result.timings["native_stage_ms"] >= 0
    assert result.timings["parallel_retrieval_ms"] >= 0
    assert answer_service.called is False


@pytest.mark.asyncio
async def test_orchestrator_short_circuits_scoped_native_unsupported_before_metadata():
    answer_service = FakeAnswerService()
    chunk_service = MetadataSearchShouldNotRun()
    orchestrator = RetrievalOrchestrator(
        chunk_service=chunk_service,
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "boom",
        runtime=FakeRuntimeTool(
            error="native scoped unsupported",
            error_type="native_document_scope_unsupported",
            timings={"runtime_query_ms": 7, "native_scoped_query": True},
        ),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 8},
    )

    assert result.answer == ""
    assert result.error_type == "native_document_scope_unsupported"
    assert result.error == "native scoped unsupported"
    assert result.timings["runtime_query_ms"] == 7
    assert result.timings["native_scoped_query"] is True
    assert result.timings["native_stage_ms"] >= 0
    assert "metadata_ms" not in result.timings
    assert "metadata_error_type" not in result.timings
    assert chunk_service.calls == 0
    assert answer_service.called is False


@pytest.mark.asyncio
async def test_orchestrator_preserves_thrown_native_exception_when_metadata_also_fails():
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=ExplodingChunkSearchService(),
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "boom",
        runtime=ExplodingNativeRuntimeTool(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 8},
    )

    assert result.answer == ""
    assert result.error_type == "parallel_retrieval_failed"
    assert "native=native query crashed" in (result.error or "")
    assert result.timings["native_error_type"] == "RuntimeError"
    assert result.timings["metadata_error_type"] == "RuntimeError"
    assert answer_service.called is False


@pytest.mark.asyncio
async def test_orchestrator_marks_skipped_graph_infrastructure_as_degraded():
    answer_service = FakeAnswerService()

    class DriverUnavailableGraphExpansionService:
        async def expand(self, query, *, seeds, profile, document_ids, limit):
            return [], [
                {
                    "stage": "graph_expansion",
                    "status": "skipped",
                    "reason": "driver_unavailable",
                }
            ]

    orchestrator = RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=DriverUnavailableGraphExpansionService(),
    )

    result = await orchestrator.query(
        "how many hadith in bukhari",
        runtime=FakeRuntimeTool(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 8},
    )

    assert result.error is None
    assert result.timings["graph_degraded"] is True
    assert result.timings["graph_error_type"] == "driver_unavailable"
