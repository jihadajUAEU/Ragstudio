import asyncio
from time import perf_counter

import pytest
from ragstudio.db.models import Chunk, Document
from ragstudio.schemas.chunks import ChunkOut
from ragstudio.services.chunk_lexical_search_repository import ChunkLexicalSearchRepository
from ragstudio.services.metadata_retrieval_service import MetadataRetrievalService
from ragstudio.services.query_understanding import (
    QueryUnderstanding,
    RetrievalPass,
    understand_query,
)


class FakeChunkService:
    def __init__(self):
        self.calls = []

    async def search(self, search_in):
        self.calls.append(search_in)
        if search_in.query in {"حنانا", "وحنانا"}:
            return type(
                "SearchResult",
                (),
                {
                    "items": [
                        ChunkOut(
                            id="chunk-19-13",
                            document_id="doc-quran",
                            text="[19:13] وَحَنَانًا مِّن لَّدُنَّا",
                            source_location={"page": 312, "reference": "19:13"},
                            metadata={
                                "score": 100,
                                "reference_metadata": {"references": ["19:13"]},
                                "tokens_ar": ["وحنانا", "حنانا"],
                            },
                        )
                    ],
                    "total": 1,
                },
            )()
        return type("SearchResult", (), {"items": [], "total": 0})()


class MismatchedReferenceChunkService:
    async def search(self, search_in):
        if search_in.query == "Explain 1:5":
            return type(
                "SearchResult",
                (),
                {
                    "items": [
                        ChunkOut(
                            id="chunk-2-2",
                            document_id="doc-quran",
                            text="Verse 2:2 context.",
                            source_location={"reference": "2:2"},
                            metadata={
                                "score": 4.0,
                                "score_breakdown": {"reference_exact": 0.0},
                                "reference_metadata": {"references": ["2:2"]},
                            },
                        )
                    ],
                    "total": 1,
                },
            )()
        return type("SearchResult", (), {"items": [], "total": 0})()


class LexicalExpandedChunkService:
    def __init__(self):
        self.calls = []

    async def search(self, search_in):
        self.calls.append(search_in)
        if search_in.query == "حنانا":
            return type(
                "SearchResult",
                (),
                {
                    "items": [
                        ChunkOut(
                            id="chunk-19-13-expanded",
                            document_id="doc-quran",
                            text="[19:13] and affection from Us",
                            source_location={"page": 312, "reference": "19:13"},
                            metadata={"score": 90},
                        )
                    ],
                    "total": 1,
                },
            )()
        return type("SearchResult", (), {"items": [], "total": 0})()


class HypothesisReferenceChunkService:
    def __init__(self):
        self.calls = []

    async def search(self, search_in):
        self.calls.append(search_in)
        if search_in.query == "book:34:hadith:288":
            return type(
                "SearchResult",
                (),
                {
                    "items": [
                        ChunkOut(
                            id="wrong-hypothesis-reference",
                            document_id="doc-hadith",
                            text="Book 34, Hadith 288. A different topic.",
                            source_location={"reference": "Book 34, Hadith 288"},
                            metadata={
                                "score": 100.0,
                                "reference_metadata": {
                                    "references": ["book:34:hadith:288"]
                                },
                            },
                        )
                    ],
                    "total": 1,
                },
            )()
        if search_in.query == "offering sacrifice eid":
            return type(
                "SearchResult",
                (),
                {
                    "items": [
                        ChunkOut(
                            id="semantic-correct-reference",
                            document_id="doc-hadith",
                            text="Book 13, Hadith 25. Eid prayer before sacrifice.",
                            source_location={"reference": "Book 13, Hadith 25"},
                            metadata={
                                "score": 12.0,
                                "reference_metadata": {
                                    "references": ["book:13:hadith:25"]
                                },
                            },
                        )
                    ],
                    "total": 1,
                },
            )()
        return type("SearchResult", (), {"items": [], "total": 0})()


class SlowMetadataPassChunkService:
    def __init__(self):
        self.started: list[str] = []
        self.finished: list[str] = []

    async def search(self, search_in):
        self.started.append(search_in.query)
        await asyncio.sleep(0.05)
        self.finished.append(search_in.query)
        return type(
            "SearchResult",
            (),
            {
                "items": [
                    ChunkOut(
                        id=f"chunk-{search_in.query}",
                        document_id="doc-1",
                        text=f"Result for {search_in.query}",
                        source_location={},
                        metadata={"score": 10.0},
                    )
                ],
                "total": 1,
            },
        )()


class DirectEvidenceParallelChunkService:
    def __init__(self):
        self.calls: list[str] = []

    async def search(self, search_in):
        self.calls.append(search_in.query)
        if search_in.query == "direct":
            items = [
                ChunkOut(
                    id="direct",
                    document_id="doc-1",
                    text="Direct evidence",
                    source_location={},
                    metadata={"score": 100.0},
                )
            ]
        else:
            items = [
                ChunkOut(
                    id="later",
                    document_id="doc-1",
                    text="Later evidence",
                    source_location={},
                    metadata={"score": 50.0},
                )
            ]
        return type("SearchResult", (), {"items": items, "total": len(items)})()


class LegacyLexicalExpandedPass:
    name = "lexical_expanded_token"
    query = "حنانا"
    limit_multiplier = 1
    direct_evidence = True


def test_hybrid_search_boosts_layout_context_matches():
    from ragstudio.services.hybrid_chunk_search import HybridChunkSearch

    chunk = Chunk(
        id="chunk-table-context",
        document_id="doc-layout",
        text="Revenue grew by 12 percent.",
        metadata_json={
            "modality": "table",
            "provenance": {
                "blocks": [
                    {
                        "role": "table",
                        "block_type": "table",
                        "page_start": 4,
                        "text_preview": "Revenue table",
                    }
                ]
            },
            "layout_context": {
                "section_title": "Financial results",
                "visual_neighborhood": ["table", "caption"],
            },
        },
    )

    score = HybridChunkSearch().score("financial results table revenue", chunk)

    assert score.breakdown["layout_context"] > 0
    assert score.score >= score.breakdown["layout_context"]


def test_metadata_candidate_preserves_layout_context_match_feature():
    service = MetadataRetrievalService(FakeChunkService())
    candidate = service._candidate_from_chunk(
        ChunkOut(
            id="chunk-layout-feature",
            document_id="doc-layout",
            text="Revenue table",
            source_location={"page": 4},
            metadata={
                "score": 18.0,
                "score_breakdown": {"layout_context": 8.0},
            },
        ),
        1,
        RetrievalPass("semantic_metadata", "financial results table"),
    )

    assert candidate.match_features == {
        "semantic_metadata": True,
        "layout_context": True,
    }


@pytest.mark.asyncio
async def test_metadata_service_runs_non_blocking_passes_concurrently():
    chunk_service = SlowMetadataPassChunkService()
    understanding = QueryUnderstanding(
        query="query",
        intent="mixed",
        answer_type="text",
        retrieval_passes=[
            RetrievalPass("phrase_exact", "phrase"),
            RetrievalPass("semantic_metadata", "semantic"),
        ],
    )

    started = perf_counter()
    candidates, trace = await MetadataRetrievalService(
        chunk_service,
        parallel_search=chunk_service.search,
    ).retrieve(
        "query",
        understanding=understanding,
        document_ids=["doc-1"],
        variant_id="variant-1",
        limit=5,
    )
    elapsed = perf_counter() - started

    assert elapsed < 0.09
    assert chunk_service.started == ["phrase", "semantic"]
    assert sorted(chunk_service.finished) == ["phrase", "semantic"]
    assert [candidate.chunk_id for candidate in candidates] == [
        "chunk-phrase",
        "chunk-semantic",
    ]
    assert [item["name"] for item in trace["passes"]] == [
        "phrase_exact",
        "semantic_metadata",
    ]


@pytest.mark.asyncio
async def test_metadata_service_uses_sequential_search_without_parallel_callable():
    chunk_service = SlowMetadataPassChunkService()
    understanding = QueryUnderstanding(
        query="query",
        intent="mixed",
        answer_type="text",
        retrieval_passes=[
            RetrievalPass("phrase_exact", "phrase"),
            RetrievalPass("semantic_metadata", "semantic"),
        ],
    )

    started = perf_counter()
    candidates, trace = await MetadataRetrievalService(chunk_service).retrieve(
        "query",
        understanding=understanding,
        document_ids=["doc-1"],
        variant_id="variant-1",
        limit=5,
    )
    elapsed = perf_counter() - started

    assert elapsed >= 0.09
    assert [candidate.chunk_id for candidate in candidates] == [
        "chunk-phrase",
        "chunk-semantic",
    ]
    assert [item["name"] for item in trace["passes"]] == [
        "phrase_exact",
        "semantic_metadata",
    ]


@pytest.mark.asyncio
async def test_metadata_service_replays_parallel_results_in_pass_order_and_stops_trace():
    chunk_service = DirectEvidenceParallelChunkService()
    understanding = QueryUnderstanding(
        query="query",
        intent="mixed",
        answer_type="text",
        retrieval_passes=[
            RetrievalPass("phrase_exact", "direct", direct_evidence=True),
            RetrievalPass("semantic_metadata", "later"),
        ],
    )

    candidates, trace = await MetadataRetrievalService(
        chunk_service,
        parallel_search=chunk_service.search,
    ).retrieve(
        "query",
        understanding=understanding,
        document_ids=["doc-1"],
        variant_id="variant-1",
        limit=5,
    )

    assert sorted(chunk_service.calls) == ["direct", "later"]
    assert [candidate.chunk_id for candidate in candidates] == ["direct"]
    assert [item["name"] for item in trace["passes"]] == ["phrase_exact"]


@pytest.mark.asyncio
async def test_metadata_service_runs_arabic_exact_before_semantic():
    chunk_service = FakeChunkService()
    understanding = understand_query("حنانا")

    candidates, trace = await MetadataRetrievalService(chunk_service).retrieve(
        "حنانا",
        understanding=understanding,
        document_ids=["doc-quran"],
        variant_id="variant-1",
        limit=5,
    )

    assert [call.query for call in chunk_service.calls] == ["حنانا"]
    assert len(candidates) == 1
    assert candidates[0].chunk_id == "chunk-19-13"
    assert candidates[0].tool == "metadata"
    assert candidates[0].retrieval_pass == "arabic_exact_token"
    assert candidates[0].match_features == {
        "arabic_exact": True,
        "arabic_token": "حنانا",
    }
    assert candidates[0].canonical_reference == "19:13"
    assert candidates[0].scope_status == "in_scope"
    assert trace["stage"] == "metadata_retrieval"
    assert trace["passes"][0]["name"] == "arabic_exact_token"
    assert trace["passes"][0]["query"] == "حنانا"
    assert trace["passes"][0]["candidate_count"] == 1
    assert trace["passes"][0]["latency_ms"] >= 0
    assert trace["passes"][0]["top_candidate_ids"] == ["metadata:chunk-19-13"]
    assert len(trace["passes"]) == 1


@pytest.mark.asyncio
async def test_metadata_service_runs_lexical_expanded_token_passes():
    chunk_service = LexicalExpandedChunkService()
    understanding = QueryUnderstanding(
        query="hanana",
        intent="lexical_expanded_token",
        answer_type="reference",
        retrieval_passes=[
            RetrievalPass(
                name="lexical_expanded_token",
                query="حنانا",
                direct_evidence=True,
                match_type="exact_script",
            )
        ],
    )

    candidates, trace = await MetadataRetrievalService(chunk_service).retrieve(
        "hanana",
        understanding=understanding,
        document_ids=["doc-quran"],
        variant_id="variant-1",
        limit=5,
    )

    assert [call.query for call in chunk_service.calls] == ["حنانا"]
    assert len(candidates) == 1
    assert candidates[0].chunk_id == "chunk-19-13-expanded"
    assert candidates[0].retrieval_pass == "lexical_expanded_token"
    assert candidates[0].match_features == {
        "lexical_expanded": True,
        "expanded_token": "حنانا",
        "match_type": "exact_script",
    }
    assert trace["passes"][0]["name"] == "lexical_expanded_token"
    assert trace["passes"][0]["query"] == "حنانا"
    assert trace["passes"][0]["candidate_count"] == 1


@pytest.mark.asyncio
async def test_metadata_service_stops_after_direct_lexical_expanded_candidate():
    chunk_service = LexicalExpandedChunkService()
    understanding = QueryUnderstanding(
        query="hanana",
        intent="lexical_expanded_token",
        answer_type="reference",
        retrieval_passes=[
            RetrievalPass(
                name="lexical_expanded_token",
                query="حنانا",
                direct_evidence=True,
                match_type="transliteration",
            ),
            RetrievalPass("semantic_metadata", "hanana"),
        ],
    )

    candidates, trace = await MetadataRetrievalService(chunk_service).retrieve(
        "hanana",
        understanding=understanding,
        document_ids=["doc-quran"],
        variant_id="variant-1",
        limit=5,
    )

    assert [call.query for call in chunk_service.calls] == ["حنانا"]
    assert len(candidates) == 1
    assert candidates[0].chunk_id == "chunk-19-13-expanded"
    assert [item["name"] for item in trace["passes"]] == ["lexical_expanded_token"]


@pytest.mark.asyncio
async def test_metadata_service_does_not_stop_after_hypothesis_reference_candidate():
    chunk_service = HypothesisReferenceChunkService()
    understanding = QueryUnderstanding(
        query="offering sacrifice eid",
        intent="lexical_expanded_token",
        answer_type="reference",
        retrieval_passes=[
            RetrievalPass(
                name="reference_exact",
                query="book:34:hadith:288",
                direct_evidence=True,
                match_type="hypothesis_reference",
            ),
            RetrievalPass("semantic_metadata", "offering sacrifice eid"),
        ],
    )

    candidates, trace = await MetadataRetrievalService(chunk_service).retrieve(
        "offering sacrifice eid",
        understanding=understanding,
        document_ids=["doc-hadith"],
        variant_id="variant-1",
        limit=5,
    )

    assert [call.query for call in chunk_service.calls] == [
        "book:34:hadith:288",
        "offering sacrifice eid",
    ]
    assert [candidate.chunk_id for candidate in candidates] == [
        "wrong-hypothesis-reference",
        "semantic-correct-reference",
    ]
    assert candidates[0].retrieval_pass == "reference_hypothesis"
    assert candidates[0].match_features == {
        "reference_hypothesis": True,
        "reference": "book:34:hadith:288",
        "match_type": "hypothesis_reference",
    }
    assert [item["name"] for item in trace["passes"]] == [
        "reference_exact",
        "semantic_metadata",
    ]


@pytest.mark.asyncio
async def test_metadata_service_falls_back_for_legacy_lexical_expanded_passes():
    chunk_service = LexicalExpandedChunkService()
    understanding = QueryUnderstanding(
        query="hanana",
        intent="lexical_expanded_token",
        answer_type="reference",
        retrieval_passes=[LegacyLexicalExpandedPass()],
    )

    candidates, _trace = await MetadataRetrievalService(chunk_service).retrieve(
        "hanana",
        understanding=understanding,
        document_ids=["doc-quran"],
        variant_id="variant-1",
        limit=5,
    )

    assert candidates[0].match_features["match_type"] == "transliteration"


@pytest.mark.asyncio
async def test_metadata_service_does_not_mark_mismatched_reference_as_exact():
    candidates, _trace = await MetadataRetrievalService(
        MismatchedReferenceChunkService()
    ).retrieve(
        "Explain 1:5",
        understanding=understand_query("Explain 1:5"),
        document_ids=["doc-quran"],
        variant_id="variant-1",
        limit=5,
    )

    assert candidates[0].chunk_id == "chunk-2-2"
    assert candidates[0].retrieval_pass == "semantic_metadata"
    assert candidates[0].match_features == {"semantic_metadata": True}
    assert candidates[0].canonical_reference == "2:2"


@pytest.mark.asyncio
async def test_reference_prefilter_returns_exact_preview_ref_before_full_scan(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        document = Document(
            filename="tafseer.txt",
            content_type="text/plain",
            sha256="tafseer-ref-prefilter",
            artifact_path=str(app.state.settings.data_dir / "tafseer.txt"),
            status="succeeded",
        )
        session.add(document)
        await session.flush()
        session.add_all(
            [
                Chunk(
                    document_id=document.id,
                    text=f"Filler chunk {index}",
                    preview_ref=None,
                    metadata_json={},
                    source_location={},
                )
                for index in range(100)
            ]
        )
        exact = Chunk(
            document_id=document.id,
            text="Verse 1:5 Guide us to the straight path.",
            preview_ref="1:5",
            metadata_json={"reference_metadata": {"references": ["1:5"]}},
            source_location={"reference": "1:5"},
        )
        session.add(exact)
        await session.commit()

        results = await ChunkLexicalSearchRepository(session).reference_prefilter(
            query="Explain 1:5",
            document_ids=[document.id],
            limit=5,
        )

    assert [chunk.preview_ref for chunk in results] == ["1:5"]
