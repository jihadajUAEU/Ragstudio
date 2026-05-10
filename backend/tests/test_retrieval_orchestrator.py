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
    async def search(self, search_in):
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


class FakeRuntimeTool:
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
            timings={"runtime_query_ms": 5, "native_scoped_query": True},
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
                text="Sahih al-Bukhari collection overview confirms 7277 hadith",
                document_id="doc-1",
                chunk_id="graph-1",
                source_location={"page": 2},
                metadata={
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
    assert any(trace["stage"] == "planner" for trace in result.chunk_traces)
    assert any(source["metadata"]["retrieval_tool"] == "graph" for source in result.sources)
    assert any(trace["stage"] == "graph_expansion" for trace in result.chunk_traces)


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
    assert answer_service.called is False
