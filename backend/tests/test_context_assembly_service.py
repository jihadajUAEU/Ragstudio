from ragstudio.services.context_assembly_service import (
    ContextAssemblyService,
    _should_offload_tokenization,
)
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


def test_context_assembly_uses_conservative_arabic_token_estimate():
    arabic = _candidate(
        "arabic_lexical",
        "quran-19-13",
        "وحنانا من لدنا وزكاة وكان تقيا",
        1,
        features={"arabic_exact": True},
        refs=["19:13"],
    )

    context = ContextAssemblyService(max_context_tokens=100).assemble([arabic])

    assert context.total_estimated_tokens >= 12


def test_context_assembly_records_direct_evidence_budget_conflict():
    direct = _candidate(
        "reference_exact",
        "quran-24-35",
        " ".join(["direct"] * 80),
        1,
        features={"reference_exact": True},
        refs=["24:35"],
    )

    context = ContextAssemblyService(max_context_tokens=10).assemble([direct])

    assert context.evidence[0].chunk_id == "quran-24-35"
    assert context.dropped[0].candidate_id == "reference_exact:quran-24-35"
    assert context.dropped[0].drop_reason == "direct_evidence_preserved_over_budget"
    assert context.dropped[0].detail == "required_direct_evidence_was_kept"


def test_context_assembly_drops_policy_blocked_candidates():
    blocked = _candidate("pgvector", "blocked-1", "Blocked evidence", 1)
    blocked = blocked.__class__(
        **{
            **blocked.__dict__,
            "metadata": {
                **blocked.metadata,
                "quality_action_policy": {"action": "block"},
            },
        }
    )

    context = ContextAssemblyService(max_context_tokens=100).assemble([blocked])

    assert context.evidence == []
    assert context.dropped[0].drop_reason == "quality_policy_block"


def test_context_assembly_does_not_mark_dropped_direct_evidence_grounded():
    blocked = _candidate(
        "reference_exact",
        "blocked-direct",
        "Blocked direct evidence",
        1,
        features={"reference_exact": True},
        refs=["24:35"],
    )
    blocked = blocked.__class__(
        **{
            **blocked.__dict__,
            "metadata": {
                **blocked.metadata,
                "quality_action_policy": {"action": "block"},
            },
        }
    )

    context = ContextAssemblyService(max_context_tokens=100).assemble([blocked])

    assert context.evidence == []
    assert context.dropped[0].drop_reason == "quality_policy_block"
    assert context.grounding_status == "insufficient_evidence"


def test_context_assembly_drops_runtime_and_graph_risk_flags():
    runtime = _candidate("runtime", "runtime-1", "Runtime evidence", 1)
    runtime = runtime.__class__(
        **{**runtime.__dict__, "risk_flags": ["runtime_bridge_missing"]}
    )
    graph = _candidate("graph", "graph-1", "Graph evidence", 2)
    graph = graph.__class__(
        **{**graph.__dict__, "risk_flags": ["graph_projection_stale"]}
    )

    context = ContextAssemblyService(max_context_tokens=100).assemble([runtime, graph])

    assert context.evidence == []
    assert [item.drop_reason for item in context.dropped] == [
        "runtime_bridge_missing",
        "graph_projection_stale",
    ]


def test_context_assembly_drops_reranker_degraded_candidates():
    degraded = _candidate("reranker", "degraded-1", "Degraded evidence", 1)
    degraded = degraded.__class__(
        **{
            **degraded.__dict__,
            "metadata": {**degraded.metadata, "reranker_status": "degraded"},
        }
    )

    context = ContextAssemblyService(max_context_tokens=100).assemble([degraded])

    assert context.evidence == []
    assert context.dropped[0].drop_reason == "reranker_degraded"


def test_context_assembly_truncates_direct_evidence_at_hard_model_limit():
    direct = _candidate(
        "reference_exact",
        "long-direct",
        "Paragraph one.\n\n" + " ".join(["direct"] * 200),
        1,
        features={"reference_exact": True},
        refs=["24:35"],
    )

    context = ContextAssemblyService(
        max_context_tokens=500,
        hard_context_tokens=20,
    ).assemble([direct])

    assert context.evidence[0].chunk_id == "long-direct"
    assert context.evidence[0].original_text == "Paragraph one."
    assert context.dropped[0].drop_reason == "context_truncated"
    assert context.dropped[0].detail == "required_evidence_truncated_to_hard_context_limit"


def test_context_assembly_tokenizer_offload_helper_flags_large_payloads():
    assert _should_offload_tokenization("word " * 10_001) is True
    assert _should_offload_tokenization("word " * 10_000) is False


def test_context_assembly_injects_breadcrumb_text_from_evidence_context():
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

    context = ContextAssemblyService(max_context_tokens=200).assemble([candidate])

    assert context.evidence[0].breadcrumb == "Synthetic Tafseer > 1:5"
    assert context.evidence[0].context_text.startswith("[Synthetic Tafseer > 1:5]")


def test_context_assembly_dynamic_fallback_breadcrumb_resolution():
    candidate = EvidenceCandidate(
        candidate_id="metadata:chunk-2",
        text="Seek help through patience and prayer.",
        document_id="doc-2",
        chunk_id="chunk-2",
        source_location={"page": 2, "reference": "2:45"},
        metadata={
            "document_metadata": {"title": "Holy Book"},
            "section_path": ["Surah Al-Baqarah"],
        },
        tool="metadata",
        tool_rank=1,
        base_score=10,
    )

    context = ContextAssemblyService(max_context_tokens=200).assemble([candidate])

    assert context.evidence[0].breadcrumb == "Holy Book > Surah Al-Baqarah > 2:45"
    assert context.evidence[0].layout_summary == "page=2"
    assert context.evidence[0].context_text.startswith(
        "[Holy Book > Surah Al-Baqarah > 2:45 | page=2]"
    )


def test_context_assembly_preserves_structural_context_reason():
    candidate = EvidenceCandidate(
        candidate_id="context-window:chunk-2",
        text="Continuation text",
        document_id="doc-1",
        chunk_id="chunk-2",
        source_location={"page": 2},
        metadata={"heading_path": ["Part 1", "Section 2"]},
        tool="metadata",
        tool_rank=1,
        base_score=1.0,
        reasons=["context_window", "heading_path_context"],
        retrieval_pass="context_window",
    )

    assembled = ContextAssemblyService().assemble([candidate])

    assert assembled.evidence[0].included_reason == "structural_context"
