import pytest
from ragstudio.schemas.chunks import ChunkOut
from ragstudio.services.metadata_retrieval_service import MetadataRetrievalService
from ragstudio.services.query_understanding import understand_query


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
