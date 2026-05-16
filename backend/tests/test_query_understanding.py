from ragstudio.services.domain_query_expansion_service import DomainQueryExpansionService
from ragstudio.services.query_understanding import understand_query


def test_understand_query_accepts_domain_expansion_passes():
    expansion = DomainQueryExpansionService().expand(
        "hanan",
        domain_metadata=[
            {
                "domain": "quran_tafseer",
                "document_type": "commentary",
                "language": "mixed",
                "tags": ["quran", "arabic"],
            }
        ],
    )

    understanding = understand_query("hanan", domain_expansion=expansion)

    assert understanding.intent == "lexical_expanded_token"
    assert understanding.answer_type == "reference"
    assert understanding.retrieval_strategy == "reference_first_hybrid"
    assert understanding.direct_evidence_required is True
    assert understanding.expanded_terms == ["حنانا", "وحنانا"]
    assert understanding.expansion_trace["expanded_terms"] == ["حنانا", "وحنانا"]
    assert [item.name for item in understanding.retrieval_passes[:2]] == [
        "lexical_expanded_token",
        "lexical_expanded_token",
    ]
    assert understanding.retrieval_passes[0].query == "حنانا"
    assert [item.match_type for item in understanding.retrieval_passes[:2]] == [
        "transliteration",
        "transliteration",
    ]
    assert [item.name for item in understanding.retrieval_passes[2:]] == [
        "semantic_metadata",
        "vector_db",
        "native_vector",
    ]


def test_understand_query_deep_copies_domain_expansion_trace():
    expansion = DomainQueryExpansionService().expand(
        "hanan",
        domain_metadata=[
            {
                "domain": "quran_tafseer",
                "document_type": "commentary",
                "language": "mixed",
                "tags": ["quran", "arabic"],
            }
        ],
    )

    understanding = understand_query("hanan", domain_expansion=expansion)

    understanding.expansion_trace["expanded_terms"].append("leaked")
    understanding.expansion_trace["expansions"][0]["terms"].append("also leaked")

    assert expansion.trace["expanded_terms"] == ["حنانا", "وحنانا"]
    assert expansion.trace["expansions"][0]["terms"] == ["حنانا", "وحنانا"]


def test_understanding_detects_arabic_exact_token_and_variants():
    understanding = understand_query("وَحَنَانًا")

    assert understanding.intent == "arabic_exact_token"
    assert understanding.answer_type == "reference"
    assert understanding.direct_evidence_required is True
    assert understanding.arabic_query_variants == ["وحنانا", "حنانا"]
    assert [item.name for item in understanding.retrieval_passes] == [
        "arabic_exact_token",
        "semantic_metadata",
        "vector_db",
        "native_vector",
    ]


def test_understanding_still_detects_arabic_exact_token_without_domain_expansion():
    understanding = understand_query("حنانا")

    assert understanding.intent == "arabic_exact_token"


def test_understanding_detects_exact_quran_reference():
    understanding = understand_query("show Quran 19:13")

    assert understanding.intent == "reference"
    assert understanding.reference_hints == ["19:13"]
    assert understanding.direct_evidence_required is True
    assert [item.name for item in understanding.retrieval_passes][:2] == [
        "reference_exact",
        "semantic_metadata",
    ]


def test_understanding_detects_phrase_lookup():
    understanding = understand_query(
        "Find the verse that says Allah is the Light of the heavens and the earth"
    )

    assert understanding.intent == "phrase_lookup"
    assert "allah is the light of the heavens and the earth" in understanding.target_phrases
    assert [item.name for item in understanding.retrieval_passes][:2] == [
        "phrase_exact",
        "semantic_metadata",
    ]


def test_reference_query_with_context_uses_graph_context_hybrid_strategy():
    understanding = understand_query("Explain 1:5 and show the surrounding connected verses")

    assert understanding.intent == "reference"
    assert understanding.reference_hints == ["1:5"]
    assert understanding.retrieval_strategy == "graph_context_hybrid"
    assert understanding.graph_context_required is True
    assert understanding.direct_evidence_required is True


def test_semantic_query_uses_semantic_hybrid_strategy():
    understanding = understand_query("What does Ibn Kathir say about guidance?")

    assert understanding.intent == "semantic"
    assert understanding.retrieval_strategy == "semantic_hybrid"
    assert understanding.graph_context_required is False
