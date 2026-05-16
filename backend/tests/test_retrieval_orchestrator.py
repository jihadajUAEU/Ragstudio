import asyncio

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


def test_plan_for_reference_context_query_sets_graph_context_strategy():
    plan = plan_for_query(
        "Explain 1:5 and show the surrounding connected verses",
        document_ids=["doc-tafseer"],
        limit=5,
    )

    assert plan.intent == "reference"
    assert plan.retrieval_strategy == "graph_context_hybrid"
    assert plan.graph_context_required is True


def test_plan_for_arabic_token_carries_retrieval_passes():
    plan = plan_for_query("حنانا", document_ids=["doc-quran"], limit=5)

    assert plan.intent == "reference"
    assert plan.understanding is not None
    assert plan.understanding.intent == "arabic_exact_token"
    assert [item.name for item in plan.understanding.retrieval_passes] == [
        "arabic_exact_token",
        "semantic_metadata",
        "vector_db",
        "native_vector",
    ]


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


def test_evidence_candidate_serializes_retrieval_pass_and_match_features():
    candidate = EvidenceCandidate(
        candidate_id="arabic:chunk-19-13",
        text="[19:13] وَحَنَانًا مِّن لَّدُنَّا",
        document_id="doc-quran",
        chunk_id="chunk-19-13",
        source_location={"page": 312, "reference": "19:13"},
        metadata={},
        tool="arabic_lexical",
        tool_rank=1,
        base_score=10.0,
        retrieval_pass="arabic_exact_token",
        match_features={"arabic_exact": True, "arabic_token": "حنانا"},
        canonical_reference="19:13",
        scope_status="in_scope",
        source_quality={"parser": "mineru", "warnings": 0},
        risk_flags=[],
    )

    source = candidate.to_source()
    trace = candidate.to_trace()

    assert source["metadata"]["retrieval_pass"] == "arabic_exact_token"
    assert source["metadata"]["match_features"] == {
        "arabic_exact": True,
        "arabic_token": "حنانا",
    }
    assert source["metadata"]["canonical_reference"] == "19:13"
    assert source["metadata"]["scope_status"] == "in_scope"
    assert trace["retrieval_pass"] == "arabic_exact_token"
    assert trace["match_features"]["arabic_exact"] is True


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


def test_fusion_keeps_exact_reference_first_and_boosts_graph_context_neighbors():
    plan = plan_for_query(
        "Explain 1:5 and show the surrounding connected verses",
        document_ids=["doc-tafseer"],
        limit=5,
    )
    exact = EvidenceCandidate(
        candidate_id="metadata:1-5",
        text="Verse 1:5 Guide us to the straight path.",
        document_id="doc-tafseer",
        chunk_id="chunk-1-5",
        source_location={"reference": "1:5"},
        metadata={},
        tool="metadata",
        tool_rank=1,
        base_score=10.0,
        retrieval_pass="reference_exact",
    )
    neighbor = EvidenceCandidate(
        candidate_id="graph:1-4",
        text="Verse 1:4 It is You we worship and You we ask for help.",
        document_id="doc-tafseer",
        chunk_id="chunk-1-4",
        source_location={"reference": "1:4"},
        metadata={"graph_relationship": {"type": "REFERENCES", "path": "reference_hop"}},
        tool="graph",
        tool_rank=1,
        base_score=10.0,
    )

    fused = fuse_candidates(plan, [neighbor, exact])

    assert fused[0].chunk_id == "chunk-1-5"
    assert fused[1].chunk_id == "chunk-1-4"
    assert "reference_first_hybrid" in fused[0].reasons
    assert "query_requested_graph_context" in fused[1].reasons


def test_domain_aware_fusion_boosts_tafseer_exact_reference():
    plan = plan_for_query("Explain 1:5", document_ids=["doc-tafseer"], limit=5)
    tafseer_exact = EvidenceCandidate(
        candidate_id="metadata:tafseer-1-5",
        text="Verse 1:5 Guide us to the straight path.",
        document_id="doc-tafseer",
        chunk_id="chunk-tafseer-1-5",
        source_location={"reference": "1:5"},
        metadata={
            "domain_metadata": {
                "domain": "quran_tafseer",
                "tags": ["quran"],
                "script": "arabic",
            },
            "reference_metadata": {"references": ["1:5"]},
            "quality_action_policy": {
                "index_exact_arabic": True,
                "graph_confidence": "trusted",
            },
        },
        tool="metadata",
        tool_rank=1,
        base_score=10.0,
        retrieval_pass="reference_exact",
    )
    generic_native = EvidenceCandidate(
        candidate_id="native:generic",
        text="A generic discussion of guidance.",
        document_id="doc-tafseer",
        chunk_id="chunk-generic",
        source_location={},
        metadata={"domain_metadata": {"domain": "generic"}},
        tool="native",
        tool_rank=1,
        base_score=20.0,
    )

    fused = fuse_candidates(plan, [generic_native, tafseer_exact])

    assert fused[0].chunk_id == "chunk-tafseer-1-5"
    assert "tafseer_reference_exact" in fused[0].reasons


def test_domain_aware_fusion_does_not_apply_tafseer_boost_to_research_paper():
    plan = plan_for_query("Explain 1:5", document_ids=["doc-paper"], limit=5)
    paper_candidate = EvidenceCandidate(
        candidate_id="metadata:paper-section",
        text="Section 1.5 describes retrieval methodology.",
        document_id="doc-paper",
        chunk_id="chunk-paper-1-5",
        source_location={"section": "1.5"},
        metadata={
            "domain_metadata": {
                "domain": "research",
                "document_type": "paper",
            },
        },
        tool="metadata",
        tool_rank=1,
        base_score=10.0,
        retrieval_pass="reference_exact",
    )

    fused = fuse_candidates(plan, [paper_candidate])

    assert "tafseer_reference_exact" not in fused[0].reasons
    assert "hadith_reference_exact" not in fused[0].reasons


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


def test_fusion_preserves_direct_fields_from_lower_scored_duplicate():
    plan = plan_for_query("حنانا", document_ids=["doc-quran"], limit=3)
    semantic = EvidenceCandidate(
        candidate_id="pgvector:chunk-19-13",
        text="[19:13] وَحَنَانًا مِّن لَّدُنَّا",
        document_id="doc-quran",
        chunk_id="chunk-19-13",
        source_location={"page": 312, "reference": "19:13"},
        metadata={},
        tool="pgvector",
        tool_rank=1,
        base_score=20.0,
        retrieval_pass="vector_db",
    )
    arabic = EvidenceCandidate(
        candidate_id="arabic:chunk-19-13",
        text="[19:13] وَحَنَانًا مِّن لَّدُنَّا",
        document_id="doc-quran",
        chunk_id="chunk-19-13",
        source_location={"page": 312, "reference": "19:13"},
        metadata={},
        tool="arabic_lexical",
        tool_rank=2,
        base_score=10.0,
        retrieval_pass="arabic_exact_token",
        match_features={"arabic_exact": True, "arabic_token": "حنانا"},
        canonical_reference="19:13",
        scope_status="in_scope",
        risk_flags=["parser_warning"],
    )

    fused = fuse_candidates(plan, [semantic, arabic])

    assert len(fused) == 1
    result = fused[0]
    assert result.tool == "pgvector"
    assert result.match_features["arabic_exact"] is True
    assert result.metadata["retrieval_passes"] == ["vector_db", "arabic_exact_token"]
    assert result.canonical_reference == "19:13"
    assert result.scope_status == "in_scope"
    assert result.risk_flags == ["parser_warning"]


def test_fusion_merges_parser_warnings_when_native_duplicate_wins():
    warning = {
        "code": "reference_unit_missing_expected_script",
        "message": "Expected Arabic text.",
        "block_type": "paragraph",
    }
    plan = plan_for_query("alpha", document_ids=["doc-1"], limit=3)
    native = EvidenceCandidate(
        candidate_id="native:shared",
        text="Same text",
        document_id="doc-1",
        chunk_id="shared",
        source_location={},
        metadata={"native_scope": True},
        tool="native",
        tool_rank=1,
        base_score=20.0,
    )
    metadata = EvidenceCandidate(
        candidate_id="metadata:shared",
        text="Same text",
        document_id="doc-1",
        chunk_id="shared",
        source_location={},
        metadata={"extraction_quality": {"parser_warnings": [warning]}, "score": 10.0},
        tool="metadata",
        tool_rank=1,
        base_score=10.0,
    )

    fused = fuse_candidates(plan, [native, metadata])

    assert len(fused) == 1
    assert fused[0].tool == "native"
    assert fused[0].metadata["extraction_quality"]["parser_warnings"] == [warning]
    assert fused[0].metadata["deduped_tools"] == ["native", "metadata"]


def test_fusion_hydrates_parser_warnings_when_native_row_id_differs():
    warning = {
        "code": "reference_unit_missing_expected_script",
        "message": "Expected Arabic text.",
        "block_type": "paragraph",
    }
    plan = plan_for_query("alpha", document_ids=["doc-1"], limit=3)
    native = EvidenceCandidate(
        candidate_id="native:lightrag-row-7",
        text="Same parser-warning text",
        document_id="doc-1",
        chunk_id="lightrag-row-7",
        source_location={},
        metadata={"native_scope": True},
        tool="native",
        tool_rank=1,
        base_score=20.0,
    )
    metadata = EvidenceCandidate(
        candidate_id="metadata:studio-chunk-1",
        text="Same parser-warning text",
        document_id="doc-1",
        chunk_id="studio-chunk-1",
        source_location={},
        metadata={"extraction_quality": {"parser_warnings": [warning]}, "score": 10.0},
        tool="metadata",
        tool_rank=1,
        base_score=10.0,
    )

    fused = fuse_candidates(plan, [native, metadata])

    native_result = next(candidate for candidate in fused if candidate.tool == "native")
    assert native_result.chunk_id == "lightrag-row-7"
    assert native_result.metadata["extraction_quality"]["parser_warnings"] == [warning]


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


class ParserWarningChunkSearchService(FakeChunkSearchService):
    async def search(self, search_in):
        self.calls += 1
        return type(
            "SearchResult",
            (),
            {
                "items": [
                    ChunkOut(
                        id="parser-warning-1",
                        document_id="doc-1",
                        text="Parser warning evidence remains usable.",
                        source_location={"page": 4},
                        metadata={
                            "score": 10.0,
                            "extraction_quality": {
                                "parser_warnings": [
                                    {
                                        "code": "reference_unit_missing_expected_script",
                                        "message": "Expected Arabic text.",
                                        "block_type": "paragraph",
                                    }
                                ]
                            },
                        },
                    )
                ],
                "total": 1,
            },
        )()


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


class EmptyRuntimeTool:
    async def query(self, query, *, document_ids, query_config):
        return RuntimeQueryResult(
            answer="",
            sources=[],
            timings={"runtime_query_ms": 3, "native_scoped_query": True},
        )


class NativeDuplicateParserWarningRuntimeTool:
    async def query(self, query, *, document_ids, query_config):
        return RuntimeQueryResult(
            answer="native answer ignored",
            sources=[
                {
                    "chunk_id": "parser-warning-1",
                    "document_id": "doc-1",
                    "text": "Native parser warning evidence.",
                    "source_location": {},
                    "metadata": {"native_scope": True},
                }
            ],
            timings={"runtime_query_ms": 5, "native_scoped_query": True},
        )


class NativeMismatchedParserWarningRuntimeTool:
    async def query(self, query, *, document_ids, query_config):
        return RuntimeQueryResult(
            answer="native answer ignored",
            sources=[
                {
                    "chunk_id": "lightrag-row-7",
                    "document_id": "doc-1",
                    "text": "Parser warning evidence remains usable.",
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


class SlowRuntimeTool:
    async def query(self, query, *, document_ids, query_config):
        await asyncio.sleep(1)
        return RuntimeQueryResult(answer="late", sources=[])


class ExplodingNativeRuntimeTool:
    async def query(self, query, *, document_ids, query_config):
        raise RuntimeError("native query crashed")


class DegradedPreflightRuntimeTool:
    def __init__(self):
        self.preflight_calls = []
        self.query_called = False

    async def preflight_scoped_retrieval(self, document_ids):
        self.preflight_calls.append(list(document_ids))
        return {
            "status": "degraded",
            "error_type": "native_document_scope_unsupported",
            "detail": (
                "LightRAG vector storage does not support storage-level "
                "full_doc_id filtering."
            ),
            "embedding_dimensions": 1536,
            "send_dimensions": True,
            "scoped_cache_policy": "disabled_for_query",
        }

    async def query(self, query, *, document_ids, query_config):
        self.query_called = True
        raise AssertionError("runtime.query should not run after degraded preflight")


class HangingPreflightRuntimeTool:
    def __init__(self):
        self.preflight_calls = []
        self.query_called = False

    async def preflight_scoped_retrieval(self, document_ids):
        self.preflight_calls.append(list(document_ids))
        await asyncio.sleep(1)
        return {"status": "ok"}

    async def query(self, query, *, document_ids, query_config):
        self.query_called = True
        raise AssertionError("runtime.query should not run after preflight timeout")


class NativeSearchShouldNotRun:
    async def query(self, query, *, document_ids, query_config):
        raise AssertionError("native search should not run")


class ExplodingChunkSearchService:
    async def search(self, search_in):
        raise RuntimeError("metadata search exploded")


class EmptyQualityReportChunkSearchService:
    def __init__(self, report):
        self.report = report
        self.calls = 0

    async def search(self, search_in):
        self.calls += 1
        return type("SearchResult", (), {"items": [], "total": 0})()

    async def quality_reports_for_documents(self, document_ids):
        return [
            {**self.report, "document_id": document_id}
            for document_id in document_ids
        ]


class GraphHydrationFailingChunkSearchService(FakeChunkSearchService):
    async def chunks_by_id(self, chunk_ids):
        raise RuntimeError("chunk lookup failed")


class GraphHydrationMissingChunkSearchService(FakeChunkSearchService):
    async def chunks_by_id(self, chunk_ids):
        self.chunk_lookup_calls.append(chunk_ids)
        return []


class GraphHydrationWrongDocumentChunkSearchService(FakeChunkSearchService):
    async def chunks_by_id(self, chunk_ids):
        self.chunk_lookup_calls.append(chunk_ids)
        return [
            ChunkOut(
                id="graph-1",
                document_id="doc-2",
                text="This hydrated chunk belongs to a different document.",
                source_location={"page": 99},
                metadata={"reference_metadata": {"references": ["collection:other"]}},
            )
            for chunk_id in chunk_ids
            if chunk_id == "graph-1"
        ]


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


class SlowAnswerService:
    def __init__(self):
        self.called = False

    async def answer(self, query, evidence, profile):
        self.called = True
        await asyncio.sleep(0.05)
        return "This slow LLM answer should not be returned in fast mode.", {
            "prompt_tokens": 4000,
        }


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
    assert any(trace.get("stage") == "planner" for trace in result.chunk_traces)
    assert any(trace.get("stage") == "final_fusion" for trace in result.chunk_traces)
    assert any(trace.get("stage") == "retrieval_fusion" for trace in result.chunk_traces)
    context_trace = next(
        trace for trace in result.chunk_traces if trace.get("stage") == "context_assembly"
    )
    assert context_trace["included_candidates"] >= 1
    assert context_trace["assembled_context"]["grounding_status"] == "insufficient_evidence"
    assert "metadata:metadata-1" in context_trace["retrieval_observability"]["final_evidence_ids"]
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
async def test_orchestrator_returns_evidence_first_answer_when_fast_llm_budget_expires():
    answer_service = SlowAnswerService()
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
        query_config={
            "limit": 8,
            "response_mode": "fast",
            "answer_budget_ms": 1,
        },
    )

    assert answer_service.called is True
    assert result.error is None
    assert result.error_type is None
    assert result.sources
    assert any(source["metadata"]["retrieval_tool"] == "graph" for source in result.sources)
    assert result.answer.startswith("Evidence-first result")
    assert "Sahih al-Bukhari" in result.answer
    assert result.token_metadata["answer_mode"] == "evidence_first"
    assert result.token_metadata["generated_without_llm"] is True
    assert result.token_metadata["llm_answer_status"] == "timeout"
    assert result.token_metadata["llm_timeout_ms"] == 1
    assert result.timings["answer_fallback"] is True
    assert result.timings["answer_timeout_ms"] == 1


@pytest.mark.asyncio
async def test_orchestrator_emits_primary_seed_expansion_and_final_fusion_stages():
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

    stages = [trace.get("stage") for trace in result.chunk_traces if isinstance(trace, dict)]
    assert "primary_retrieval" in stages
    assert "seed_fusion" in stages
    assert "graph_expansion" in stages
    assert "final_fusion" in stages
    assert "retrieval_fusion" in stages
    assert any(
        trace.get("stage") == "final_fusion"
        and trace.get("compat_stage") == "retrieval_fusion"
        for trace in result.chunk_traces
    )
    assert any(
        trace.get("stage") == "retrieval_fusion"
        and trace.get("canonical_stage") == "final_fusion"
        for trace in result.chunk_traces
    )
    assert result.error is None
    assert answer_service.called is True


@pytest.mark.asyncio
async def test_orchestrator_records_grounding_validation_trace():
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

    validation_trace = next(
        trace for trace in result.chunk_traces if trace.get("stage") == "grounding_validation"
    )
    assert validation_trace["status"] in {"grounded", "failed"}
    assert "available_labels" in validation_trace
    assert result.validation == validation_trace


@pytest.mark.asyncio
async def test_orchestrator_uses_query_reference_hints_for_grounding_validation():
    orchestrator = RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        answer_service=FakeAnswerService(),
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "show 19:13",
        runtime=FakeRuntimeTool(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 8},
    )

    assert result.validation["status"] == "failed"
    assert {
        "code": "expected_reference_not_in_sources",
        "detail": "Expected references missing from sources: 19:13",
    } in result.validation["failures"]


@pytest.mark.asyncio
async def test_orchestrator_surfaces_parser_quality_warnings_in_evidence_and_traces():
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=ParserWarningChunkSearchService(),
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "parser warning",
        runtime=FakeRuntimeTool(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 8, "graph_expansion_enabled": False},
    )

    assert result.error is None
    warning_code = "reference_unit_missing_expected_script"
    source = next(
        source for source in result.sources if source["chunk_id"] == "parser-warning-1"
    )
    assert source["metadata"]["parser_quality_warning_codes"] == [warning_code]
    assert f"parser_quality_warning:{warning_code}" in source["metadata"]["retrieval_reasons"]
    assert any(
        trace.get("stage") == "parser_quality"
        and trace.get("warning_counts") == {warning_code: 1}
        and "metadata:parser-warning-1" in trace.get("affected_candidate_ids", [])
        for trace in result.chunk_traces
    )
    evidence = next(
        candidate
        for candidate in answer_service.evidence
        if candidate.chunk_id == "parser-warning-1"
    )
    assert evidence.metadata["parser_quality_warning_codes"] == [warning_code]
    assert f"parser_quality_warning:{warning_code}" in evidence.reasons


@pytest.mark.asyncio
async def test_orchestrator_emits_quality_diagnostics_when_arabic_candidates_are_empty():
    report = {
        "quality_report_version": 1,
        "status": "ready_with_warnings",
        "domain_profile": "quran_tafseer",
        "references": [
            {
                "reference": "19:13",
                "expected_scripts": ["arabic", "latin"],
                "observed_scripts": ["latin"],
                "missing_scripts": ["arabic"],
                "status": "missing_expected_script",
                "materialization": {"index_exact_arabic": False},
            }
        ],
        "summary": {"reference_units_missing_expected_script": 1},
    }
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=EmptyQualityReportChunkSearchService(report),
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "\u062d\u0646\u0627\u0646\u0627",
        runtime=EmptyRuntimeTool(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-quran"],
        variant_id="variant-1",
        query_config={"limit": 8, "graph_expansion_enabled": False},
    )

    trace = next(
        item for item in result.chunk_traces if item.get("stage") == "quality_diagnostics"
    )
    assert trace["status"] == "warning"
    assert trace["query_script"] == "arabic"
    assert trace["affected_references"] == ["19:13"]
    assert trace["documents"][0]["document_id"] == "doc-quran"


@pytest.mark.asyncio
async def test_orchestrator_reports_legacy_quality_unknown_for_empty_arabic_results():
    report = {
        "quality_report_version": None,
        "status": "quality_unknown",
        "domain_profile": "quran_tafseer",
        "references": [],
        "summary": {"quality_unknown_document_count": 1},
    }
    orchestrator = RetrievalOrchestrator(
        chunk_service=EmptyQualityReportChunkSearchService(report),
        answer_service=FakeAnswerService(),
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "\u062d\u0646\u0627\u0646\u0627",
        runtime=EmptyRuntimeTool(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["legacy-doc"],
        variant_id="variant-1",
        query_config={"limit": 8, "graph_expansion_enabled": False},
    )

    trace = next(
        item for item in result.chunk_traces if item.get("stage") == "quality_diagnostics"
    )
    assert trace["status"] == "unknown"
    assert trace["quality_status"] == "quality_unknown"
    assert trace["quality_unknown_documents"] == ["legacy-doc"]


@pytest.mark.asyncio
async def test_orchestrator_preserves_parser_warning_when_native_duplicate_wins():
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=ParserWarningChunkSearchService(),
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "parser warning",
        runtime=NativeDuplicateParserWarningRuntimeTool(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 8, "graph_expansion_enabled": False},
    )

    warning_code = "reference_unit_missing_expected_script"
    source = next(
        source for source in result.sources if source["chunk_id"] == "parser-warning-1"
    )
    assert source["metadata"]["retrieval_tool"] == "native"
    assert source["metadata"]["parser_quality_warning_codes"] == [warning_code]
    assert f"parser_quality_warning:{warning_code}" in source["metadata"]["retrieval_reasons"]
    assert any(
        trace.get("stage") == "parser_quality"
        and "native:parser-warning-1" in trace.get("affected_candidate_ids", [])
        for trace in result.chunk_traces
    )


@pytest.mark.asyncio
async def test_orchestrator_preserves_parser_warning_when_native_id_differs():
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=ParserWarningChunkSearchService(),
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "parser warning",
        runtime=NativeMismatchedParserWarningRuntimeTool(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 8, "graph_expansion_enabled": False},
    )

    warning_code = "reference_unit_missing_expected_script"
    source = next(source for source in result.sources if source["chunk_id"] == "lightrag-row-7")
    assert source["metadata"]["retrieval_tool"] == "native"
    assert source["metadata"]["parser_quality_warning_codes"] == [warning_code]
    assert f"parser_quality_warning:{warning_code}" in source["metadata"]["retrieval_reasons"]
    assert any(
        trace.get("stage") == "parser_quality"
        and "native:lightrag-row-7" in trace.get("affected_candidate_ids", [])
        for trace in result.chunk_traces
    )


@pytest.mark.asyncio
async def test_orchestrator_degrades_runtime_query_errors_to_metadata():
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

    assert result.answer == "Sahih al-Bukhari contains 7277 hadith."
    assert result.error is None
    assert any(source["metadata"]["retrieval_tool"] == "metadata" for source in result.sources)
    assert result.timings["runtime_query_ms"] == 4
    assert result.timings["native_degraded"] is True
    assert result.timings["native_error_type"] == "runtime_query_error"
    assert result.timings["native_error"] == "runtime exploded"
    assert result.timings["metadata_ms"] >= 0
    retrieval_trace = next(
        trace for trace in result.chunk_traces if trace["stage"] == "retrieval"
    )
    assert retrieval_trace["native_status"] == "degraded"
    assert answer_service.called is True


@pytest.mark.asyncio
async def test_orchestrator_skips_native_when_metadata_only_requested():
    answer_service = FakeAnswerService()
    chunk_service = FakeChunkSearchService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=chunk_service,
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "show Quran 1:5",
        runtime=NativeSearchShouldNotRun(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 8, "reference_query_mode": "exact"},
    )

    assert result.answer == "Sahih al-Bukhari contains 7277 hadith."
    assert chunk_service.calls == 2
    assert "native_stage_ms" not in result.timings
    retrieval_trace = next(
        trace for trace in result.chunk_traces if trace["stage"] == "retrieval"
    )
    assert retrieval_trace["native_status"] == "skipped"
    assert retrieval_trace["metadata_candidates"] == 1
    assert retrieval_trace["metadata_trace"]["stage"] == "metadata_retrieval"
    assert [item["name"] for item in retrieval_trace["metadata_trace"]["passes"]] == [
        "reference_exact",
        "semantic_metadata",
    ]


@pytest.mark.asyncio
async def test_orchestrator_degrades_native_timeout_to_metadata():
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "how many hadith in bukhari",
        runtime=SlowRuntimeTool(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 8, "native_query_timeout_ms": 1},
    )

    assert result.answer == "Sahih al-Bukhari contains 7277 hadith."
    assert result.error is None
    assert result.timings["native_degraded"] is True
    assert result.timings["native_error_type"] == "native_query_timeout"
    assert "timed out" in result.timings["native_error"]
    assert result.timings["metadata_ms"] >= 0
    assert answer_service.called is True


@pytest.mark.asyncio
async def test_orchestrator_degrades_thrown_native_exception_to_metadata():
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "how many hadith in bukhari",
        runtime=ExplodingNativeRuntimeTool(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 8},
    )

    assert result.answer == "Sahih al-Bukhari contains 7277 hadith."
    assert result.error is None
    assert result.timings["native_degraded"] is True
    assert result.timings["native_error_type"] == "RuntimeError"
    assert result.timings["native_error"] == "native query crashed"
    assert result.timings["metadata_ms"] >= 0
    assert answer_service.called is True


@pytest.mark.asyncio
async def test_orchestrator_degrades_scoped_native_unsupported_for_reference_query():
    answer_service = FakeAnswerService()
    chunk_service = FakeChunkSearchService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=chunk_service,
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "show Book 64 Hadith 486",
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

    assert result.error is None
    assert result.answer == "Sahih al-Bukhari contains 7277 hadith."
    assert result.sources
    assert result.timings["runtime_query_ms"] == 7
    assert result.timings["native_scoped_query"] is True
    assert result.timings["native_stage_ms"] >= 0
    assert result.timings["metadata_ms"] >= 0
    assert result.timings["native_degraded"] is True
    assert result.timings["native_error_type"] == "native_document_scope_unsupported"
    assert chunk_service.calls == 1
    assert answer_service.called is True


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
async def test_orchestrator_drops_graph_candidates_when_hydration_fails():
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=GraphHydrationFailingChunkSearchService(),
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

    assert result.error is None
    assert all(candidate.tool != "graph" for candidate in answer_service.evidence)
    assert all(source["metadata"]["retrieval_tool"] != "graph" for source in result.sources)
    hydration_trace = next(
        trace for trace in result.chunk_traces if trace["stage"] == "graph_hydration"
    )
    assert hydration_trace["status"] == "failed"
    assert result.timings["graph_hydration_degraded"] is True


@pytest.mark.asyncio
async def test_orchestrator_drops_graph_candidates_missing_postgres_chunks():
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=GraphHydrationMissingChunkSearchService(),
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

    assert result.error is None
    assert all(candidate.tool != "graph" for candidate in answer_service.evidence)
    hydration_trace = next(
        trace for trace in result.chunk_traces if trace["stage"] == "graph_hydration"
    )
    assert hydration_trace["missing_candidates"] == 1
    assert hydration_trace["dropped_preview_candidates"] == 1


@pytest.mark.asyncio
async def test_orchestrator_drops_graph_candidates_outside_requested_document_scope():
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=GraphHydrationWrongDocumentChunkSearchService(),
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

    assert result.error is None
    assert all(candidate.tool != "graph" for candidate in answer_service.evidence)
    assert all(source["metadata"]["retrieval_tool"] != "graph" for source in result.sources)
    hydration_trace = next(
        trace for trace in result.chunk_traces if trace["stage"] == "graph_hydration"
    )
    assert hydration_trace["scope_mismatch_candidates"] == 1


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
async def test_orchestrator_degrades_scoped_native_unsupported_after_metadata_search():
    answer_service = FakeAnswerService()
    chunk_service = FakeChunkSearchService()
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

    assert result.answer == "Sahih al-Bukhari contains 7277 hadith."
    assert result.error is None
    assert result.timings["runtime_query_ms"] == 7
    assert result.timings["native_scoped_query"] is True
    assert result.timings["native_stage_ms"] >= 0
    assert result.timings["metadata_ms"] >= 0
    assert result.timings["native_degraded"] is True
    assert result.timings["native_error_type"] == "native_document_scope_unsupported"
    assert result.timings["native_error"] == "native scoped unsupported"
    assert "metadata_error_type" not in result.timings
    assert chunk_service.calls == 1
    assert answer_service.called is True


@pytest.mark.asyncio
async def test_orchestrator_degrades_scoped_native_preflight_before_query():
    answer_service = FakeAnswerService()
    runtime = DegradedPreflightRuntimeTool()
    orchestrator = RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "boom",
        runtime=runtime,
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 8},
    )

    assert runtime.preflight_calls == [["doc-1"]]
    assert runtime.query_called is False
    assert result.answer == "Sahih al-Bukhari contains 7277 hadith."
    assert result.error is None
    assert result.timings["native_degraded"] is True
    assert result.timings["native_error_type"] == "native_document_scope_unsupported"
    assert "full_doc_id filtering" in result.timings["native_error"]
    assert result.timings["native_preflight"]["status"] == "degraded"
    assert result.timings["native_preflight"]["send_dimensions"] is True
    assert result.timings["metadata_ms"] >= 0
    assert answer_service.called is True


@pytest.mark.asyncio
async def test_orchestrator_degrades_hanging_native_preflight_to_metadata():
    answer_service = FakeAnswerService()
    runtime = HangingPreflightRuntimeTool()
    orchestrator = RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "boom",
        runtime=runtime,
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 8, "native_query_timeout_ms": 10},
    )

    assert runtime.preflight_calls == [["doc-1"]]
    assert runtime.query_called is False
    assert result.answer == "Sahih al-Bukhari contains 7277 hadith."
    assert result.error is None
    assert result.timings["native_degraded"] is True
    assert result.timings["native_error_type"] == "native_query_timeout"
    assert result.timings["native_error"] == "Native query timed out after 10 ms."
    assert result.timings["native_stage_ms"] >= 0
    assert result.timings["metadata_ms"] >= 0
    assert answer_service.called is True


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
