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
