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


def test_hadith_topic_query_prioritizes_answer_terms_over_question_scaffolding():
    query = "Which is the hadith saying about offering sacrifice for eid from hadith_bukhari"
    domain_metadata = {
        "domain": "hadith",
        "document_type": "collection",
        "collection": "sahih_bukhari",
        "tags": ["hadith", "islamic_text"],
    }
    correct = Chunk(
        id="correct",
        document_id="doc-1",
        text=(
            "Book 13, Hadith 25\n\n"
            "The Prophet went on the day of Id-ul-Adha and said our first act "
            "is offering the prayer, then we return and slaughter the sacrifice."
        ),
        source_location={"page": 374},
        metadata_json={"domain_metadata": domain_metadata},
    )
    distractor = Chunk(
        id="distractor",
        document_id="doc-1",
        text=(
            "Book 63, Hadith 91\n\n"
            "Which report is the saying about a different matter for people from Medina."
        ),
        source_location={"page": 2000},
        metadata_json={"domain_metadata": domain_metadata},
    )

    search = HybridChunkSearch()
    correct_score = search.score(query, correct)
    distractor_score = search.score(query, distractor)

    assert correct_score.score > distractor_score.score
    assert correct_score.breakdown["term_coverage"] > distractor_score.breakdown[
        "term_coverage"
    ]


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
