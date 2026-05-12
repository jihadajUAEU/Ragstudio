from ragstudio.db.models import Chunk
from ragstudio.services.hybrid_chunk_search import HybridChunkSearch


def test_arabic_query_matches_diacritized_chunk_text():
    chunk = Chunk(
        id="chunk-1",
        document_id="doc-1",
        text="وَحَنَانًا مِّن لَّدُنَّا وَزَكَاةً",
        source_location={"page": 1},
        metadata_json={},
    )

    score = HybridChunkSearch().score("وحنانا", chunk)

    assert score.score > 0
    assert score.breakdown["arabic_exact"] >= 40.0


def test_arabic_query_matches_prefix_stripped_token():
    chunk = Chunk(
        id="chunk-1",
        document_id="doc-1",
        text="حَنَانًا مِّن لَّدُنَّا",
        source_location={"page": 1},
        metadata_json={},
    )

    score = HybridChunkSearch().score("وحنانا", chunk)

    assert score.score > 0
    assert score.breakdown["arabic_token"] >= 20.0


def test_arabic_query_does_not_match_quarantined_exact_policy():
    chunk = Chunk(
        id="chunk-1",
        document_id="doc-1",
        text="وَحَنَانًا مِّن لَّدُنَّا وَزَكَاةً",
        source_location={"page": 1},
        metadata_json={
            "quality_action_policy": {
                "index_vector": False,
                "index_exact_arabic": False,
                "project_graph": False,
                "graph_confidence": "blocked",
            },
        },
    )

    score = HybridChunkSearch().score("وحنانا", chunk)

    assert score.score == 0.0
    assert score.breakdown["quality_blocked_arabic"] == 1.0
