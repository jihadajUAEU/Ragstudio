import asyncio
from types import SimpleNamespace

import httpx
import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document
from ragstudio.schemas.chunks import ChunkOut
from ragstudio.services.context_assembly_service import ContextAssemblyService
from ragstudio.services.domain_query_expansion_service import DomainQueryExpansionService
from ragstudio.services.query_hypothesis_service import (
    ProbableAnswer,
    QueryHypothesis,
    QueryHypothesisService,
    QueryTargetTerm,
)
from ragstudio.services.query_hypothesis_verifier import QueryHypothesisVerification
from ragstudio.services.retrieval_evidence import (
    EvidenceCandidate,
    apply_query_aware_ordering,
    fuse_candidates,
    plan_for_query,
)
from ragstudio.services.retrieval_fusion import RetrievalFusion
from ragstudio.services.retrieval_orchestrator import (
    RetrievalOrchestrator,
    _confirmed_hypothesis_answer_allowed,
    _evidence_from_context,
    _graph_seed_candidates,
)
from ragstudio.services.runtime_types import RuntimeQueryResult

QURAN_REFERENCE_CUSTOM_JSON = {
    "reference_schema": {
        "type": "chapter_verse",
        "fields": {"chapter": "chapter_number", "verse": "verse_number"},
        "canonical_ref_template": "{chapter}:{verse}",
    },
    "reference_resolution": {"build_canonical_units": True},
    "domain_structure": {
        "primary_anchor": {
            "type": "chapter_verse",
            "regex": r"(?P<chapter>\d{1,4}):(?P<verse>\d{1,6})",
            "unit": "verse",
            "verified": True,
        },
    },
    "quality_policy": {
        "required_scripts_by_unit_role": {"verse": ["arabic"]},
    },
}


class _ChunkServiceWithSession:
    def __init__(self, session):
        self.session = session


def test_plan_for_count_query_prefers_metadata_and_native():
    plan = plan_for_query("how many hadith in bukhari", document_ids=["doc-1"], limit=8)

    assert plan.intent == "count"
    assert plan.use_native is True
    assert plan.use_metadata is True
    assert plan.use_relationships is True
    assert plan.candidate_limit == 20
    assert plan.document_ids == ["doc-1"]


def test_graph_seed_candidates_accept_hydrated_vector_hits():
    vector = EvidenceCandidate(
        candidate_id="vector:chunk-1",
        text="Hydrated canonical text",
        document_id="doc-1",
        chunk_id="chunk-1",
        source_location={"page": 1},
        metadata={
            "vector_retrieval": {"hydrated_to_canonical": True},
            "quality_action_policy": {"project_graph": True},
        },
        tool="pgvector",
        tool_rank=1,
        base_score=0.9,
        retrieval_pass="vector_db",
    )

    seeds = _graph_seed_candidates([vector], document_ids=["doc-1"], max_seeds=5)

    assert [seed.chunk_id for seed in seeds] == ["chunk-1"]


def test_evidence_from_context_applies_assembled_context_text():
    candidate = EvidenceCandidate(
        candidate_id="metadata:chunk-1",
        text="Guide us to the straight path.",
        document_id="doc-1",
        chunk_id="chunk-1",
        source_location={"page": 1},
        metadata={"evidence_context": {"breadcrumb": "Synthetic Tafseer > 1:5"}},
        tool="metadata",
        tool_rank=1,
        base_score=10,
    )
    assembled_context = ContextAssemblyService(max_context_tokens=200).assemble([candidate])

    evidence = _evidence_from_context([candidate], assembled_context)

    assert evidence[0].text.startswith("[Synthetic Tafseer > 1:5]")
    assert evidence[0].metadata["assembled_context"]["context_text_applied"] is True


def test_retrieval_orchestrator_threads_http_client_provider_to_default_reranker():
    provider = object()
    orchestrator = RetrievalOrchestrator(
        chunk_service=_ChunkServiceWithSession(None),
        http_client_provider=provider,
    )

    assert orchestrator.reranker_service._http_client_provider is provider


@pytest.mark.asyncio
async def test_orchestrator_expands_layout_neighbors_from_seed_candidates(
    database_url, tmp_path
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        session.add(
            Document(
                id="doc-layout-neighbor-orchestrator",
                filename="layout.pdf",
                content_type="application/pdf",
                sha256="layout-orchestrator-sha",
                artifact_path=str(tmp_path / "layout.pdf"),
            )
        )
        session.add_all(
            [
                Chunk(
                    id="seed-layout-orchestrator",
                    document_id="doc-layout-neighbor-orchestrator",
                    text="Figure caption.",
                    source_location={"page": 2, "reference": "fig:2"},
                    metadata_json={
                        "layout": {"role": "caption"},
                        "layout_group_id": "figure-2",
                        "reading_order": 0,
                    },
                ),
                Chunk(
                    id="neighbor-layout-orchestrator",
                    document_id="doc-layout-neighbor-orchestrator",
                    text="Figure body details.",
                    source_location={"page": 2, "reference": "fig:2"},
                    metadata_json={
                        "layout": {"role": "body"},
                        "layout_group_id": "figure-2",
                        "reading_order": 1,
                    },
                ),
            ]
        )
        await session.commit()

        orchestrator = RetrievalOrchestrator(
            chunk_service=_ChunkServiceWithSession(session)
        )
        candidates, traces = await orchestrator._safe_layout_neighbors(
            [
                EvidenceCandidate(
                    candidate_id="pgvector:seed-layout-orchestrator",
                    text="Figure caption.",
                    document_id="doc-layout-neighbor-orchestrator",
                    chunk_id="seed-layout-orchestrator",
                    source_location={"page": 2, "reference": "fig:2"},
                    metadata={
                        "layout_group_id": "figure-2",
                        "reading_order": 0,
                    },
                    tool="pgvector",
                    tool_rank=1,
                    base_score=10.0,
                    final_score=10.0,
                )
            ],
            document_ids=["doc-layout-neighbor-orchestrator"],
            limit=5,
            timings={},
        )

    await engine.dispose()

    assert [candidate.chunk_id for candidate in candidates] == [
        "neighbor-layout-orchestrator"
    ]
    assert traces[0]["stage"] == "layout_neighbor_expansion"
    assert traces[0]["status"] == "ran"
    assert traces[0]["reason"] == (
        "same_page_reference_layout_group_or_reading_order_neighbors"
    )
    assert traces[0]["candidate_count"] == 1
    assert traces[0]["candidate_ids"] == ["layout-neighbor:neighbor-layout-orchestrator"]
    assert traces[0]["canonical_chunk_ids"] == ["neighbor-layout-orchestrator"]
    assert traces[0]["document_ids"] == ["doc-layout-neighbor-orchestrator"]
    assert traces[0]["latency_ms"] >= 0
    assert traces[0]["timed_out"] is False
    assert traces[0]["partial"] is False
    assert traces[0]["layout_group_ids"] == ["figure-2"]
    assert traces[0]["reading_order_neighbors"] is True
    assert traces[0]["layout_summaries"]["neighbor-layout-orchestrator"] == "text; page=2"


@pytest.mark.asyncio
async def test_orchestrator_expands_context_window_from_seed_candidates(
    database_url, tmp_path
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        session.add(
            Document(
                id="doc-context-window-orchestrator",
                filename="context-window.pdf",
                content_type="application/pdf",
                sha256="context-window-orchestrator-sha",
                artifact_path=str(tmp_path / "context-window.pdf"),
            )
        )
        session.add_all(
            [
                Chunk(
                    id="parent-context-window-orchestrator",
                    document_id="doc-context-window-orchestrator",
                    text="Parent canonical section.",
                    source_location={"page": 1},
                    metadata_json={},
                ),
                Chunk(
                    id="prev-context-window-orchestrator",
                    document_id="doc-context-window-orchestrator",
                    text="Previous canonical chunk.",
                    source_location={"page": 1},
                    metadata_json={"reading_order": 1},
                ),
                Chunk(
                    id="seed-context-window-orchestrator",
                    document_id="doc-context-window-orchestrator",
                    text="Seed canonical chunk.",
                    source_location={"page": 1},
                    metadata_json={
                        "parent_chunk_id": "parent-context-window-orchestrator",
                        "reading_order": 2,
                    },
                ),
                Chunk(
                    id="next-context-window-orchestrator",
                    document_id="doc-context-window-orchestrator",
                    text="Next canonical chunk.",
                    source_location={"page": 1},
                    metadata_json={
                        "previous_chunk_id": "seed-context-window-orchestrator",
                        "reading_order": 3,
                    },
                ),
                Chunk(
                    id="sibling-context-window-orchestrator",
                    document_id="doc-context-window-orchestrator",
                    text="Sibling canonical chunk.",
                    source_location={"page": 1},
                    metadata_json={
                        "parent_chunk_id": "parent-context-window-orchestrator",
                    },
                ),
            ]
        )
        await session.commit()

        orchestrator = RetrievalOrchestrator(
            chunk_service=_ChunkServiceWithSession(session)
        )
        candidates, traces = await orchestrator._safe_context_neighbors(
            [
                EvidenceCandidate(
                    candidate_id="metadata:seed-context-window-orchestrator",
                    text="Seed canonical chunk.",
                    document_id="doc-context-window-orchestrator",
                    chunk_id="seed-context-window-orchestrator",
                    source_location={"page": 1},
                    metadata={
                        "parent_chunk_id": "parent-context-window-orchestrator",
                        "previous_chunk_id": "prev-context-window-orchestrator",
                        "next_chunk_id": "next-context-window-orchestrator",
                        "reading_order": 2,
                    },
                    tool="metadata",
                    tool_rank=1,
                    base_score=10.0,
                )
            ],
            document_ids=["doc-context-window-orchestrator"],
            limit=4,
            timings={},
        )

    await engine.dispose()

    assert {candidate.chunk_id for candidate in candidates} == {
        "parent-context-window-orchestrator",
        "prev-context-window-orchestrator",
        "next-context-window-orchestrator",
        "sibling-context-window-orchestrator",
    }
    assert traces[0]["stage"] == "retrieval_lane_result"
    assert traces[0]["lane"] == "context_window"
    assert traces[0]["status"] == "ran"
    assert traces[0]["reason"] == "adjacent_parent_sibling_context_window"
    assert traces[0]["candidate_count"] == 4
    assert traces[0]["relationship_reasons"][
        "parent-context-window-orchestrator"
    ] == "parent_context"
    assert traces[0]["relationship_reasons"]["prev-context-window-orchestrator"] == (
        "reading_order_adjacent_and_linked_context"
    )
    assert traces[0]["relationship_reasons"]["next-context-window-orchestrator"] == (
        "reading_order_adjacent_and_linked_context"
    )
    assert traces[0]["relationship_reasons"][
        "sibling-context-window-orchestrator"
    ] == "sibling_context"


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
        reference_contracts=[
            {
                "reference_contract": {
                    "verified": True,
                    "canonical_units": True,
                    "canonical_ref_template": "{chapter}:{verse}",
                    "required_groups": ["chapter", "verse"],
                    "patterns": [r"(?P<chapter>\d{1,4}):(?P<verse>\d{1,6})"],
                }
            }
        ],
    )

    assert plan.intent == "reference"
    assert plan.retrieval_strategy == "graph_context_hybrid"
    assert plan.graph_context_required is True


def test_confirmed_hypothesis_answer_requires_generic_reference_shape():
    hypothesis = QueryHypothesis(
        original_query="find mercy",
        valid=True,
        intent="find_word_occurrence",
        target_terms=[
            QueryTargetTerm(surface="mercy", script="latin", term_type="exact_text")
        ],
        answer_shape="surah_and_verse",
        probable_answer=ProbableAnswer(reference="19:13"),
    )
    verification = QueryHypothesisVerification(
        status="confirmed",
        reason="target_term_found_in_evidence",
        target_terms=["mercy"],
        matched_terms=["mercy"],
        reference="19:13",
    )

    assert (
        _confirmed_hypothesis_answer_allowed(
            hypothesis,
            verification,
            domain_expansion=SimpleNamespace(domain_family="reference_heavy"),
        )
        is False
    )


def test_plan_for_arabic_token_carries_retrieval_passes():
    plan = plan_for_query(
        "حنانا",
        document_ids=["doc-quran"],
        limit=5,
        declared_scripts={"arabic"},
    )

    assert plan.intent == "reference"
    assert plan.understanding is not None
    assert plan.understanding.intent == "arabic_exact_token"
    assert [item.name for item in plan.understanding.retrieval_passes] == [
        "arabic_exact_token",
        "semantic_metadata",
        "vector_db",
        "native_vector",
    ]


def test_plan_for_query_carries_domain_expansion_reference_intent():
    expansion = DomainQueryExpansionService().expand(
        "hanan",
        domain_metadata=[
            {
                "domain": "quran_tafseer",
                    "document_type": "commentary",
                    "language": "mixed",
                    "tags": ["quran", "arabic"],
                    "custom_json": QURAN_REFERENCE_CUSTOM_JSON,
                }
            ],
        )

    plan = plan_for_query(
        "hanan",
        document_ids=["doc-quran"],
        limit=5,
        domain_expansion=expansion,
    )

    assert plan.intent == "reference"
    assert plan.understanding is not None
    assert plan.understanding.intent == "lexical_expanded_token"
    assert plan.understanding.answer_type == "reference"
    assert plan.understanding.expanded_terms == ["حنانا", "وحنانا"]
    assert plan.understanding.retrieval_passes[0].name == "lexical_expanded_token"
    assert plan.retrieval_strategy == "reference_first_hybrid"


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


def test_fusion_boosts_lexical_expanded_metadata_above_semantic_candidate():
    expansion = DomainQueryExpansionService().expand(
        "hanan",
        domain_metadata=[
            {
                "domain": "quran_tafseer",
                "document_type": "commentary",
                "language": "mixed",
                "tags": ["quran", "arabic"],
                "custom_json": QURAN_REFERENCE_CUSTOM_JSON,
            }
        ],
    )
    plan = plan_for_query(
        "hanan",
        document_ids=["doc-quran"],
        limit=3,
        domain_expansion=expansion,
    )
    semantic_native = EvidenceCandidate(
        candidate_id="native:semantic-hanan",
        text="A semantically related discussion about mercy and compassion.",
        document_id="doc-quran",
        chunk_id="chunk-semantic",
        source_location={},
        metadata={
            "domain_metadata": {
                "domain": "quran_tafseer",
                "custom_json": QURAN_REFERENCE_CUSTOM_JSON,
            }
        },
        tool="native",
        tool_rank=1,
        base_score=42.0,
        retrieval_pass="native_vector",
    )
    lexical_metadata = EvidenceCandidate(
        candidate_id="metadata:hanan-19-13",
        text="[19:13] وَحَنَانًا مِّن لَّدُنَّا",
        document_id="doc-quran",
        chunk_id="chunk-19-13",
        source_location={"reference": "19:13"},
        metadata={
            "domain_metadata": {
                "domain": "quran_tafseer",
                "custom_json": QURAN_REFERENCE_CUSTOM_JSON,
            }
        },
        tool="metadata",
        tool_rank=2,
        base_score=18.0,
        retrieval_pass="lexical_expanded_token",
        match_features={"expanded_term": "حنانا", "match_type": "transliteration"},
        canonical_reference="19:13",
    )

    fused = fuse_candidates(plan, [semantic_native, lexical_metadata])

    assert fused[0].chunk_id == "chunk-19-13"
    assert "lexical_expanded_exact" in fused[0].reasons
    assert fused[0].final_score > fused[1].final_score


def test_fusion_keeps_answer_bearing_metadata_above_graph_neighbors():
    plan = plan_for_query(
        "Which is the hadith saying about offering sacrifice for eid from hadith_bukhari",
        document_ids=["doc-bukhari"],
        limit=8,
    )
    exact_hadith = EvidenceCandidate(
        candidate_id="metadata:book-13-hadith-25",
        text=(
            "Book 13, Hadith 25. The day of Id-ul-Adha: first offer the prayer, "
            "then return and slaughter the sacrifice."
        ),
        document_id="doc-bukhari",
        chunk_id="book-13-hadith-25",
        source_location={"reference": "Book 13, Hadith 25"},
        metadata={
            "score_breakdown": {"term_coverage": 8.3},
            "domain_metadata": {"domain": "hadith", "collection": "sahih_bukhari"},
        },
        tool="metadata",
        tool_rank=3,
        base_score=10.4,
        retrieval_pass="semantic_metadata",
    )
    neighbor = EvidenceCandidate(
        candidate_id="graph:book-13-hadith-24",
        text="Book 13, Hadith 24. A nearby Eid prayer narration.",
        document_id="doc-bukhari",
        chunk_id="book-13-hadith-24",
        source_location={"reference": "Book 13, Hadith 24"},
        metadata={
            "graph_relationship": {"type": "REFERENCES", "path": "reference_hop"},
            "domain_metadata": {"domain": "hadith", "collection": "sahih_bukhari"},
        },
        tool="graph",
        tool_rank=1,
        base_score=17.0,
        reasons=["graph_neighbor"],
    )

    fused = fuse_candidates(plan, [neighbor, exact_hadith])

    assert fused[0].chunk_id == "book-13-hadith-25"
    assert "answer_terms_matched" in fused[0].reasons


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
                "custom_json": QURAN_REFERENCE_CUSTOM_JSON,
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
    assert "reference_heavy_exact" in fused[0].reasons


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

    assert "reference_heavy_exact" not in fused[0].reasons


def test_multi_document_reference_query_keeps_exact_hits_from_each_tafseer_document():
    plan = plan_for_query("Explain 1:5", document_ids=["doc-a", "doc-b"], limit=2)
    doc_a = EvidenceCandidate(
        candidate_id="metadata:doc-a-1-5",
        text="Doc A verse 1:5 explanation.",
        document_id="doc-a",
        chunk_id="chunk-doc-a-1-5",
        source_location={"reference": "1:5"},
        metadata={"domain_metadata": {"domain": "quran_tafseer"}},
        tool="metadata",
        tool_rank=1,
        base_score=30.0,
        retrieval_pass="reference_exact",
    )
    doc_b = EvidenceCandidate(
        candidate_id="metadata:doc-b-1-5",
        text="Doc B verse 1:5 explanation.",
        document_id="doc-b",
        chunk_id="chunk-doc-b-1-5",
        source_location={"reference": "1:5"},
        metadata={"domain_metadata": {"domain": "quran_tafseer"}},
        tool="metadata",
        tool_rank=2,
        base_score=24.0,
        retrieval_pass="reference_exact",
    )
    doc_a_extra = EvidenceCandidate(
        candidate_id="metadata:doc-a-extra",
        text="Another strong Doc A passage.",
        document_id="doc-a",
        chunk_id="chunk-doc-a-extra",
        source_location={},
        metadata={"domain_metadata": {"domain": "quran_tafseer"}},
        tool="metadata",
        tool_rank=3,
        base_score=25.0,
    )

    fused = fuse_candidates(plan, [doc_a, doc_a_extra, doc_b])

    assert [candidate.document_id for candidate in fused[:2]] == ["doc-a", "doc-b"]


def test_multi_document_comparison_query_prioritizes_multiple_documents():
    plan = plan_for_query(
        "Compare guidance in these selected documents",
        document_ids=["doc-a", "doc-b"],
        limit=4,
    )
    doc_a = EvidenceCandidate(
        candidate_id="native:doc-a",
        text="Doc A discusses guidance as a straight path.",
        document_id="doc-a",
        chunk_id="chunk-doc-a",
        source_location={},
        metadata={"domain_metadata": {"domain": "quran_tafseer"}},
        tool="native",
        tool_rank=1,
        base_score=40.0,
    )
    doc_b = EvidenceCandidate(
        candidate_id="native:doc-b",
        text="Doc B discusses guidance as divine direction.",
        document_id="doc-b",
        chunk_id="chunk-doc-b",
        source_location={},
        metadata={"domain_metadata": {"domain": "quran_tafseer"}},
        tool="native",
        tool_rank=2,
        base_score=20.0,
    )
    doc_a_extra = EvidenceCandidate(
        candidate_id="native:doc-a-extra",
        text="Doc A extra evidence.",
        document_id="doc-a",
        chunk_id="chunk-doc-a-extra",
        source_location={},
        metadata={"domain_metadata": {"domain": "quran_tafseer"}},
        tool="native",
        tool_rank=3,
        base_score=35.0,
    )

    fused = fuse_candidates(plan, [doc_a, doc_a_extra, doc_b])

    assert {candidate.document_id for candidate in fused[:2]} == {"doc-a", "doc-b"}


def test_multi_document_ordering_survives_retrieval_fusion_rescoring():
    plan = plan_for_query(
        "Compare guidance in these selected documents",
        document_ids=["doc-a", "doc-b"],
        limit=4,
    )
    doc_a = EvidenceCandidate(
        candidate_id="native:doc-a",
        text="Doc A discusses guidance as a straight path.",
        document_id="doc-a",
        chunk_id="chunk-doc-a",
        source_location={},
        metadata={},
        tool="native",
        tool_rank=1,
        base_score=40.0,
        final_score=40.0,
    )
    doc_a_extra = EvidenceCandidate(
        candidate_id="native:doc-a-extra",
        text="Doc A extra evidence.",
        document_id="doc-a",
        chunk_id="chunk-doc-a-extra",
        source_location={},
        metadata={},
        tool="native",
        tool_rank=2,
        base_score=35.0,
        final_score=35.0,
    )
    doc_b = EvidenceCandidate(
        candidate_id="native:doc-b",
        text="Doc B discusses guidance as divine direction.",
        document_id="doc-b",
        chunk_id="chunk-doc-b",
        source_location={},
        metadata={},
        tool="native",
        tool_rank=3,
        base_score=20.0,
        final_score=20.0,
    )

    fused = RetrievalFusion().fuse([[doc_a, doc_a_extra, doc_b]], limit=4)
    reordered = apply_query_aware_ordering(plan, fused)

    assert [candidate.document_id for candidate in fused[:2]] == ["doc-a", "doc-a"]
    assert {candidate.document_id for candidate in reordered[:2]} == {"doc-a", "doc-b"}


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
    assert "lexical_expanded_exact" not in result.reasons


def test_fusion_retains_lexical_expanded_boost_after_vector_duplicate_wins():
    plan = plan_for_query("qiyam al layl", document_ids=["doc-lexical"], limit=3)
    semantic = EvidenceCandidate(
        candidate_id="pgvector:chunk-night-prayer",
        text="The chapter discusses night prayer and standing in worship.",
        document_id="doc-lexical",
        chunk_id="chunk-night-prayer",
        source_location={"page": 7},
        metadata={},
        tool="pgvector",
        tool_rank=1,
        base_score=40.0,
        retrieval_pass="vector_db",
    )
    lexical_expanded = EvidenceCandidate(
        candidate_id="lexical-expanded:chunk-night-prayer",
        text="The chapter discusses night prayer and standing in worship.",
        document_id="doc-lexical",
        chunk_id="chunk-night-prayer",
        source_location={"page": 7},
        metadata={"retrieval_passes": ["lexical_expanded_token"]},
        tool="metadata",
        tool_rank=2,
        base_score=6.0,
        retrieval_pass="lexical_expanded_token",
        match_features={
            "lexical_expanded": True,
            "expanded_token": "qiyam",
            "matched_token": "standing",
        },
    )
    ordinary_semantic = EvidenceCandidate(
        candidate_id="pgvector:ordinary",
        text="A semantic-only result about general worship.",
        document_id="doc-lexical",
        chunk_id="chunk-ordinary",
        source_location={"page": 9},
        metadata={},
        tool="pgvector",
        tool_rank=3,
        base_score=20.0,
        retrieval_pass="vector_db",
    )

    fused = fuse_candidates(plan, [semantic, lexical_expanded, ordinary_semantic])

    result = next(candidate for candidate in fused if candidate.chunk_id == "chunk-night-prayer")
    assert result.tool == "pgvector"
    assert result.retrieval_pass == "vector_db"
    assert result.metadata["retrieval_passes"] == ["vector_db", "lexical_expanded_token"]
    assert result.match_features["lexical_expanded"] is True
    assert result.reasons.count("lexical_expanded_exact") == 1
    assert result.boost_score == 28.0
    assert result.final_score == 68.0

    semantic_only = next(candidate for candidate in fused if candidate.chunk_id == "chunk-ordinary")
    assert "lexical_expanded_exact" not in semantic_only.reasons


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


class QuranContractFakeChunkSearchService(FakeChunkSearchService):
    async def domain_metadata_for_documents(self, document_ids):
        return [
            {
                "domain": "quran_tafseer",
                "document_type": "commentary",
                "language": "mixed",
                "script": "arabic",
                "tags": ["quran", "arabic"],
                "custom_json": QURAN_REFERENCE_CUSTOM_JSON,
            }
        ]


class QuranDomainMetadataChunkSearchService:
    def __init__(self):
        self.calls = 0
        self.search_queries = []
        self.domain_metadata_document_calls = []

    async def domain_metadata_for_documents(self, document_ids):
        self.domain_metadata_document_calls.append(list(document_ids))
        return [
            {
                "domain": "quran_tafseer",
                "document_type": "tafseer",
                "content_role": "quran",
                "language": "mixed",
                "tags": ["quran", "tafseer", "arabic"],
                "custom_json": QURAN_REFERENCE_CUSTOM_JSON,
            }
        ]

    async def search(self, search_in):
        self.calls += 1
        self.search_queries.append(search_in.query)
        return type(
            "SearchResult",
            (),
            {
                "items": [
                    ChunkOut(
                        id=f"quran-{self.calls}",
                        document_id="doc-quran",
                        text=f"[19:13] وَحَنَانًا مِّن لَّدُنَّا matched {search_in.query}",
                        source_location={"page": 312, "reference": "19:13"},
                        metadata={
                            "domain_metadata": {
                                "domain": "quran_tafseer",
                                "custom_json": QURAN_REFERENCE_CUSTOM_JSON,
                            },
                            "reference_metadata": {"references": ["19:13"]},
                            "score": 10.0,
                        },
                    )
                ],
                "total": 1,
            },
        )()


class EmptyMetadataChunkSearchService:
    async def domain_metadata_for_documents(self, document_ids):
        return []

    async def search(self, search_in):
        return type("SearchResult", (), {"items": [], "total": 0})()

    async def chunks_by_id(self, chunk_ids):
        return []


class PolicyBlockedDomainChunkSearchService(FakeChunkSearchService):
    async def domain_metadata_for_documents(self, document_ids):
        return [
            {
                "domain": "medical",
                "layout_types": ["figure"],
                "quality_action_policy": {
                    "index_vector": False,
                    "project_graph": False,
                    "reasons": ["quality_policy_blocks_secondary_lanes"],
                },
                "materialization_policy": {
                    "action": "persist_only",
                    "allow_raganything_runtime_lane": False,
                    "reasons": ["runtime_bridge_missing"],
                },
            }
        ]


class HadithReferenceChunkSearchService:
    def __init__(self):
        self.search_queries = []
        self.domain_metadata_document_calls = []

    async def domain_metadata_for_documents(self, document_ids):
        self.domain_metadata_document_calls.append(list(document_ids))
        return [
            {
                "domain": "hadith",
                "document_type": "collection",
                "content_role": "primary_source",
                "tags": ["hadith", "islamic_text", "religious_text"],
            }
        ]

    async def search(self, search_in):
        self.search_queries.append(search_in.query)
        items = []
        if search_in.query == "book:34:hadith:288":
            items.append(
                ChunkOut(
                    id="book-34-hadith-288",
                    document_id="doc-hadith",
                    text="Book 34, Hadith 288. A trade-related report.",
                    source_location={"reference": "Book 34, Hadith 288"},
                    metadata={
                        "domain_metadata": {"domain": "hadith"},
                        "reference_metadata": {"references": ["book:34:hadith:288"]},
                        "score": 100.0,
                        "score_breakdown": {"reference_exact": 100.0},
                    },
                )
            )
        elif search_in.query == "book:13:hadith:25" or search_in.query.startswith("Which"):
            items.append(
                ChunkOut(
                    id="book-13-hadith-25",
                    document_id="doc-hadith",
                    text=(
                        "Book 13, Hadith 25. On Eid, prayer comes first, then "
                        "the sacrifice."
                    ),
                    source_location={"reference": "Book 13, Hadith 25"},
                    metadata={
                        "domain_metadata": {"domain": "hadith"},
                        "reference_metadata": {"references": ["book:13:hadith:25"]},
                        "score": 10.0,
                        "score_breakdown": {"term_coverage": 8.5},
                    },
                )
            )
        return type("SearchResult", (), {"items": items, "total": len(items)})()


class ArticleClauseReferenceChunkSearchService:
    def __init__(self):
        self.search_queries = []
        self.domain_metadata_document_calls = []

    async def domain_metadata_for_documents(self, document_ids):
        self.domain_metadata_document_calls.append(list(document_ids))
        return [
            {
                "domain": "policy_manual",
                "document_type": "policy",
                "custom_json": {
                    "reference_schema": {
                        "type": "article_clause",
                        "canonical_ref_template": "article:{article}:clause:{clause}",
                        "fields": {
                            "article": "article_number",
                            "clause": "clause_number",
                        },
                    },
                    "reference_resolution": {
                        "build_canonical_units": True,
                    },
                    "domain_structure": {
                        "primary_anchor": {
                            "type": "article_clause",
                            "regex": r"Article\s+(?P<article>\d+)\.(?P<clause>\d+)",
                            "unit": "clause",
                            "verified": True,
                        }
                    },
                },
            }
        ]

    async def search(self, search_in):
        self.search_queries.append(search_in.query)
        items = []
        if search_in.query == "article:12:clause:7":
            items.append(
                ChunkOut(
                    id="article-12-clause-7",
                    document_id="doc-policy",
                    text="Article 12.7 requires annual evidence review.",
                    source_location={"reference": "article:12:clause:7"},
                    metadata={
                        "domain_metadata": {"domain": "policy_manual"},
                        "reference_metadata": {
                            "references": ["article:12:clause:7"],
                        },
                        "score": 20.0,
                        "score_breakdown": {"reference_exact": 100.0},
                    },
                )
            )
        return type("SearchResult", (), {"items": items, "total": len(items)})()


class HananHypothesisService:
    async def hypothesize(self, query, *, profile, domain_metadata, timeout_ms):
        return QueryHypothesis(
            original_query=query,
            intent="find_word_occurrence",
            target_terms=[
                QueryTargetTerm(
                    surface="hanan",
                    script="latin",
                    language_hint="arabic",
                    term_type="transliteration",
                )
            ],
            domain_hint="quran",
            answer_shape="reference",
            probable_answer=ProbableAnswer(
                reference="19:13",
                display_label="Surah Maryam, 19:13",
                matched_term="حنانا",
            ),
            confidence=0.86,
            valid=True,
            source="llm",
        )


class SemanticHypothesisService:
    async def hypothesize(self, query, *, profile, domain_metadata, timeout_ms):
        return QueryHypothesis(
            original_query=query,
            intent="semantic_question",
            target_terms=[QueryTargetTerm(surface="hanan", script="latin")],
            domain_hint="quran",
            answer_shape="explanation",
            confidence=0.8,
            valid=True,
            source="llm",
        )


class CorrectHadithReferenceHypothesisService:
    async def hypothesize(self, query, *, profile, domain_metadata, timeout_ms):
        return QueryHypothesis(
            original_query=query,
            intent="reference_lookup",
            target_terms=[
                QueryTargetTerm(surface="offering", script="latin"),
                QueryTargetTerm(surface="sacrifice", script="latin"),
                QueryTargetTerm(surface="eid", script="latin"),
            ],
            possible_references=["book:13:hadith:25"],
            domain_hint="hadith",
            answer_shape="reference",
            confidence=0.86,
            valid=True,
            source="llm",
        )


class ArticleClauseReferenceHypothesisService:
    async def hypothesize(self, query, *, profile, domain_metadata, timeout_ms):
        return QueryHypothesisService.parse_hypothesis(
            {
                "intent": "reference_lookup",
                "possible_references": ["Article 12.7"],
                "domain_hint": "reference",
                "answer_shape": "reference",
            },
            original_query=query,
            reference_contracts=[
                {
                    "reference_contract": {
                        "schema_type": "article_clause",
                        "canonical_ref_template": "article:{article}:clause:{clause}",
                        "required_groups": ["article", "clause"],
                        "verified": True,
                        "anchors": [
                            {
                                "kind": "primary_anchor",
                                "regex": (
                                    r"Article\s+(?P<article>\d+)\.(?P<clause>\d+)"
                                ),
                                "verified": True,
                            }
                        ],
                    }
                }
            ],
        )


class WrongHadithReferenceHypothesisService:
    async def hypothesize(self, query, *, profile, domain_metadata, timeout_ms):
        return QueryHypothesis(
            original_query=query,
            intent="reference_lookup",
            target_terms=[
                QueryTargetTerm(surface="offering", script="latin"),
                QueryTargetTerm(surface="sacrifice", script="latin"),
                QueryTargetTerm(surface="eid", script="latin"),
            ],
            possible_references=["book:34:hadith:288"],
            domain_hint="hadith",
            answer_shape="reference",
            confidence=0.66,
            valid=True,
            source="llm",
        )


class TimeoutHypothesisService:
    async def hypothesize(self, query, *, profile, domain_metadata, timeout_ms):
        raise TimeoutError("planner timed out")


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


class SlowNativeRuntimeTool(FakeRuntimeTool):
    def __init__(self):
        self.query_called = False

    async def query(self, query, *, document_ids, query_config):
        self.query_called = True
        await asyncio.sleep(0.05)
        return RuntimeQueryResult(
            answer="slow native answer",
            sources=[],
            timings={"runtime_query_ms": 50},
        )


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


class SlowChunkSearchService(FakeChunkSearchService):
    async def search(self, search_in):
        await asyncio.sleep(0.05)
        return await super().search(search_in)


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


class TimeoutAnswerService:
    def __init__(self):
        self.called = False

    async def answer(self, query, evidence, profile):
        self.called = True
        raise httpx.ReadTimeout("provider timed out")


class FakeRerankerService:
    async def rerank(self, query, chunks, profile):
        return chunks, [{"provider": "disabled", "status": "disabled"}]


class RerankerShouldNotRun:
    async def rerank(self, query, chunks, profile):
        raise AssertionError("reranker should not run")


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
        query_config={"limit": 8, "query_hypothesis_required": False},
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
    assert any(trace.get("stage") == "candidate_diversity" for trace in result.chunk_traces)
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
    assert graph_evidence.text.startswith("[collection:bukhari | page=9]\n")
    assert graph_evidence.text.endswith(
        "Full hydrated graph chunk confirms 7277 hadith in Sahih al-Bukhari."
    )
    assert graph_evidence.metadata["assembled_context"] == {
        "breadcrumb": "collection:bukhari",
        "layout_summary": "page=9",
        "context_text_applied": True,
    }
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
async def test_orchestrator_returns_evidence_first_answer_when_provider_times_out():
    answer_service = TimeoutAnswerService()
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
        query_config={"limit": 8, "response_mode": "fast", "answer_budget_ms": 1000},
    )

    assert answer_service.called is True
    assert result.error is None
    assert result.answer.startswith("Evidence-first result")
    assert result.token_metadata["llm_answer_status"] == "timeout"
    assert result.token_metadata["llm_error_type"] == "ReadTimeout"
    assert result.timings["answer_fallback"] is True


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
        query_config={"limit": 8, "query_hypothesis_required": False},
    )

    stages = [trace.get("stage") for trace in result.chunk_traces if isinstance(trace, dict)]
    assert "primary_retrieval" in stages
    assert "seed_fusion" in stages
    assert "graph_expansion" in stages
    assert "final_fusion" in stages
    assert "retrieval_fusion" not in stages
    assert result.error is None
    assert answer_service.called is True


@pytest.mark.asyncio
async def test_orchestrator_emits_retrieval_route_plan_trace():
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=QuranDomainMetadataChunkSearchService(),
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "hanan",
        runtime=FakeRuntimeTool(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-quran"],
        variant_id="variant-1",
        query_config={"limit": 5},
    )

    route_trace = next(
        trace for trace in result.chunk_traces if trace.get("stage") == "retrieval_route_plan"
    )
    assert route_trace["source_of_truth"] == "postgres_canonical_evidence"
    assert route_trace["lanes"][0]["lane"] == "postgres_canonical"
    assert route_trace["planned_lanes"][0] == "postgres_canonical"
    assert route_trace["domain_profile_id"] == "reference_heavy"
    assert route_trace["document_ids"] == ["doc-quran"]
    assert route_trace["intent"] == "reference"
    assert route_trace["direct_evidence_required"] is True
    assert result.error is None


@pytest.mark.asyncio
async def test_orchestrator_route_plan_applies_document_quality_and_materialization_policy():
    class GraphShouldNotRun:
        async def expand(self, query, *, seeds, profile, document_ids, limit):
            raise AssertionError("graph lane should not run")

    orchestrator = RetrievalOrchestrator(
        chunk_service=PolicyBlockedDomainChunkSearchService(),
        answer_service=FakeAnswerService(),
        reranker_service=FakeRerankerService(),
        graph_expansion_service=GraphShouldNotRun(),
    )

    result = await orchestrator.query(
        "how many hadith in bukhari",
        runtime=NativeSearchShouldNotRun(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={"limit": 8},
    )

    route_trace = next(
        trace for trace in result.chunk_traces if trace.get("stage") == "retrieval_route_plan"
    )
    lane_by_name = {lane["lane"]: lane for lane in route_trace["lanes"]}

    assert lane_by_name["raganything_runtime"]["status"] == "skipped"
    assert lane_by_name["graph"]["status"] == "skipped"
    assert lane_by_name["vector"]["status"] == "skipped"
    assert result.error is None
    assert result.timings.get("native_stage_ms") is None
    assert any(
        trace.get("stage") == "retrieval_lane_result"
        and trace.get("lane") == "vector"
        and trace.get("status") == "skipped"
        for trace in result.chunk_traces
    )


@pytest.mark.asyncio
async def test_orchestrator_runs_quality_gated_vector_lane_when_baseline_passes():
    class VectorRepo:
        async def candidate_rows(self, *, query, document_ids, limit):
            return [
                {
                    "candidate_id": "vector-row:chunk-v1",
                    "chunk_id": "chunk-v1",
                    "document_id": document_ids[0],
                    "text": "vector alpha evidence",
                    "source_location": {"page": 1},
                    "metadata": {"quality_action_policy": {"index_vector": True}},
                    "score": 0.8,
                    "rank": 1,
                }
            ]

    orchestrator = RetrievalOrchestrator(
        chunk_service=EmptyMetadataChunkSearchService(),
        answer_service=FakeAnswerService(),
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
        vector_candidate_repository=VectorRepo(),
    )

    result = await orchestrator.query(
        "alpha",
        runtime=NativeSearchShouldNotRun(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-vector"],
        variant_id="variant-1",
        query_config={
            "limit": 3,
            "vector_baseline_gate": {"passed": True},
            "runtime_readiness": {"state": "disabled", "reason": "test_vector_lane_only"},
            "graph_expansion_enabled": False,
        },
    )

    assert result.error is None
    assert any(source["chunk_id"] == "chunk-v1" for source in result.sources)
    assert any(
        trace.get("stage") == "vector_retrieval" and trace.get("status") == "ran"
        for trace in result.chunk_traces
    )


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
        chunk_service=QuranContractFakeChunkSearchService(),
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
        query_config={"limit": 8, "query_hypothesis_required": False},
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
    chunk_service = QuranContractFakeChunkSearchService()
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
        query_config={
            "limit": 8,
            "reference_query_mode": "exact",
            "query_hypothesis_required": False,
        },
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
async def test_orchestrator_uses_selected_document_domain_metadata_for_expansion():
    answer_service = FakeAnswerService()
    chunk_service = QuranDomainMetadataChunkSearchService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=chunk_service,
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "hanan",
        runtime=NativeSearchShouldNotRun(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-quran"],
        variant_id="variant-1",
        query_config={
            "limit": 8,
            "retrieval_mode": "metadata",
            "graph_expansion_enabled": False,
        },
    )

    assert result.error is None
    assert chunk_service.domain_metadata_document_calls == [["doc-quran"]]
    assert "native_stage_ms" not in result.timings

    retrieval_trace = next(
        trace for trace in result.chunk_traces if trace["stage"] == "retrieval"
    )
    assert retrieval_trace["native_status"] == "skipped"
    lexical_passes = [
        item
        for item in retrieval_trace["metadata_trace"]["passes"]
        if item["name"] == "lexical_expanded_token"
    ]
    assert [item["query"] for item in lexical_passes] == ["حنانا"]

    expansion_trace = next(
        trace
        for trace in result.chunk_traces
        if trace.get("stage") == "domain_query_expansion"
    )
    assert expansion_trace["expanded_terms"] == ["حنانا", "وحنانا"]

    planner_trace = next(
        trace for trace in result.chunk_traces if trace["stage"] == "planner"
    )
    assert planner_trace["understanding_intent"] == "lexical_expanded_token"
    assert planner_trace["expanded_terms"] == ["حنانا", "وحنانا"]


@pytest.mark.asyncio
async def test_orchestrator_uses_hypothesis_terms_and_confirmed_answer_for_word_query():
    chunk_service = QuranDomainMetadataChunkSearchService()
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=chunk_service,
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
        query_hypothesis_service=HananHypothesisService(),
    )

    result = await orchestrator.query(
        "in which surah the word hanan is mentioned",
        runtime=NativeSearchShouldNotRun(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-quran"],
        variant_id="variant-1",
        query_config={
            "limit": 8,
            "retrieval_mode": "metadata",
            "graph_expansion_enabled": False,
        },
    )

    assert result.error is None
    assert answer_service.called is False
    assert result.answer == "The word حنانا is mentioned at Surah Maryam, 19:13. [S1]"
    assert result.token_metadata["answer_mode"] == "confirmed_hypothesis"
    assert chunk_service.search_queries[0] == "حنانا"

    hypothesis_trace = next(
        trace for trace in result.chunk_traces if trace["stage"] == "query_hypothesis"
    )
    assert hypothesis_trace["status"] == "valid"
    expansion_trace = next(
        trace
        for trace in result.chunk_traces
        if trace.get("stage") == "domain_query_expansion"
    )
    assert expansion_trace["expansion_source"] == "query_hypothesis"
    assert expansion_trace["expansion_input_terms"] == ["hanan"]
    verification_trace = next(
        trace
        for trace in result.chunk_traces
        if trace["stage"] == "hypothesis_verification"
    )
    assert verification_trace["status"] == "confirmed"
    assert verification_trace["reference"] == "19:13"


@pytest.mark.asyncio
async def test_religious_query_requires_llm_planning_in_auto_mode():
    orchestrator = RetrievalOrchestrator(
        chunk_service=QuranDomainMetadataChunkSearchService(),
        answer_service=FakeAnswerService(),
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
        query_hypothesis_service=TimeoutHypothesisService(),
    )

    result = await orchestrator.query(
        "Which hadith mentions offering sacrifice for eid?",
        runtime=NativeSearchShouldNotRun(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-quran"],
        variant_id="variant-1",
        query_config={
            "limit": 8,
            "retrieval_mode": "metadata",
            "graph_expansion_enabled": False,
            "query_hypothesis_required": "auto",
            "query_hypothesis_timeout_ms": 5000,
        },
    )

    assert result.error_type == "query_hypothesis_failed"
    assert "LLM query planning failed" in (result.error or "")
    assert result.timings["query_hypothesis_timeout_ms"] == 5000


@pytest.mark.asyncio
async def test_orchestrator_tries_confirmed_hadith_reference_hypothesis_first():
    chunk_service = HadithReferenceChunkSearchService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=chunk_service,
        answer_service=FakeAnswerService(),
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
        query_hypothesis_service=CorrectHadithReferenceHypothesisService(),
    )

    result = await orchestrator.query(
        "Which hadith mentions offering sacrifice for eid?",
        runtime=NativeSearchShouldNotRun(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-hadith"],
        variant_id="variant-1",
        query_config={
            "limit": 8,
            "retrieval_mode": "metadata",
            "graph_expansion_enabled": False,
        },
    )

    assert result.error is None
    assert chunk_service.search_queries[0] == "book:13:hadith:25"
    assert result.sources[0]["metadata"]["canonical_reference"] == "book:13:hadith:25"
    verification_trace = next(
        trace for trace in result.chunk_traces if trace["stage"] == "hypothesis_verification"
    )
    assert verification_trace["status"] == "confirmed"
    assert verification_trace["possible_reference_results"][0]["status"] == "confirmed"
    assert verification_trace["reference"] == "book:13:hadith:25"


@pytest.mark.asyncio
async def test_orchestrator_uses_custom_reference_contract_hypothesis():
    chunk_service = ArticleClauseReferenceChunkSearchService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=chunk_service,
        answer_service=FakeAnswerService(),
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
        query_hypothesis_service=ArticleClauseReferenceHypothesisService(),
    )

    result = await orchestrator.query(
        "Show Article 12.7",
        runtime=NativeSearchShouldNotRun(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-policy"],
        variant_id="variant-1",
        query_config={
            "limit": 8,
            "retrieval_mode": "metadata",
            "graph_expansion_enabled": False,
        },
    )

    assert result.error is None
    assert chunk_service.search_queries[0] == "article:12:clause:7"
    assert result.sources[0]["metadata"]["canonical_reference"] == "article:12:clause:7"
    verification_trace = next(
        trace for trace in result.chunk_traces if trace["stage"] == "hypothesis_verification"
    )
    assert verification_trace["status"] == "confirmed"
    assert verification_trace["possible_reference_results"][0]["status"] == "confirmed"
    assert verification_trace["reference"] == "article:12:clause:7"


@pytest.mark.asyncio
async def test_orchestrator_keeps_semantic_fallback_when_reference_hypothesis_is_wrong():
    chunk_service = HadithReferenceChunkSearchService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=chunk_service,
        answer_service=FakeAnswerService(),
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
        query_hypothesis_service=WrongHadithReferenceHypothesisService(),
    )

    result = await orchestrator.query(
        "Which hadith mentions offering sacrifice for eid?",
        runtime=NativeSearchShouldNotRun(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-hadith"],
        variant_id="variant-1",
        query_config={
            "limit": 8,
            "retrieval_mode": "metadata",
            "graph_expansion_enabled": False,
        },
    )

    assert result.error is None
    assert chunk_service.search_queries[:2] == [
        "book:34:hadith:288",
        "Which hadith mentions offering sacrifice for eid?",
    ]
    assert result.sources[0]["metadata"]["canonical_reference"] == "book:13:hadith:25"
    verification_trace = next(
        trace for trace in result.chunk_traces if trace["stage"] == "hypothesis_verification"
    )
    assert verification_trace["status"] == "confirmed"
    assert verification_trace["reference"] == "book:13:hadith:25"
    assert verification_trace["possible_reference_results"][0]["status"] == "rejected"


@pytest.mark.asyncio
async def test_orchestrator_does_not_shortcut_semantic_hypothesis_with_target_terms():
    chunk_service = QuranDomainMetadataChunkSearchService()
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=chunk_service,
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
        query_hypothesis_service=SemanticHypothesisService(),
    )

    result = await orchestrator.query(
        "explain the concept of hanan",
        runtime=NativeSearchShouldNotRun(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-quran"],
        variant_id="variant-1",
        query_config={
            "limit": 8,
            "retrieval_mode": "metadata",
            "graph_expansion_enabled": False,
        },
    )

    assert result.error is None
    assert answer_service.called is True
    assert result.token_metadata["answer_mode"] == "full"
    verification_trace = next(
        trace
        for trace in result.chunk_traces
        if trace["stage"] == "hypothesis_verification"
    )
    assert verification_trace["status"] == "confirmed"


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
async def test_fast_mode_uses_metadata_when_native_misses_fast_budget():
    runtime = SlowNativeRuntimeTool()
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        answer_service=answer_service,
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "how many hadith in bukhari",
        runtime=runtime,
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={
            "limit": 8,
            "response_mode": "fast",
            "response_budget_ms": 200,
            "native_query_timeout_ms": 1,
            "graph_expansion_enabled": False,
        },
    )

    assert runtime.query_called is True
    assert result.error is None
    assert result.sources
    assert result.timings["native_degraded"] is True
    assert result.timings["native_error_type"] == "native_query_timeout"
    assert result.timings["response_budget_ms"] == 200
    assert answer_service.called is True


@pytest.mark.asyncio
async def test_fast_mode_applies_response_budget_to_metadata_and_native_retrieval():
    runtime = SlowNativeRuntimeTool()
    orchestrator = RetrievalOrchestrator(
        chunk_service=SlowChunkSearchService(),
        answer_service=FakeAnswerService(),
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "how many hadith in bukhari",
        runtime=runtime,
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={
            "limit": 8,
            "response_mode": "fast",
            "response_budget_ms": 1,
            "native_query_timeout_ms": 1000,
        },
    )

    assert runtime.query_called is True
    assert result.error_type == "parallel_retrieval_failed"
    assert result.timings["native_error_type"] == "native_query_timeout"
    assert result.timings["metadata_error_type"] == "TimeoutError"
    assert result.timings["total_ms"] < 250


@pytest.mark.asyncio
async def test_unscoped_metadata_retrieval_uses_route_lane_timeout():
    orchestrator = RetrievalOrchestrator(
        chunk_service=SlowChunkSearchService(),
        answer_service=FakeAnswerService(),
        reranker_service=FakeRerankerService(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "how many hadith in bukhari",
        runtime=EmptyRuntimeTool(),
        profile=type("Profile", (), {"enable_rerank": False, "reranker_provider": "disabled"})(),
        document_ids=[],
        variant_id="variant-1",
        query_config={
            "limit": 8,
            "response_mode": "fast",
            "response_budget_ms": 1,
        },
    )

    assert result.error_type == "metadata_retrieval_error"
    assert result.timings["total_ms"] < 100


@pytest.mark.asyncio
async def test_fast_mode_query_config_disables_profile_reranker():
    answer_service = FakeAnswerService()
    orchestrator = RetrievalOrchestrator(
        chunk_service=FakeChunkSearchService(),
        answer_service=answer_service,
        reranker_service=RerankerShouldNotRun(),
        graph_expansion_service=FakeGraphExpansionService(),
    )

    result = await orchestrator.query(
        "how many hadith in bukhari",
        runtime=FakeRuntimeTool(),
        profile=type("Profile", (), {"enable_rerank": True, "reranker_provider": "llm"})(),
        document_ids=["doc-1"],
        variant_id="variant-1",
        query_config={
            "limit": 8,
            "response_mode": "fast",
            "enable_rerank": False,
            "graph_expansion_enabled": False,
        },
    )

    assert result.error is None
    assert result.timings["rerank_ms"] == 0.0
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
