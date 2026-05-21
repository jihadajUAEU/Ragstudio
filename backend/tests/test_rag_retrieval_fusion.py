from ragstudio.services.retrieval_evidence import EvidenceCandidate
from ragstudio.services.retrieval_fusion import RetrievalFusion


def _candidate(tool, chunk_id, text, score, features=None, references=None):
    return EvidenceCandidate(
        candidate_id=f"{tool}:{chunk_id}",
        text=text,
        document_id="doc-quran",
        chunk_id=chunk_id,
        source_location={"page": 1},
        metadata={
            "reference_metadata": {"references": references or []},
            "match_features": features or {},
        },
        tool=tool,
        tool_rank=1,
        base_score=score,
    )


def test_fusion_preserves_per_lane_rank_metadata():
    metadata = _candidate("metadata", "chunk-1", "Canonical metadata match.", 3.0)
    native = _candidate("native", "chunk-1", "Canonical metadata match.", 0.7)
    graph = _candidate("graph", "chunk-2", "Graph neighbor match.", 0.2)

    fused = RetrievalFusion().fuse(
        [
            [metadata],
            [native],
            [graph],
        ],
        limit=5,
    )

    assert fused[0].chunk_id == "chunk-1"
    assert fused[0].metadata["retrieval_passes"] == ["metadata", "native"]
    assert fused[0].metadata["lane_ranks"] == {"metadata": 1, "native": 1}
    assert fused[1].metadata["retrieval_passes"] == ["graph"]
    assert fused[1].metadata["lane_ranks"]["graph"] == 1


def test_fusion_uses_rrf_rank_bridge_instead_of_raw_score_addition():
    lexical = _candidate("metadata", "lexical-top", "Exact lexical match.", 1000.0)
    vector = _candidate("pgvector", "vector-top", "Semantic match.", 0.92)

    fused = RetrievalFusion().fuse([[lexical], [vector]], limit=5)

    first_score_basis = fused[0].metadata["fusion_score_basis"]
    second_score_basis = fused[1].metadata["fusion_score_basis"]

    assert first_score_basis["formula"] == "rrf"
    assert first_score_basis["rrf_k"] == 60
    assert "raw_lane_score" not in first_score_basis
    assert {candidate.chunk_id for candidate in fused[:2]} == {"lexical-top", "vector-top"}
    assert {candidate.final_score for candidate in fused[:2]} == {
        first_score_basis["rrf_score"],
        second_score_basis["rrf_score"],
    }
    assert all(candidate.final_score < 1.0 for candidate in fused[:2])


def test_fusion_orders_by_rrf_score_before_lane_tie_break():
    metadata = _candidate("metadata", "metadata-once", "Single lane match.", 99.0)
    native_first = _candidate("native", "native-twice", "Repeated native match.", 0.1)
    native_second = _candidate("native", "native-twice", "Repeated native match.", 0.1)

    fused = RetrievalFusion().fuse(
        [
            [native_first],
            [native_second],
            [metadata],
        ],
        limit=5,
    )

    assert fused[0].chunk_id == "native-twice"
    assert fused[0].metadata["fusion_score_basis"]["rrf_score"] > fused[1].metadata[
        "fusion_score_basis"
    ]["rrf_score"]


def test_exact_arabic_token_outranks_broad_semantic_match():
    semantic = _candidate(
        "pgvector",
        "semantic-1",
        "Allah guides people in many passages.",
        0.91,
    )
    lexical = _candidate(
        "arabic_lexical",
        "quran-19-13",
        "[19:13] وَحَنَانًا مِّن لَّدُنَّا وَزَكَاةً",
        0.5,
        features={"arabic_exact": True, "arabic_token": "وحنانا"},
        references=["19:13"],
    )

    fused = RetrievalFusion().fuse([[semantic], [lexical]], limit=5)

    assert fused[0].chunk_id == "quran-19-13"
    assert "direct_arabic_match" in fused[0].reasons


def test_exact_reference_outranks_exact_arabic_when_reference_requested():
    reference = _candidate(
        "reference_exact",
        "quran-24-35",
        "[24:35] Allah is the Light of the heavens and the earth.",
        0.4,
        features={"reference_exact": True},
        references=["24:35"],
    )
    lexical = _candidate(
        "arabic_lexical",
        "quran-19-13",
        "[19:13] وَحَنَانًا مِّن لَّدُنَّا",
        0.8,
        features={"arabic_exact": True},
        references=["19:13"],
    )

    fused = RetrievalFusion().fuse([[lexical], [reference]], limit=5)

    assert fused[0].chunk_id == "quran-24-35"
    assert "exact_reference_match" in fused[0].reasons
