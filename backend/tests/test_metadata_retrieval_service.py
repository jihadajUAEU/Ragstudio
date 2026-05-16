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

    assert [call.query for call in chunk_service.calls][:2] == ["حنانا", "حنانا"]
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
    assert trace["passes"][1]["name"] == "semantic_metadata"
    assert trace["passes"][1]["candidate_count"] == 0


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
async def test_metadata_service_falls_back_for_legacy_lexical_expanded_passes():
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
            )
        ],
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
    assert candidates[0].match_features == {}
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
