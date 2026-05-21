from types import SimpleNamespace

from ragstudio.services.hybrid_chunk_search import (
    HybridChunkSearch,
    _arabic_phrase_boundary_pattern,
)


class Chunk(SimpleNamespace):
    pass


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


def test_count_intent_uses_domain_metadata_without_domain_specific_terms():
    query = "How many severe medication incidents were reported?"
    domain_metadata = {
        "domain": "medical_safety",
        "document_type": "safety_report",
        "custom_json": {
            "search_intents": [
                {
                    "query_terms": ["how", "many", "count", "number", "total"],
                    "requires_numeric_evidence": True,
                    "vocabulary": ["events"],
                    "boost": 30.0,
                }
            ],
            "domain_vocabulary": {
                "events": ["incident", "near_miss", "medication"],
                "term_aliases": {"incident": ["event", "case"]},
            },
        },
    }
    correct = Chunk(
        id="correct",
        document_id="doc-1",
        text=(
            "Medication safety summary: 12 severe medication incidents were reported "
            "during the quarter."
        ),
        source_location={"page": 374},
        metadata_json={"domain_metadata": domain_metadata},
    )
    distractor = Chunk(
        id="distractor",
        document_id="doc-1",
        text=(
            "The safety committee discussed training improvements and reporting forms."
        ),
        source_location={"page": 2000},
        metadata_json={"domain_metadata": domain_metadata},
    )

    search = HybridChunkSearch()
    correct_score = search.score(query, correct)
    distractor_score = search.score(query, distractor)

    assert correct_score.score > distractor_score.score
    assert correct_score.breakdown["domain_intent"] == 30.0
    assert distractor_score.breakdown["domain_intent"] == 0.0


def test_domain_intent_phrase_requires_full_query_phrase():
    domain_metadata = {
        "domain": "clinical",
        "custom_json": {
            "search_intents": [
                {
                    "query_terms": ["how many", "count"],
                    "requires_numeric_evidence": True,
                    "vocabulary": ["incident"],
                    "boost": 30.0,
                }
            ],
            "domain_vocabulary": {"events": ["incident"]},
        },
    }
    chunk = Chunk(
        id="chunk-1",
        document_id="doc-1",
        text="Medication incident classification lists 12 severe events.",
        source_location={"page": 1},
        metadata_json={"domain_metadata": domain_metadata},
    )

    false_match = HybridChunkSearch().score("How are medication incidents classified?", chunk)
    true_match = HybridChunkSearch().score("How many medication incidents were severe?", chunk)

    assert false_match.breakdown["domain_intent"] == 0.0
    assert true_match.breakdown["domain_intent"] == 30.0


def test_retrieval_explain_uses_weighted_score_breakdown():
    chunk = Chunk(
        id="chunk-1",
        document_id="doc-1",
        text="alpha beta gamma",
        source_location={"page": 1},
        metadata_json={},
    )

    score = HybridChunkSearch().score("alpha beta gamma", chunk, search_weights={"exact_phrase": 0})

    signals = score.breakdown["retrieval_explain"]["signals"]
    signal_names = {signal["name"] for signal in signals}

    assert score.breakdown["exact_phrase"] == 8.0
    assert score.breakdown["weighted_score_breakdown"]["exact_phrase"] == 0.0
    assert "exact_phrase" not in signal_names


def test_terms_do_not_expand_eid_without_domain_vocabulary():
    search = HybridChunkSearch()

    terms = search._terms("eid", None)

    assert terms == {"eid"}


def test_terms_use_domain_vocabulary_aliases_when_metadata_provides_them():
    domain_metadata = {
        "domain": "holiday_report",
        "custom_json": {
            "domain_vocabulary": {
                "holidays": ["eid"],
                "term_aliases": {"eid": ["id", "adha"]},
            }
        },
    }
    chunk = Chunk(
        id="chunk-1",
        document_id="doc-1",
        text="The office was closed for Id al-Adha.",
        source_location={"page": 1},
        metadata_json={"domain_metadata": domain_metadata},
    )

    score = HybridChunkSearch().score("eid closure", chunk)

    assert "weighted_score_breakdown" in score.breakdown
    assert score.breakdown["term_coverage"] > 0.0
    assert score.breakdown["semantic_density"] == 0.0
    assert score.breakdown["metadata_boost"] == 0.0
    assert score.breakdown["domain_intent"] == 0.0


def test_semantic_density_weight_controls_real_breakdown_component():
    chunk = Chunk(
        id="chunk-1",
        document_id="doc-1",
        text="alpha beta gamma delta",
        source_location={"page": 1},
        metadata_json={},
    )

    unweighted = HybridChunkSearch().score("alpha beta", chunk)
    weighted = HybridChunkSearch().score(
        "alpha beta",
        chunk,
        search_weights={"semantic_density": 2.0},
    )

    assert unweighted.breakdown["semantic_density"] > 0.0
    assert "term_density" not in unweighted.breakdown
    assert weighted.breakdown["weighted_score_breakdown"]["semantic_density"] == (
        unweighted.breakdown["semantic_density"] * 2.0
    )


def test_cross_reference_only_inline_reference_does_not_get_reference_exact_boost():
    domain_metadata = {
        "domain": "quran_tafseer",
        "document_type": "commentary",
        "citation_style": "surah_ayah",
        "custom_json": {
            "reference_schema": {
                "type": "chapter_verse",
                "canonical_ref_template": "{chapter}:{verse}",
            },
            "domain_structure": {
                "primary_anchor": {
                    "regex": r"\bVerse\s+(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})\b",
                    "unit": "verse_section",
                },
                "inline_references": {
                    "regex": r"(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})",
                    "policy": "cross_reference_only",
                },
            },
            "retrieval": {"exact_reference_top1": True},
        },
    }
    chunk = Chunk(
        id="chunk-1",
        document_id="doc-1",
        text=(
            "Verse 18:30 Indeed, those who believe are rewarded. "
            "The commentary mentions 25:75-76."
        ),
        source_location={"page": 1},
        metadata_json={
            "domain_metadata": domain_metadata,
            "reference_metadata": {
                "references": ["18:30"],
                "cross_references": ["25:75"],
                "chapter_start": 18,
                "chapter_end": 18,
                "verse_start": 30,
                "verse_end": 30,
            },
        },
    )

    inline_score = HybridChunkSearch().score("25:75", chunk)
    primary_score = HybridChunkSearch().score("18:30", chunk)

    assert inline_score.breakdown["reference_exact"] == 0.0
    assert primary_score.breakdown["reference_exact"] == 100.0


def test_arabic_phrase_boundary_pattern_is_cached():
    first = _arabic_phrase_boundary_pattern("\u0648\u062d\u0646\u0627\u0646\u0627")
    second = _arabic_phrase_boundary_pattern("\u0648\u062d\u0646\u0627\u0646\u0627")

    assert first is second


def test_compiled_answer_bearing_phrase_patterns_preserve_phrase_boost():
    chunk = Chunk(
        id="chunk-phrase",
        document_id="doc-1",
        text="This section is translated as guide us to the straight path.",
        source_location={"page": 1},
        metadata_json={},
    )

    score = HybridChunkSearch().score(
        'Which verse is translated as "guide us to the straight path"?',
        chunk,
    )

    assert score.breakdown["exact_phrase"] >= 24.0
