from ragstudio.services.context_assembly_service import ContextAssemblyService
from ragstudio.services.retrieval_evidence import EvidenceCandidate


def _candidate(tool, chunk_id, text, rank, features=None, refs=None):
    return EvidenceCandidate(
        candidate_id=f"{tool}:{chunk_id}",
        text=text,
        document_id="doc-quran",
        chunk_id=chunk_id,
        source_location={"page": rank},
        metadata={
            "reference_metadata": {"references": refs or []},
            "retrieval_passes": [tool],
            "match_features": features or {},
        },
        tool=tool,
        tool_rank=rank,
        base_score=1.0,
        final_score=1.0,
        reasons=["test"],
    )


def test_context_assembly_pins_direct_evidence_before_semantic_context():
    semantic = _candidate("pgvector", "semantic-1", "general guidance text", 1)
    direct = _candidate(
        "arabic_lexical",
        "quran-19-13",
        "[19:13] وَحَنَانًا مِّن لَّدُنَّا وَزَكَاةً",
        2,
        features={"arabic_exact": True},
        refs=["19:13"],
    )

    context = ContextAssemblyService(max_context_tokens=200).assemble([semantic, direct])

    assert context.evidence[0].chunk_id == "quran-19-13"
    assert context.evidence[0].original_text.startswith("[19:13]")
    assert context.evidence[0].normalized_text is None


def test_context_assembly_dedupes_candidates_and_merges_retrieval_passes():
    lexical = _candidate("arabic_lexical", "quran-19-13", "[19:13] وَحَنَانًا", 1, refs=["19:13"])
    vector = _candidate("pgvector", "quran-19-13", "[19:13] وَحَنَانًا", 2, refs=["19:13"])

    context = ContextAssemblyService(max_context_tokens=200).assemble([lexical, vector])

    assert len(context.evidence) == 1
    assert context.evidence[0].retrieval_passes == ["arabic_lexical", "pgvector"]


def test_context_assembly_drops_low_value_semantic_when_budget_is_small():
    direct = _candidate(
        "reference_exact",
        "quran-24-35",
        "[24:35] Allah is the Light of the heavens and the earth.",
        1,
        features={"reference_exact": True},
        refs=["24:35"],
    )
    semantic = _candidate("pgvector", "long-semantic", "word " * 300, 2)

    context = ContextAssemblyService(max_context_tokens=20).assemble([direct, semantic])

    assert [item.chunk_id for item in context.evidence] == ["quran-24-35"]
    assert context.dropped[0].candidate_id == "pgvector:long-semantic"
    assert context.dropped[0].drop_reason == "token_budget"
